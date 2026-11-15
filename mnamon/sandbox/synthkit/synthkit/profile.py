"""``synthkit profile``: understand the model BEFORE generating test data.

Builds a small probe set of valid rows (half realistic DAG samples, half a
Latin-hypercube sweep over the declared ranges and categories, plus any sample
rows), calls the model and writes ``model-profile.json``:

signature · output type/range/positive rate · determinism · latency/errors ·
per-feature sensitivity (one-at-a-time sweep + permutation) · monotonicity vs the
declared ``monotone`` · decision-boundary estimate (band share, per-feature
near-boundary region, a linear surrogate on logit(score) that ``generate`` uses
for boundary-aware oversampling) · which protected / proxy / rule fields actually
move the output · positive rate per protected group · plain-language notes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, qmc
from sklearn.linear_model import LogisticRegression, Ridge

from synthkit import GENERATOR
from synthkit.expr import names
from synthkit.sampler import Sampler
from synthkit.spec import Dictionary, canonical_hash
from synthkit.target import Target

EPS = 0.01  # score change that counts as "moves the output"
BAND = 0.1  # |score - threshold| that counts as "near the boundary"


def model_inputs(dictionary: Dictionary, target: Target) -> list[str]:
    if target.input_columns:
        return list(target.input_columns)
    return [
        n
        for n, f in dictionary.fields.items()
        if f.get("role", "feature") not in ("surface", "label")
    ]


def _grid(fdef: dict, k: int = 5) -> list[Any]:
    if fdef["type"] in ("category", "boolean"):
        if fdef["type"] == "boolean":
            return [False, True]
        values = fdef.get("values")
        if values:
            return list(values)
        dist = fdef.get("distribution") or {}
        return list(dist.get("values", dist).keys())
    lo, hi = fdef.get("range") or [0, 1]
    pts = np.linspace(lo, hi, k)
    if fdef["type"] == "integer":
        return sorted({int(round(p)) for p in pts})
    return [float(p) for p in pts]


def _lhs_rows(
    sampler: Sampler, features: list[str], n: int, rng: np.random.Generator
) -> list[dict]:
    fields = sampler.fields
    sweep = [
        f
        for f in features
        if f in fields and fields[f]["type"] in ("category", "integer", "float", "boolean")
    ]
    if not sweep or n <= 0:
        return []
    lhs = qmc.LatinHypercube(d=len(sweep), seed=rng).random(n * 3)
    rows: list[dict] = []
    for u in lhs:
        if len(rows) >= n:
            break
        base = sampler.sample_row(rng)
        for j, f in enumerate(sweep):
            fdef = fields[f]
            if fdef["type"] in ("category", "boolean"):
                options = _grid(fdef)
                base[f] = options[min(int(u[j] * len(options)), len(options) - 1)]
            else:
                lo, hi = fdef.get("range") or [0, 1]
                value = lo + u[j] * (hi - lo)
                base[f] = int(round(value)) if fdef["type"] == "integer" else float(value)
        if not sampler.failed_rules(base):
            rows.append(base)
    return rows


def build_probes(
    sampler: Sampler,
    features: list[str],
    n: int,
    rng: np.random.Generator,
    sample: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict] = []
    for i in range(n - n // 2):
        row, _ = sampler.valid_row(rng, index=i)
        if row is not None:
            row["_probe"] = "dag"
            rows.append(row)
    for row in _lhs_rows(sampler, features, n // 2, rng):
        row["_probe"] = "lhs"
        rows.append(row)
    frame = pd.DataFrame(rows)
    if sample is not None and not sample.empty:
        extra = sample.copy()
        extra["_probe"] = "sample"
        frame = pd.concat([frame, extra], ignore_index=True)
    return frame


def _design(frame: pd.DataFrame, features: list[str], fields: dict) -> tuple[np.ndarray, dict]:
    """One-hot categories + standardised numerics; returns X and the encoding."""
    cols: list[np.ndarray] = []
    enc: dict[str, Any] = {"numeric": {}, "categorical": {}}
    for f in features:
        fdef = fields.get(f, {})
        if fdef.get("type") in ("integer", "float"):
            x = pd.to_numeric(frame[f], errors="coerce").fillna(0).to_numpy(dtype=float)
            mean, std = float(x.mean()), float(x.std() or 1.0)
            enc["numeric"][f] = {"mean": mean, "std": std}
            cols.append(((x - mean) / std)[:, None])
        elif fdef.get("type") in ("category", "boolean"):
            levels = [str(v) for v in _grid(fdef)]
            enc["categorical"][f] = levels
            values = frame[f].astype(str).to_numpy()
            cols.append(np.stack([(values == lv).astype(float) for lv in levels], axis=1))
    return (np.hstack(cols) if cols else np.zeros((len(frame), 0))), enc


def fit_surrogate(
    frame: pd.DataFrame,
    scores: np.ndarray,
    decisions: np.ndarray,
    features: list[str],
    fields: dict,
    threshold: float,
) -> dict:
    """A linear model on logit(score): cheap, JSON-able, good enough to aim sampling."""
    X, enc = _design(frame, features, fields)
    if X.shape[1] == 0:
        return {}
    binary = len(np.unique(scores)) <= 2
    if binary:
        if len(np.unique(decisions)) < 2:
            return {}
        model = LogisticRegression(max_iter=1000).fit(X, decisions)
        coef, intercept, fidelity = (
            model.coef_[0],
            float(model.intercept_[0]),
            float(model.score(X, decisions)),
        )
        fidelity_kind = "accuracy"
    else:
        p = np.clip(scores, 1e-4, 1 - 1e-4)
        y = np.log(p / (1 - p))
        model = Ridge(alpha=1.0).fit(X, y)
        coef, intercept, fidelity = model.coef_, float(model.intercept_), float(model.score(X, y))
        fidelity_kind = "r2"
    out: dict[str, Any] = {
        "kind": "linear_logit",
        "intercept": intercept,
        "numeric": {},
        "categorical": {},
        fidelity_kind: round(fidelity, 4),
        "threshold_logit": math.log(threshold / (1 - threshold)) if 0 < threshold < 1 else 0.0,
    }
    j = 0
    for f in features:
        if f in enc["numeric"]:
            out["numeric"][f] = {**enc["numeric"][f], "coef": float(coef[j])}
            j += 1
        elif f in enc["categorical"]:
            levels = enc["categorical"][f]
            out["categorical"][f] = {lv: float(coef[j + i]) for i, lv in enumerate(levels)}
            j += len(levels)
    return out


def surrogate_logit(surrogate: dict, frame: pd.DataFrame) -> np.ndarray:
    z = np.full(len(frame), float(surrogate.get("intercept", 0.0)))
    for f, p in (surrogate.get("numeric") or {}).items():
        if f in frame.columns:
            x = pd.to_numeric(frame[f], errors="coerce").fillna(p["mean"]).to_numpy(dtype=float)
            z += p["coef"] * (x - p["mean"]) / (p["std"] or 1.0)
    for f, levels in (surrogate.get("categorical") or {}).items():
        if f in frame.columns:
            z += frame[f].astype(str).map(levels).fillna(0.0).to_numpy(dtype=float)
    return z


def _cramers_v(a: pd.Series, b: pd.Series) -> float | None:
    table = pd.crosstab(a.astype(str), b.astype(str))
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    chi2 = chi2_contingency(table, correction=False)[0]
    n = table.to_numpy().sum()
    return round(float(math.sqrt(chi2 / (n * (min(table.shape) - 1)))), 4)


def _r(x: float) -> float:
    return round(float(x), 4)


def run_profile(
    target: Target,
    dictionary: Dictionary,
    plugin: dict,
    *,
    seed: int = 0,
    n_probe: int = 256,
    n_oat: int = 48,
    sample: pd.DataFrame | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    sampler = Sampler(dictionary)
    fields = dictionary.fields
    inputs = model_inputs(dictionary, target)
    missing = [c for c in inputs if c not in fields]
    features = [
        c
        for c in inputs
        if c in fields and fields[c].get("role", "feature") not in ("id", "surface", "label")
    ]
    notes: list[str] = []
    if missing:
        notes.append(f"Model inputs not in the data dictionary: {missing} (filled with nulls).")

    probes = build_probes(sampler, features, n_probe, rng, sample)
    for col in missing:
        probes[col] = None
    scores, decisions = target.score(probes)
    thr = target.threshold

    # determinism: same input → same score
    k = min(20, len(probes))
    again, _ = target.score(probes.iloc[:k])
    det_diff = float(np.max(np.abs(again - scores[:k]))) if k else 0.0

    output = {
        "type": (plugin.get("io") or {}).get("output", {}).get("type", "score"),
        "binary_scores": bool(len(np.unique(scores)) <= 2),
        "min": _r(scores.min()),
        "max": _r(scores.max()),
        "mean": _r(scores.mean()),
        "quantiles": {q: _r(np.quantile(scores, float(q))) for q in ("0.1", "0.5", "0.9")},
        "threshold": thr,
        "positive_rate": _r(decisions.mean()),
        "positive_rate_realistic": _r(decisions[(probes["_probe"] == "dag").to_numpy()].mean()),
        "in_unit_interval": bool(scores.min() >= 0 and scores.max() <= 1),
    }

    # one-at-a-time sweeps on a subset of realistic probes
    base = probes[probes["_probe"] == "dag"].head(n_oat).reset_index(drop=True)
    base_scores = scores[: len(base)] if len(base) else np.array([])
    sensitivity: dict[str, dict] = {}
    for f in features:
        fdef = fields[f]
        if fdef.get("type") in ("string", "id"):
            # Free text (a postcode, a name): sweep real values seen in the probes, never numbers.
            seen = [v for v in pd.unique(probes[f].dropna()) if str(v).strip()]
            grid = seen[:5]
            if not grid:
                continue
        else:
            grid = _grid(fdef)
        frames = []
        for value in grid:
            variant = base.copy()
            variant[f] = value
            frames.append(variant)
        swept = pd.concat(frames, ignore_index=True)
        s, d = target.score(swept)
        s = s.reshape(len(grid), len(base))
        d = d.reshape(len(grid), len(base))
        perm = probes.copy()
        perm[f] = rng.permutation(perm[f].to_numpy())
        ps, pd_ = target.score(perm)
        role = fdef.get("role", "feature")
        entry = {
            "role": role,
            "oat_mean_range": _r((s.max(0) - s.min(0)).mean()),
            "oat_max_abs_delta": _r(np.abs(s - base_scores).max()),
            "oat_flip_rate": _r((d.max(0) != d.min(0)).mean()),
            "perm_mean_abs_delta": _r(np.abs(ps - scores).mean()),
            "perm_flip_rate": _r((pd_ != decisions).mean()),
            "by_value": {str(v): _r(s[i].mean()) for i, v in enumerate(grid)},
        }
        entry["moves_output"] = bool(
            entry["oat_mean_range"] > EPS or entry["perm_mean_abs_delta"] > EPS
        )
        if fdef.get("proxy_for"):
            entry["proxy_for"] = fdef["proxy_for"]
        sensitivity[f] = entry
    ranking = sorted(sensitivity, key=lambda f: -sensitivity[f]["oat_mean_range"])

    # monotonicity vs declared
    monotonicity: dict[str, dict] = {}
    for f in features:
        direction = fields[f].get("monotone")
        if direction not in ("increasing", "decreasing"):
            continue
        lo, hi = fields[f].get("range") or [None, None]
        step = fields[f].get("monotone_step") or (
            1 if fields[f]["type"] == "integer" else ((hi - lo) / 10 if hi is not None else 0.1)
        )
        up = base.copy()
        up[f] = pd.to_numeric(up[f]) + step
        if hi is not None:
            up[f] = up[f].clip(upper=hi)
        us, _ = target.score(up)
        delta = us - base_scores
        bad = delta < -1e-9 if direction == "increasing" else delta > 1e-9
        monotonicity[f] = {
            "declared": direction,
            "step": step,
            "violation_rate": _r(bad.mean()),
            "max_violation": _r(np.abs(delta[bad]).max() if bad.any() else 0.0),
            "holds": bool(not bad.any()),
        }

    # decision boundary
    near = np.abs(scores - thr) <= BAND
    region: dict[str, Any] = {}
    if near.any():
        nb = probes[near]
        for f in features:
            fdef = fields[f]
            if fdef["type"] in ("integer", "float"):
                x = pd.to_numeric(nb[f], errors="coerce").dropna()
                if len(x):
                    region[f] = {
                        "q10": _r(x.quantile(0.1)),
                        "q50": _r(x.median()),
                        "q90": _r(x.quantile(0.9)),
                    }
            else:
                region[f] = {
                    str(k): _r(v) for k, v in nb[f].astype(str).value_counts(normalize=True).items()
                }
    surrogate = fit_surrogate(probes, scores, decisions, features, fields, thr)
    boundary = {
        "threshold": thr,
        "band": BAND,
        "near_share": _r(near.mean()),
        "near_count": int(near.sum()),
        "region": region,
        "surrogate": surrogate,
    }

    # protected / proxy / rules: what actually moves the output
    realistic = probes[probes["_probe"] == "dag"]
    dag_mask = (probes["_probe"] == "dag").to_numpy()
    protected: dict[str, dict] = {}
    for f in dictionary.by_role("protected"):
        rates = (
            pd.Series(decisions[dag_mask], index=realistic.index)
            .groupby(realistic[f].astype(str))
            .mean()
        )
        protected[f] = {
            "model_input": f in inputs,
            "moves_output_directly": bool(sensitivity.get(f, {}).get("moves_output", False)),
            "positive_rate_by_group": {k: _r(v) for k, v in rates.items()},
            "selection_rate_ratio": _r(rates.min() / rates.max()) if rates.max() > 0 else None,
        }
    proxies: dict[str, dict] = {}
    for f in dictionary.by_role("proxy"):
        assoc = {
            p: _cramers_v(realistic[f], realistic[p])
            for p in fields[f].get("proxy_for") or []
            if p in realistic.columns
        }
        proxies[f] = {
            "proxy_for": fields[f].get("proxy_for") or [],
            "model_input": f in inputs,
            "moves_output": bool(sensitivity.get(f, {}).get("moves_output", False)),
            "association_cramers_v": assoc,
        }
    rules = []
    for rule in dictionary.rules:
        read = sorted(names(rule["expr"]))
        moving = [f for f in read if sensitivity.get(f, {}).get("moves_output")]
        rules.append(
            {
                "id": rule["id"],
                "severity": rule.get("severity", "hard"),
                "fields": read,
                "fields_moving_output": moving,
            }
        )
    label = None
    if dictionary.label_rule:
        y = np.array([sampler.label(r) for r in realistic.to_dict(orient="records")], dtype=float)
        ok = ~np.isnan(y)
        if ok.any():
            label = {
                "name": dictionary.label_rule.get("name", "label"),
                "positive_rate": _r(y[ok].mean()),
                "agreement_with_decision": _r((y[ok] == decisions[dag_mask][ok]).mean()),
            }

    for f, p in proxies.items():
        if p["moves_output"]:
            for attr in p["proxy_for"]:
                if attr in protected and not protected[attr]["moves_output_directly"]:
                    notes.append(
                        f"{f} moves the output and stands in for {attr}, which the model does "
                        f"not use directly: test with causal and proxy-only twins, not only "
                        f"attribute-only twins."
                    )
    for f, p in protected.items():
        if not p["model_input"]:
            notes.append(f"{f} is not a model input: attribute-only twins will show no gap.")
        elif p["moves_output_directly"]:
            notes.append(f"{f} (protected) moves the output directly.")
    for f, m in monotonicity.items():
        if not m["holds"]:
            notes.append(
                f"{f}: declared {m['declared']} but violated on "
                f"{m['violation_rate']:.0%} of probes."
            )
    if det_diff > 1e-9:
        notes.append(
            f"Non-deterministic: the same input changed the score by up to {det_diff:.4g}."
        )
    if boundary["near_share"] < 0.05:
        notes.append("Few probes near the decision boundary: use boundary-aware sampling.")

    return {
        "generator": GENERATOR,
        "seed": seed,
        "target": {
            "name": target.name,
            "access_type": target.kind,
            "plugin": plugin.get("id"),
        },
        "signature": {
            "inputs": inputs,
            "types": target.input_types,
            "from": "model" if target.input_columns else "dictionary",
            "not_in_dictionary": missing,
            "dictionary_fields_not_inputs": [f for f in fields if f not in inputs],
        },
        "probes": {
            "n": len(probes),
            "by_kind": probes["_probe"].value_counts().to_dict(),
            "hash": canonical_hash(
                probes.drop(columns="_probe").astype(str).to_dict(orient="list")
            ),
        },
        "output": output,
        "determinism": {"max_abs_diff": _r(det_diff), "holds": det_diff <= 1e-9},
        "sensitivity": sensitivity,
        "sensitivity_ranking": ranking,
        "monotonicity": monotonicity,
        "decision_boundary": boundary,
        "protected": protected,
        "proxies": proxies,
        "rules": rules,
        "label_rule": label,
        "calls": target.stats(),
        "notes": notes,
    }


def write_profile(profile: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
