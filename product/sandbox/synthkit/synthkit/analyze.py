"""``synthkit analyze``: the dataset analysis the human sees before approving.

Five gates (synthetic-data.md § 2) plus diversity, informativeness and twin
validity → ``dataset-analysis.json`` + a short ``dataset-analysis.md``.

* schema: types, enums, ranges and nulls hold on rows meant to be valid; model
  signature columns present. Otherwise fail.
* business_rules: every hard rule 100 % on base rows (fail otherwise); soft rules
  within tolerance (warn otherwise).
* realism: TV/KS complement >= 0.8 vs a dictionary-only reference population and
  stated stats within tolerance; warn otherwise (often by design: balanced strata).
* coverage: every cell >= min_per_cell; fail otherwise.
* privacy: no PII patterns, no copies of a reference sample (fail); duplicate base
  rows > 5 % warn.
"""

from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from synthkit import GENERATOR
from synthkit.expr import evaluate
from synthkit.profile import surrogate_logit
from synthkit.sampler import Sampler
from synthkit.spec import GenerationSpec
from synthkit.stats import compare_population, entropy_norm, ks_complement, tv_complement

PII_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?:\+|00)\d[\d ()-]{8,}\d"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "national_id_11_digits": re.compile(r"\b\d{11}\b"),  # e.g. Greek AMKA
    "card_number": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}
META_PREFIX = "_"


def load_dataset(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, keep_default_na=True)


def _status(fails: bool, warns: bool = False) -> str:
    return "fail" if fails else ("warn" if warns else "pass")


def _schema_gate(frame: pd.DataFrame, fields: dict, signature: list[str]) -> dict:
    valid = (
        frame[frame["_expect_valid"].astype(str).str.lower() == "true"]
        if ("_expect_valid" in frame.columns)
        else frame
    )
    problems: list[str] = []
    missing = [f for f in fields if f not in frame.columns]
    if missing:
        problems.append(f"missing columns: {missing}")
    sig_missing = [c for c in signature if c not in frame.columns]
    if sig_missing:
        problems.append(f"model inputs missing: {sig_missing}")
    for f, fdef in fields.items():
        if f not in valid.columns:
            continue
        col = valid[f]
        nulls = col.isna()
        if nulls.any() and not fdef.get("nullable"):
            problems.append(f"{f}: {int(nulls.sum())} nulls but not nullable")
        present = col[~nulls]
        if fdef["type"] in ("integer", "float"):
            x = pd.to_numeric(present, errors="coerce")
            if x.isna().any():
                problems.append(f"{f}: non-numeric values")
            if fdef["type"] == "integer" and ((x.dropna() % 1) != 0).any():
                problems.append(f"{f}: non-integer values")
            rng = fdef.get("range")
            if rng is not None and ((x < rng[0]) | (x > rng[1])).any():
                problems.append(f"{f}: values outside {rng}")
        elif fdef["type"] == "category" and fdef.get("values"):
            allowed = {str(v) for v in fdef["values"]}
            bad = set(present.astype(str)) - allowed
            if bad:
                problems.append(f"{f}: unknown values {sorted(bad)[:5]}")
    return {"status": _status(bool(problems)), "problems": problems, "rows_checked": len(valid)}


def _rule_pass(records: list[dict], expr: str) -> float:
    if not records:
        return 1.0
    ok = 0
    for r in records:
        with contextlib.suppress(TypeError, ValueError, ZeroDivisionError):
            ok += bool(evaluate(expr, r))
    return round(ok / len(records), 4)


def _rules_gate(frame: pd.DataFrame, rules: list[dict]) -> dict:
    base = frame[frame["_test"] == "base"].to_dict(orient="records")
    realistic = frame[
        frame["_test"].isin(["base", "perturbation"]) | (frame["_twin_mode"] == "causal")
    ].to_dict(orient="records")
    out: dict[str, Any] = {"hard": {}, "soft": {}}
    fails = warns = False
    for rule in rules:
        sev = rule.get("severity", "hard")
        rate = _rule_pass(base, rule["expr"])
        entry = {"pass_rate_base": rate, "pass_rate_realistic": _rule_pass(realistic, rule["expr"])}
        if sev == "hard":
            fails |= rate < 1.0
        else:
            tol = float(rule.get("tolerance", 0.05))
            entry["tolerance"] = tol
            warns |= (1 - rate) > tol
        out[sev][rule["id"]] = entry
    out["status"] = _status(fails, warns)
    out["note"] = (
        "Attribute-only and proxy-only twins may break rules on purpose (they change "
        "one field and keep the rest); they are not gated."
    )
    return out


