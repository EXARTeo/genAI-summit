"""Shared statistics: population stats, marginals, TV/KS complements."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

NUMERIC_STATS = ("mean", "median", "min", "max", "std")


def population_stat(frame: pd.DataFrame, key: str) -> float | None:
    """``sex.female`` → share of sex == female; ``years_experience.median`` → the median."""
    field, _, stat = key.partition(".")
    if field not in frame.columns or not stat:
        return None
    col = frame[field]
    if stat in NUMERIC_STATS:
        x = pd.to_numeric(col, errors="coerce").dropna()
        return float(getattr(x, stat)()) if len(x) else None
    return float((col.astype(str) == stat).mean())


def compare_population(frame: pd.DataFrame, stats: dict[str, Any]) -> dict[str, dict]:
    out = {}
    for key, stated in (stats or {}).items():
        observed = population_stat(frame, key)
        if observed is None:
            out[key] = {"stated": stated, "observed": None}
            continue
        stat = key.partition(".")[2]
        if stat in NUMERIC_STATS:
            rel = abs(observed - float(stated)) / max(abs(float(stated)), 1e-9)
            ok = rel <= 0.25
        else:
            rel = abs(observed - float(stated))
            ok = rel <= 0.05
        out[key] = {
            "stated": stated,
            "observed": round(observed, 4),
            "diff": round(rel, 4),
            "within_tolerance": bool(ok),
        }
    return out


def tv_complement(a: pd.Series, b: pd.Series) -> float:
    pa = a.astype(str).value_counts(normalize=True)
    pb = b.astype(str).value_counts(normalize=True)
    keys = set(pa.index) | set(pb.index)
    tv = 0.5 * sum(abs(pa.get(k, 0.0) - pb.get(k, 0.0)) for k in keys)
    return round(1.0 - float(tv), 4)


def ks_complement(a: pd.Series, b: pd.Series) -> float:
    xa = pd.to_numeric(a, errors="coerce").dropna()
    xb = pd.to_numeric(b, errors="coerce").dropna()
    if not len(xa) or not len(xb):
        return 0.0
    return round(1.0 - float(ks_2samp(xa, xb).statistic), 4)


def marginal(frame: pd.DataFrame, field: str, fdef: dict) -> dict:
    col = frame[field]
    if fdef["type"] in ("integer", "float"):
        x = pd.to_numeric(col, errors="coerce")
        return {
            "mean": round(float(x.mean()), 4),
            "median": round(float(x.median()), 4),
            "min": float(x.min()),
            "max": float(x.max()),
            "null_share": round(float(x.isna().mean()), 4),
        }
    shares = col.astype(str).value_counts(normalize=True)
    out: dict[str, Any] = {"observed": {str(k): round(float(v), 4) for k, v in shares.items()}}
    declared = fdef.get("distribution")
    if isinstance(declared, dict) and "dist" not in declared:
        total = sum(float(v) for v in declared.values()) or 1.0
        out["declared"] = {str(k): round(float(v) / total, 4) for k, v in declared.items()}
    return out


def entropy_norm(col: pd.Series) -> float:
    p = col.astype(str).value_counts(normalize=True).to_numpy()
    if len(p) <= 1:
        return 0.0
    return round(float(-(p * np.log(p)).sum() / np.log(len(p))), 4)


def compare_to_reference(frame: pd.DataFrame, reference: pd.DataFrame, fields: dict) -> dict:
    """TV/KS complement of each reference-fitted field: synthetic base rows vs the reference."""
    out: dict[str, float] = {}
    for f in reference.columns:
        if f not in frame.columns or f not in fields:
            continue
        ref = reference[f].dropna()
        if fields[f]["type"] in ("category", "boolean"):
            out[f"TVComplement.{f}"] = tv_complement(frame[f].dropna(), ref)
        elif fields[f]["type"] in ("integer", "float"):
            out[f"KSComplement.{f}"] = ks_complement(frame[f], ref)
    return out
