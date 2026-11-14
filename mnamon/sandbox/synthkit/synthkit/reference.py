"""``generation.mode: reference_sample``: fit the dictionary's DAG to a public sample.

The reference (``datasets/public/<slug>/data.csv`` + ``mapping.yaml``, written by
the agents service's ``fetch_public_dataset`` after a human approved it) is mapped
onto our dictionary, then every mapped field gets a fitted distribution:

* category / boolean: P(field | mapped category parents) from counts, Laplace
  smoothed over the dictionary's values; cells with fewer than ``min_cell`` rows
  fall back to the field's fitted marginal (``default``);
* integer / float: empirical quantiles (``dist: empirical``), per parent cell
  when the cell is big enough.

Unmapped fields keep their dictionary definition (zero-shot) and still condition
on the fitted ones, so the DAG stays one DAG. The dictionary's hard rules are
applied afterwards by the sampler as usual. A field is NOT fitted (kept
zero-shot, reason recorded) when its column is missing, its values cannot be
mapped, or too many numeric values fall outside the dictionary's range (a
semantic mismatch, e.g. an installment *rate class* mapped to a ratio).
Deterministic: numpy/pandas only, no SDV (BSL licence).
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

N_QUANTILES = 101
MIN_CELL = 20
MIN_COVERAGE = 0.5
MAX_OUT_OF_RANGE = 0.2
ALPHA = 0.5
_BAND = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)\s*$")
_TRUE = {"1", "true", "yes", "y", "t"}
_FALSE = {"0", "false", "no", "n", "f", "none"}


def _values(fdef: dict) -> list[Any]:
    if fdef.get("values"):
        return list(fdef["values"])
    dist = fdef.get("distribution") or {}
    if isinstance(dist, dict) and "dist" not in dist:
        return list(dist)
    return []


def _map_category(col: pd.Series, fdef: dict, spec: dict) -> tuple[pd.Series | None, str]:
    values = [str(v) for v in _values(fdef)]
    if spec.get("transform") == "bin":
        bands = [(v, _BAND.match(v)) for v in values]
        if not values or not all(m for _, m in bands):
            return None, "bin needs band labels like '18-25'"
        x = pd.to_numeric(col, errors="coerce")
        out = pd.Series([None] * len(col), index=col.index, dtype=object)
        for label, m in bands:
            lo, hi = float(m.group(1)), float(m.group(2))
            out[(x >= lo) & (x <= hi)] = label
        return out, ""
    vmap = {str(k): str(v) for k, v in (spec.get("values") or {}).items()}
    text = col.astype(str)
    out = text.map(vmap) if vmap else text.where(text.isin(values))
    return out.where(out.isin(values)), ""


def _map_boolean(col: pd.Series, spec: dict) -> pd.Series:
    vmap = {str(k).lower(): str(v).lower() for k, v in (spec.get("values") or {}).items()}
    low = col.astype(str).str.strip().str.lower().map(lambda v: vmap.get(v, v))
    return low.map(lambda v: True if v in _TRUE else (False if v in _FALSE else None))


def _map_numeric(col: pd.Series, fdef: dict, spec: dict) -> tuple[pd.Series | None, str]:
    x = pd.to_numeric(col, errors="coerce") * float(spec.get("scale", 1.0))
    rng = fdef.get("range")
    if rng is not None:
        present = x.dropna()
        out_share = float(((present < rng[0]) | (present > rng[1])).mean()) if len(present) else 0
        if out_share > MAX_OUT_OF_RANGE:
            return None, (
                f"{out_share:.0%} of values outside the dictionary range {rng}: "
                "semantic or unit mismatch, kept zero-shot"
            )
        x = x.where((x >= rng[0]) & (x <= rng[1]))
    return x, ""


def map_reference(
    ref: pd.DataFrame, mapping: dict, fields: dict[str, dict]
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Reference rows renamed/recoded to our fields; per-field status and reason."""
    mapped: dict[str, pd.Series] = {}
    info: dict[str, dict] = {}
    for name, spec in (mapping.get("fields") or {}).items():
        if name not in fields:
            info[name] = {"status": "skipped", "reason": "not a dictionary field"}
            continue
        column = spec.get("column")
        if column not in ref.columns:
            info[name] = {"status": "skipped", "reason": f"column {column!r} not in the data"}
            continue
        fdef = fields[name]
        col = ref[column].replace("", np.nan)
        if fdef["type"] == "category":
            series, why = _map_category(col, fdef, spec)
        elif fdef["type"] == "boolean":
            series, why = _map_boolean(col, spec), ""
        elif fdef["type"] in ("integer", "float"):
            series, why = _map_numeric(col, fdef, spec)
        else:
            series, why = None, f"type {fdef['type']} is not fitted (surface/id)"
        if series is None:
            info[name] = {"status": "skipped", "column": column, "reason": why}
            continue
        coverage = float(series.notna().mean()) if len(series) else 0.0
        if coverage < MIN_COVERAGE:
            info[name] = {
                "status": "skipped",
                "column": column,
                "reason": f"only {coverage:.0%} of values map to the dictionary",
            }
            continue
        mapped[name] = series
        info[name] = {"status": "fitted", "column": column, "coverage": round(coverage, 4)}
    return pd.DataFrame(mapped, index=ref.index), info