def _realism_gate(frame: pd.DataFrame, spec: GenerationSpec, seed: int) -> dict:
    d = spec.dictionary
    base = frame[frame["_test"] == "base"]
    sampler = Sampler(d)
    rng = np.random.default_rng(seed + 9973)
    ref_rows = [r for r in (sampler.valid_row(rng, index=i)[0] for i in range(1000)) if r]
    reference = pd.DataFrame(ref_rows)
    metrics: dict[str, float] = {}
    for f, fdef in d.fields.items():
        if f not in base.columns or fdef.get("role") in ("id", "surface"):
            continue
        if fdef["type"] == "category":
            metrics[f"TVComplement.{f}"] = tv_complement(base[f], reference[f])
        elif fdef["type"] in ("integer", "float"):
            metrics[f"KSComplement.{f}"] = ks_complement(base[f], reference[f])
    population = compare_population(base, d.population.get("stats") or {})
    low = {k: v for k, v in metrics.items() if v < 0.8}
    off = [k for k, v in population.items() if v.get("within_tolerance") is False]
    by = (spec.raw.get("strata") or {}).get("by") or []
    note = (
        f"Strata {by} are balanced by design, so their marginals differ from the population."
        if by
        else ""
    )
    return {
        "status": _status(False, bool(low or off)),
        "metrics": metrics,
        "below_0_8": low,
        "population_stats": population,
        "note": note,
        "reference": "1000 rows sampled from the dictionary alone (no strata, no transforms)",
    }


def _coverage_gate(frame: pd.DataFrame, spec: GenerationSpec) -> dict:
    cov = spec.raw.get("coverage") or {}
    cells = cov.get("cells") or (spec.dictionary.by_role("protected")[:2])
    need = int(cov.get("min_per_cell", 0))
    base = frame[frame["_test"] == "base"]
    counts = base.groupby([base[c].astype(str) for c in cells]).size() if cells else pd.Series()
    table = {"|".join(k if isinstance(k, tuple) else (k,)): int(v) for k, v in counts.items()}
    low = {k: v for k, v in table.items() if v < need}
    scenario_counts = frame.groupby(["_test", frame["_twin_mode"].fillna("")]).size()
    return {
        "status": _status(bool(low)),
        "cells": cells,
        "min_per_cell": need,
        "counts": table,
        "below_min": low,
        "by_scenario": {f"{t}:{m}" if m else t: int(v) for (t, m), v in scenario_counts.items()},
    }


def _privacy_gate(frame: pd.DataFrame, fields: dict, sample: pd.DataFrame | None) -> dict:
    hits: dict[str, int] = {}
    for col in frame.columns:
        if col.startswith(META_PREFIX) or frame[col].dtype.kind in "biuf":
            continue
        text = frame[col].dropna().astype(str)
        for name, pattern in PII_PATTERNS.items():
            n = int(text.map(lambda s, p=pattern: bool(p.search(s))).sum())
            if n:
                hits[f"{col}:{name}"] = n
    surface_sources = {
        f: (d.get("source") or {}).get("kind")
        for f, d in fields.items()
        if d.get("role") == "surface"
    }
    feats = [f for f, d in fields.items() if d.get("role", "feature") not in ("id", "surface")]
    base = frame[frame["_test"] == "base"][feats].astype(str)
    dup_rate = round(float(base.duplicated().mean()), 4) if len(base) else 0.0
    copies = 0
    if sample is not None and not sample.empty:
        common = [c for c in feats if c in sample.columns]
        merged = base[common].merge(sample[common].astype(str).drop_duplicates(), how="inner")
        copies = len(merged)
    return {
        "status": _status(bool(hits) or copies > 0, dup_rate > 0.05),
        "pii_pattern_hits": hits,
        "surface_sources": surface_sources,
        "duplicate_base_rows": dup_rate,
        "copies_of_reference_sample": copies,
        "note": "Surface fields come from Faker or curated synthetic lists only.",
    }


def _twin_validity(frame: pd.DataFrame, spec: GenerationSpec) -> dict:
    sampler = Sampler(spec.dictionary)
    by_id = frame.set_index("_row_id")
    twins = frame[frame["_test"] == "twin"]
    fields = list(spec.dictionary.fields)
    out: dict[str, Any] = {}
    for mode, group in twins.groupby("_twin_mode"):
        ok = 0
        for _, t in group.iterrows():
            b = by_id.loc[t["_twin_of"]]
            changed = {f for f in fields if str(b[f]) != str(t[f])}
            attr = str(t["_flip"]).split(":")[0] if mode != "proxy_only" else None
            if mode == "attribute_only":
                ok += changed == {attr}
            elif mode == "causal":
                allowed = sampler.descendants(attr) | {attr}
                ok += attr in changed and changed <= allowed
            else:  # proxy_only: only proxies changed, protected kept
                ok += bool(changed) and all(
                    spec.dictionary.fields[f].get("role") == "proxy" for f in changed
                )
        out[str(mode)] = {"pairs": len(group), "valid_share": round(ok / max(len(group), 1), 4)}
    return out


