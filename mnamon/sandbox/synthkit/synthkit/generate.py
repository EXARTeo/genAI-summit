"""``synthkit generate``: GenerationSpec + seed → dataset + DataCard.yaml.

G3 base sample (ancestral, optionally balanced per stratum) → boundary-aware
oversampling (needs model-profile.json) → G4 hard-rule repair/reject → G5
surface fields (Faker / curated lists / custom) → label rule → G6 transforms
(counterfactual twins in 3 modes, edge cases, perturbations) → coverage top-up
→ G8 Data Card. Every row carries meta columns (``_row_id``, ``_test``,
``_twin_of``, ``_twin_mode``, ``_flip``, ``_edge``, ``_expect_valid``,
``_boundary``) so the execute step can pair results without guessing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from synthkit import GENERATOR
from synthkit.expr import evaluate
from synthkit.profile import surrogate_logit
from synthkit.sampler import CUSTOM_SAMPLERS, Sampler
from synthkit.spec import TWIN_MODES, GenerationSpec, canonical_hash
from synthkit.stats import compare_population, compare_to_reference, marginal

META = [
    "_row_id",
    "_test",
    "_twin_of",
    "_twin_mode",
    "_flip",
    "_edge",
    "_expect_valid",
    "_boundary",
]


def _load_custom(spec: GenerationSpec) -> None:
    CUSTOM_SAMPLERS.clear()
    if spec.custom_path is None:
        return
    module_spec = importlib.util.spec_from_file_location("synthkit_custom", spec.custom_path)
    if module_spec is None or module_spec.loader is None:
        raise ValueError(f"cannot load {spec.custom_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)  # registers via @synthkit.sampler.sampler


def _values(fdef: dict) -> list[Any]:
    if fdef.get("values"):
        return list(fdef["values"])
    dist = fdef.get("distribution") or {}
    return list(dist.get("values", dist).keys())


class Generator:
    def __init__(self, spec: GenerationSpec, seed: int) -> None:
        self.spec = spec
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        _load_custom(spec)
        self.sampler = Sampler(spec.dictionary)
        self.fields = spec.dictionary.fields
        self.rows: list[dict] = []
        self.rejected = 0
        self.repairs = 0
        self.topped_up = 0

    # -- helpers ------------------------------------------------------------
    def _new(self, row: dict, test: str, **meta: Any) -> dict:
        out = dict(row)
        out["_row_id"] = f"r{len(self.rows):06d}"
        out["_test"] = test
        for key in META[2:]:
            out.setdefault(key, None)
        out.update(meta)
        if out["_expect_valid"] is None:
            out["_expect_valid"] = True
        self.rows.append(out)
        return out

    def _valid(self, given: dict | None = None) -> dict | None:
        row, repairs = self.sampler.valid_row(self.rng, given, index=len(self.rows))
        self.repairs += repairs
        if row is None:
            self.rejected += 1
        return row

    def _cells(self, by: list[str]) -> list[dict]:
        return [
            dict(zip(by, combo, strict=True))
            for combo in itertools.product(*[_values(self.fields[f]) for f in by])
        ]

    # -- G3/G4: base rows ---------------------------------------------------------
    def base(self) -> None:
        n = self.spec.n
        strata = self.spec.raw.get("strata") or {}
        by = strata.get("by") or []
        givens: list[dict | None]
        if by and strata.get("balance", True):
            cells = self._cells(by)
            givens = [cells[i % len(cells)] for i in range(n)]
        else:
            givens = [None] * n
        boundary = self.spec.raw.get("boundary") or {}
        surrogate = ((self.spec.profile or {}).get("decision_boundary") or {}).get("surrogate")
        n_boundary = int(round(n * float(boundary.get("share", 0)))) if surrogate else 0
        # Boundary slots spread evenly across the strata.
        boundary_slots = (
            set(np.linspace(0, n - 1, n_boundary).astype(int).tolist()) if n_boundary else set()
        )
        pool_k = int(boundary.get("pool", 5))
        for i, given in enumerate(givens):
            if i in boundary_slots:
                row = self._boundary_row(given, surrogate, pool_k)
                if row is not None:
                    self._new(row, "base", _boundary=True)
                    continue
            row = self._valid(given)
            if row is not None:
                self._new(row, "base", _boundary=False)

    def _boundary_row(self, given: dict | None, surrogate: dict, k: int) -> dict | None:
        """Best of k valid candidates: the one the surrogate puts closest to the threshold."""
        candidates = [r for r in (self._valid(given) for _ in range(k)) if r is not None]
        if not candidates:
            return None
        z = surrogate_logit(surrogate, pd.DataFrame(candidates))
        return candidates[int(np.argmin(np.abs(z - surrogate.get("threshold_logit", 0.0))))]

    # -- G6: transforms -------------------------------------------------------------
    def twins(self, t: dict) -> None:
        attr = t["attribute"]
        modes = t.get("modes") or list(TWIN_MODES)
        proxies = t.get("proxies") or [
            f for f, d in self.fields.items() if attr in (d.get("proxy_for") or [])
        ]
        targets = t.get("to") or _values(self.fields[attr])
        bases = [r for r in self.rows if r["_test"] == "base"][: int(t.get("max_base", 10**9))]
        keep = set(self.sampler.fields) - self.sampler.descendants(attr) - {attr}
        for row in bases:
            core = {f: row[f] for f in self.fields}
            for new in targets:
                if new == row[attr]:
                    continue
                flip = f"{attr}:{row[attr]}->{new}"
                meta = {"_twin_of": row["_row_id"], "_flip": flip, "_boundary": row["_boundary"]}
                if "attribute_only" in modes:
                    twin = dict(core)
                    twin[attr] = new
                    self._new(twin, "twin", _twin_mode="attribute_only", **meta)
                if "causal" in modes:
                    given = {f: core[f] for f in keep}
                    given[attr] = new
                    twin = self._valid(given)
                    if twin is not None:
                        self._new(twin, "twin", _twin_mode="causal", **meta)
                if "proxy_only" in modes and proxies:
                    twin = dict(core)
                    flipped = dict(core)
                    flipped[attr] = new
                    for p in proxies:
                        for _ in range(10):
                            value = self.sampler.sample_value(p, flipped, self.rng)
                            if value != core[p]:
                                break
                        twin[p] = value
                    if all(twin[p] == core[p] for p in proxies):
                        continue  # the proxy has one likely value either way: no pair
                    pmeta = dict(meta, _flip=f"{','.join(proxies)} as if {attr}={new}")
                    self._new(twin, "twin", _twin_mode="proxy_only", **pmeta)

    def edge_cases(self, t: dict) -> None:
        bases = [r for r in self.rows if r["_test"] == "base"]
        if not bases:
            return
        template = {f: bases[0][f] for f in self.fields}
        targets = t.get("fields") or [
            f for f, d in self.fields.items() if d.get("role", "feature") in ("feature", "proxy")
        ]
        for f in targets:
            fdef = self.fields[f]
            cases: list[tuple[str, Any, bool]] = []
            if fdef["type"] in ("integer", "float") and fdef.get("range"):
                lo, hi = fdef["range"]
                unit = 1 if fdef["type"] == "integer" else (hi - lo) * 0.01 or 0.01
                cases += [
                    ("min", lo, True),
                    ("max", hi, True),
                    ("below_min", lo - unit, False),
                    ("above_max", hi + unit, False),
                ]
            elif fdef["type"] == "category":
                cases += [("unknown_category", "__unknown__", False)]
            cases.append(("null", None, bool(fdef.get("nullable"))))
            for label, value, valid in cases:
                row = dict(template)
                row[f] = value
                if valid and self.sampler.failed_rules(row):
                    valid = False  # the boundary value breaks a hard rule for this template
                self._new(
                    row,
                    "edge",
                    _edge=f"{f}:{label}",
                    _expect_valid=valid,
                    _twin_of=bases[0]["_row_id"],
                )

    def perturbation(self, t: dict) -> None:
        targets = t.get("fields") or [f for f, d in self.fields.items() if d.get("monotone")]
        delta = t.get("delta", 1)
        bases = [r for r in self.rows if r["_test"] == "base"][: int(t.get("max_base", 10**9))]
        for f in targets:
            hi = (self.fields[f].get("range") or [None, None])[1]
            for row in bases:
                twin = {k: row[k] for k in self.fields}
                # Only numeric values shift by a delta; a category is left alone.
                numeric = isinstance(twin[f], int | float) and not isinstance(twin[f], bool)
                value = twin[f] + delta if numeric else None
                if value is None or (hi is not None and value > hi):
                    continue
                twin[f] = value
                valid = not self.sampler.failed_rules(twin)
                self._new(
                    twin,
                    "perturbation",
                    _twin_of=row["_row_id"],
                    _flip=f"{f}{delta:+}",
                    _expect_valid=valid,
                    _boundary=row["_boundary"],
                )

    def coverage(self) -> dict:
        cov = self.spec.raw.get("coverage") or {}
        cells_by = cov.get("cells") or []
        need = int(cov.get("min_per_cell", 0))
        if not cells_by or not need:
            return {}
        base = pd.DataFrame([r for r in self.rows if r["_test"] == "base"])
        counts = {}
        for cell in self._cells(cells_by):
            mask = np.ones(len(base), dtype=bool)
            for f, v in cell.items():
                mask &= (base[f].astype(str) == str(v)).to_numpy()
            have = int(mask.sum())
            for _ in range(max(0, need - have)):
                row = self._valid(cell)
                if row is not None:
                    self._new(row, "base", _boundary=False)
                    self.topped_up += 1
                    have += 1
            counts["|".join(f"{f}={v}" for f, v in cell.items())] = have
        return {
            "cells": cells_by,
            "min_per_cell": need,
            "counts": counts,
            "topped_up": self.topped_up,
        }

    # -- run --------------------------------------------------------------------
    def run(self) -> tuple[pd.DataFrame, dict]:
        self.base()
        coverage = self.coverage()
        transforms = self.spec.raw.get("transforms") or []
        for t in transforms:
            getattr(self, t["kind"])(t)
        frame = pd.DataFrame(self.rows)
        label = self.spec.dictionary.label_rule
        if label:
            frame[label.get("name", "label")] = [
                self.sampler.label({f: r[f] for f in self.fields}) for r in self.rows
            ]
        for f, fdef in self.fields.items():
            if fdef["type"] == "integer":
                frame[f] = pd.array(
                    [None if v is None or v != v else int(v) for v in frame[f]], dtype="Int64"
                )
        cols = list(self.fields) + ([label.get("name", "label")] if label else []) + META
        return frame[cols], coverage


def _rule_rates(sampler: Sampler, frame: pd.DataFrame, rules: list[dict]) -> dict:
    out = {}
    records = frame.to_dict(orient="records")
    for rule in rules:
        ok = []
        for r in records:
            try:
                ok.append(bool(evaluate(rule["expr"], r)))
            except (TypeError, ValueError, ZeroDivisionError):
                ok.append(False)
        out[rule["id"]] = round(float(np.mean(ok)) if ok else 1.0, 4)
    return out


def data_card(
    spec: GenerationSpec,
    gen: Generator,
    frame: pd.DataFrame,
    coverage: dict,
    content_sha256: str,
    files: dict[str, str],
) -> dict:
    d = spec.dictionary
    base = frame[frame["_test"] == "base"]
    spec_hash = spec.hash()
    dataset_id = "ds-sha256:" + canonical_hash(
        {"spec": spec_hash, "seed": gen.seed, "generator": GENERATOR}
    )
    provenance = {
        "fields": {n: f.get("provenance", "dictionary") for n, f in d.fields.items()},
        "rules": {r["id"]: r.get("provenance", "dictionary") for r in d.rules},
    }
    if d.label_rule:
        provenance["label_rule"] = d.label_rule.get("provenance", "dictionary")
    assumptions = [
        {
            "field": n,
            "provenance": "llm_assumption",
            "what": "distribution/conditional"
            + (f" P({n} | {', '.join(f['depends_on'])})" if f.get("depends_on") else ""),
        }
        for n, f in d.fields.items()
        if f.get("provenance") == "llm_assumption"
    ]
    assumptions += [
        {"rule": r["id"], "expr": r["expr"], "provenance": "llm_assumption"}
        for r in d.rules
        if r.get("provenance") == "llm_assumption"
    ]
    twins = frame[frame["_test"] == "twin"]
    pairs = []
    for mode in TWIN_MODES:
        for _, t in twins[twins["_twin_mode"] == mode].head(2).iterrows():
            b = frame[frame["_row_id"] == t["_twin_of"]].iloc[0]
            changed = {f: [b[f], t[f]] for f in d.fields if str(b[f]) != str(t[f])}
            pairs.append(
                {"mode": mode, "base": t["_twin_of"], "twin": t["_row_id"], "changed": changed}
            )
    protected = d.by_role("protected")
    label = d.label_rule
    ref = spec.reference
    inputs_used = [{"path": d.source}]
    if ref:
        inputs_used += [
            {"path": ref["path"], "sha256": ref["sha256"], "kind": "reference_sample"},
            {"path": ref["mapping"], "kind": "reference_mapping"},
        ]
    if spec.profile:
        inputs_used.append({"path": spec.raw["model_profile"]})
    card = {
        "dataset_id": dataset_id,
        "name": spec.name,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": spec.raw.get("purpose") or {},
        "target": {
            "plugin": spec.plugin.get("id"),
            "access_type": (spec.plugin.get("access") or {}).get("type"),
        },
        "inputs_used": inputs_used,
        "generation": {
            "method": "reference_sample" if ref else "dag_sampler",
            "mode": spec.mode,
            "generator_version": GENERATOR,
            "seed": gen.seed,
            "spec_sha256": spec_hash,
            "boundary_aware": bool(spec.raw.get("boundary") and spec.profile),
            "custom": (
                {
                    "file": spec.raw.get("custom"),
                    "ai_generated": True,
                    "sha256": hashlib.sha256(spec.custom_path.read_bytes()).hexdigest(),
                }
                if spec.custom_path
                else None
            ),
            "assumptions": assumptions,
        },
        "ai_generated": bool(spec.custom_path),
        "provenance": provenance,
        "composition": {
            "rows": len(frame),
            "by_test": frame["_test"].value_counts().to_dict(),
            "twins_by_mode": twins["_twin_mode"].value_counts().to_dict(),
            "boundary_rows": int(base["_boundary"].fillna(False).astype(bool).sum()),
            "strata": {p: base[p].astype(str).value_counts().to_dict() for p in protected},
            "transforms": [t["kind"] for t in spec.raw.get("transforms") or []],
            "label": (
                {
                    "name": label.get("name"),
                    "rule": label["expr"],
                    "positive_rate": round(float(base[label.get("name", "label")].mean()), 4),
                }
                if label
                else None
            ),
        },
        "distributions": {
            n: marginal(base, n, f)
            for n, f in d.fields.items()
            if f["type"] in ("category", "integer", "float")
        },
        "population": compare_population(base, d.population.get("stats") or {}),
        "reference": (
            {
                "source": ref["source"],
                "licence": ref["licence"],
                "licence_status": ref["licence_status"],
                "path": ref["path"],
                "sha256": ref["sha256"],
                "rows": ref["rows"],
                "fitted_fields": ref["fitted"],
                "zero_shot_fields": ref["zero_shot"],
                "fit": ref["fields"],
                "dropped_columns": ref["dropped_columns"],
                "label": ref.get("label"),
                "label_rate": ref.get("label_rate"),
                "realism_vs_reference": compare_to_reference(base, spec.reference_frame, d.fields),
            }
            if ref
            else None
        ),
        "group_balance": {p: base[p].astype(str).value_counts().to_dict() for p in protected},
        "rules": {
            "pass_rate_base": _rule_rates(gen.sampler, base, d.rules),
            "repairs": gen.repairs,
            "rejected_rows": gen.rejected,
        },
        "coverage": coverage,
        "sample_rows": base.head(5).drop(columns=META[1:]).to_dict(orient="records"),
        "twin_pairs": pairs,
        "files": files,
        "content_sha256": content_sha256,
        "limitations": [
            (
                f"Synthetic rows fitted to a public reference ({(ref['source'] or {}).get('id')}, "
                f"{ref['licence']}): fields {ref['fitted']} follow its distributions, which "
                "describe a different population than the audited system's applicants; "
                f"{ref['zero_shot']} are zero-shot from the dictionary."
                if ref
                else "Synthetic only: realism is checked against the dictionary and stated "
                "population stats, not against real applicants."
            ),
            *(
                ["Strata are balanced by design: group rates are not population rates."]
                if (spec.raw.get("strata") or {}).get("by")
                else []
            ),
            *(
                [
                    "Boundary-aware rows are chosen with a linear surrogate of the model; they "
                    "over-represent near-threshold cases by design."
                ]
                if spec.raw.get("boundary") and spec.profile
                else []
            ),
        ],
        "data_policy": "synthetic_only",
        "reference_data": (
            f"public:{ref['licence']} (fitted statistics only; no reference row is copied)"
            if ref
            else None
        ),
        "review": {"status": "proposed"},
    }
    return card


def _plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, float) and obj != obj:  # NaN
        return None
    return obj


def generate(spec: GenerationSpec, seed: int, out_dir: Path, fmt: str = "both") -> dict:
    gen = Generator(spec, seed)
    frame, coverage = gen.run()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_bytes = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    content_sha256 = hashlib.sha256(csv_bytes).hexdigest()
    files: dict[str, str] = {}
    if fmt in ("csv", "both"):
        (out_dir / "dataset.csv").write_bytes(csv_bytes)
        files["csv"] = "dataset.csv"
    if fmt in ("parquet", "both"):
        frame.to_parquet(out_dir / "dataset.parquet", index=False)
        files["parquet"] = "dataset.parquet"
    card = _plain(data_card(spec, gen, frame, coverage, content_sha256, files))
    (out_dir / "DataCard.yaml").write_text(
        yaml.safe_dump(card, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return card