def _cat_table(series: pd.Series, values: list[Any]) -> dict:
    counts = series.astype(str).value_counts()
    raw = {str(v): float(counts.get(str(v), 0)) + ALPHA for v in values}
    total = sum(raw.values())
    return {v: round(raw[str(v)] / total, 6) for v in values}


def _quantiles(series: pd.Series) -> list[float]:
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    return [round(float(q), 6) for q in np.quantile(x, np.linspace(0, 1, N_QUANTILES))]


class ReferenceSampleError(ValueError):
    """The reference sample or its mapping cannot be used (load_spec -> SpecError)."""


def fit_fields(
    fields: dict[str, dict],
    mapped: dict[str, pd.Series] | pd.DataFrame,
    info: dict,
    source: str,
    order: list[str],
) -> dict[str, dict]:
    """New field definitions for every fitted field (others unchanged); ``order`` = DAG order."""
    frame = pd.DataFrame(mapped)
    out = copy.deepcopy(fields)
    fitted = [f for f, i in info.items() if i["status"] == "fitted"]
    for name in order:
        if name not in fitted:
            continue
        fdef = fields[name]
        declared = list(fdef.get("depends_on") or [])
        parents = [
            p for p in declared if p in fitted and fields[p]["type"] in ("category", "boolean")
        ]
        new = {
            k: v
            for k, v in fdef.items()
            if k not in ("distribution", "conditional", "depends_on", "p_true")
        }
        new["provenance"] = f"reference:{source}"
        col = frame[name]
        if fdef["type"] == "boolean":
            new["p_true"] = round(float(col.dropna().astype(bool).mean()), 6)
            parents = []  # booleans keep a marginal (the sampler has no conditional p_true)
        elif fdef["type"] == "category":
            values = _values(fdef)
            marginal = _cat_table(col.dropna(), values)
            new["values"] = values
            if parents:
                new["depends_on"] = parents
                cond: dict[str, Any] = {}
                sub = frame[[*parents, name]].dropna()
                for key, grp in sub.groupby([sub[p].astype(str) for p in parents]):
                    key = key if isinstance(key, tuple) else (key,)
                    if len(grp) >= MIN_CELL:
                        cond["|".join(map(str, key))] = _cat_table(grp[name], values)
                cond["default"] = marginal
                new["conditional"] = cond
            else:
                new["distribution"] = marginal
        else:
            marginal = {"dist": "empirical", "quantiles": _quantiles(col)}
            if parents:
                new["depends_on"] = parents
                cond = {}
                sub = frame[[*parents, name]].dropna()
                for key, grp in sub.groupby([sub[p].astype(str) for p in parents]):
                    key = key if isinstance(key, tuple) else (key,)
                    if len(grp) >= MIN_CELL:
                        cond["|".join(map(str, key))] = {
                            "dist": "empirical",
                            "quantiles": _quantiles(grp[name]),
                        }
                cond["default"] = marginal
                new["conditional"] = cond
            else:
                new["distribution"] = marginal
        dropped = [p for p in declared if p not in parents]
        info[name]["parents"] = parents
        if dropped:
            info[name]["dropped_parents"] = dropped
        out[name] = new
    return out


def apply_reference(
    raw: dict, base: Path, dict_data: dict, order: list[str]
) -> tuple[dict, dict, pd.DataFrame]:
    """``generation`` block -> (dictionary with fitted fields, reference info, mapped frame)."""
    gen = raw.get("generation") or {}
    if not gen.get("reference"):
        raise ReferenceSampleError(
            "reference_sample mode needs generation.reference (path to data.csv)"
        )
    ref_path = base / gen["reference"]
    map_path = base / gen["mapping"] if gen.get("mapping") else ref_path.parent / "mapping.yaml"
    if not ref_path.exists():
        raise ReferenceSampleError(f"reference sample not found: {ref_path}")
    mapping = yaml.safe_load(map_path.read_text(encoding="utf-8")) if map_path.exists() else None
    if not isinstance(mapping, dict):
        raise ReferenceSampleError(f"reference mapping not found or invalid: {map_path}")
    data = ref_path.read_bytes()
    ref = pd.read_csv(ref_path, dtype=str, keep_default_na=False)
    fields = dict_data.get("fields") or {}
    mapped, info = map_reference(ref, mapping, fields)
    source = mapping.get("source") or {}
    fitted_fields = fit_fields(
        fields, mapped, info, str(source.get("id", ref_path.parent.name)), order
    )
    out = dict(dict_data)
    out["fields"] = fitted_fields
    fitted = sorted(f for f, i in info.items() if i["status"] == "fitted")
    reference = {
        "path": str(gen["reference"]),
        "mapping": str(gen.get("mapping") or map_path.name),
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": len(ref),
        "source": source,
        "licence": source.get("licence"),
        "licence_status": source.get("licence_status"),
        "fields": info,
        "fitted": fitted,
        "zero_shot": sorted(
            f
            for f, d in fields.items()
            if f not in fitted and d.get("role", "feature") not in ("id", "surface")
        ),
        "label": mapping.get("label"),
        "dropped_columns": mapping.get("dropped_columns") or [],
        "min_cell": MIN_CELL,
    }
    label = mapping.get("label") or {}
    if label.get("column") in ref.columns and label.get("values"):
        coded = (
            ref[label["column"]].astype(str).map({str(k): v for k, v in label["values"].items()})
        )
        if coded.notna().any():
            reference["label_rate"] = round(float(coded.dropna().astype(float).mean()), 4)
    return out, reference, mapped[fitted] if fitted else mapped