def _informativeness(frame: pd.DataFrame, profile: dict | None) -> dict:
    boundary = (profile or {}).get("decision_boundary") or {}
    surrogate = boundary.get("surrogate")
    if not surrogate:
        return {"available": False, "note": "No model profile: run `synthkit profile` first."}
    base = frame[frame["_test"] == "base"]
    z = surrogate_logit(surrogate, base)
    p = 1 / (1 + np.exp(-z))
    thr = float(boundary.get("threshold", 0.5))
    band = float(boundary.get("band", 0.1))
    near = np.abs(p - thr) <= band
    return {
        "available": True,
        "near_boundary_share": round(float(near.mean()), 4),
        "probe_near_share": boundary.get("near_share"),
        "predicted_positive_rate": round(float((p >= thr).mean()), 4),
        "note": "Surrogate estimate; the real scores come from the execute step.",
    }


def run_analysis(
    frame: pd.DataFrame,
    spec: GenerationSpec,
    *,
    seed: int = 0,
    profile: dict | None = None,
    sample: pd.DataFrame | None = None,
) -> dict:
    d = spec.dictionary
    profile = profile if profile is not None else spec.profile
    signature = ((profile or {}).get("signature") or {}).get("inputs") or []
    gates = {
        "schema": _schema_gate(frame, d.fields, signature),
        "business_rules": _rules_gate(frame, d.rules),
        "realism": _realism_gate(frame, spec, seed),
        "coverage": _coverage_gate(frame, spec),
        "privacy": _privacy_gate(frame, d.fields, sample),
    }
    feats = [f for f, x in d.fields.items() if x.get("role", "feature") not in ("id", "surface")]
    base = frame[frame["_test"] == "base"]
    diversity = {
        "unique_feature_rows_share": round(
            float(1 - base[feats].astype(str).duplicated().mean()), 4
        ),
        "entropy": {f: entropy_norm(base[f]) for f in feats},
    }
    overall = (
        "fail"
        if any(g["status"] == "fail" for g in gates.values())
        else "warn"
        if any(g["status"] == "warn" for g in gates.values())
        else "pass"
    )
    return {
        "generator": GENERATOR,
        "dataset": {"rows": len(frame), "by_test": frame["_test"].value_counts().to_dict()},
        "overall": overall,
        "gates": gates,
        "diversity": diversity,
        "informativeness": _informativeness(frame, profile),
        "twin_validity": _twin_validity(frame, spec),
    }


def to_markdown(a: dict, name: str) -> str:
    icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [
        f"# Dataset analysis: {name}",
        "",
        f"Overall: **{icon[a['overall']]}** "
        f"({a['dataset']['rows']} rows: {a['dataset']['by_test']})",
        "",
        "| Gate | Status | Detail |",
        "| --- | --- | --- |",
    ]
    g = a["gates"]
    lines.append(
        f"| Schema | {icon[g['schema']['status']]} | "
        f"{'; '.join(g['schema']['problems']) or 'types, enums, ranges, nulls OK'} |"
    )
    hard = ", ".join(
        f"{k} {v['pass_rate_base']:.0%}" for k, v in g["business_rules"]["hard"].items()
    )
    soft = ", ".join(
        f"{k} {v['pass_rate_base']:.0%}" for k, v in g["business_rules"]["soft"].items()
    )
    lines.append(
        f"| Business rules | {icon[g['business_rules']['status']]} | hard: {hard or '-'}; "
        f"soft: {soft or '-'} |"
    )
    low = ", ".join(f"{k} {v}" for k, v in g["realism"]["below_0_8"].items()) or "all ≥ 0.8"
    lines.append(f"| Realism | {icon[g['realism']['status']]} | {low}. {g['realism']['note']} |")
    lines.append(
        f"| Coverage | {icon[g['coverage']['status']]} | cells {g['coverage']['cells']}, "
        f"min {g['coverage']['min_per_cell']}, below: {g['coverage']['below_min'] or 'none'} |"
    )
    p = g["privacy"]
    lines.append(
        f"| Privacy | {icon[p['status']]} | PII hits: {p['pii_pattern_hits'] or 'none'}; "
        f"duplicate base rows {p['duplicate_base_rows']:.1%} |"
    )
    lines += ["", "## Twins", ""]
    for mode, v in a["twin_validity"].items():
        lines.append(f"- {mode}: {v['pairs']} pairs, {v['valid_share']:.0%} valid")
    inf = a["informativeness"]
    lines += ["", "## Informativeness", ""]
    lines.append(
        f"- Near the decision boundary (surrogate): {inf['near_boundary_share']:.0%} "
        f"(probes: {inf['probe_near_share']})"
        if inf.get("available")
        else f"- {inf['note']}"
    )
    lines.append(f"- Unique feature rows: {a['diversity']['unique_feature_rows_share']:.0%}")
    return "\n".join(lines) + "\n"


def write_analysis(a: dict, out_dir: Path, name: str) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dataset-analysis.json").write_text(
        json.dumps(a, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "dataset-analysis.md").write_text(to_markdown(a, name), encoding="utf-8")
