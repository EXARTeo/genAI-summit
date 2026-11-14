"""Causal-graph (DAG) sampler driven by a ``data-dictionary.yaml``.

Implements the deterministic half of docs/architecture/synthetic-data.md: ancestral sampling
from ``depends_on`` + ``conditional``, hard-rule enforcement (resample the row, then reject),
the ``label_rule``, and counterfactual twins in two modes (ceteris paribus, and causal, which
re-samples the flipped attribute's descendants). Same ``(dictionary, seed)`` gives the same rows.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from seedlib.expr import evaluate

MAX_RESAMPLE_ROUNDS = 10


@dataclass
class Dictionary:
    """A parsed data dictionary."""

    fields: dict[str, dict[str, Any]]
    rules: list[dict[str, Any]] = field(default_factory=list)
    label_rule: dict[str, Any] | None = None
    population: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Dictionary":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            fields=raw["fields"],
            rules=raw.get("rules", []),
            label_rule=raw.get("label_rule"),
            population=raw.get("population", {}),
        )

    def order(self) -> list[str]:
        """Fields in topological order of ``depends_on``."""
        done: list[str] = []
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in done:
                return
            if name in visiting:
                raise ValueError(f"cycle in depends_on at {name}")
            visiting.add(name)
            for parent in self.fields[name].get("depends_on", []):
                if parent not in self.fields:
                    raise ValueError(f"{name} depends on unknown field {parent}")
                visit(parent)
            visiting.discard(name)
            done.append(name)

        for name in self.fields:
            visit(name)
        return done

    def descendants(self, name: str) -> list[str]:
        """Fields that depend on ``name`` directly or transitively, in topological order."""
        out: set[str] = set()
        changed = True
        while changed:
            changed = False
            for child, spec in self.fields.items():
                if child not in out and ({name} | out) & set(spec.get("depends_on", [])):
                    out.add(child)
                    changed = True
        return [f for f in self.order() if f in out]

    def by_role(self, role: str) -> list[str]:
        return [n for n, s in self.fields.items() if s.get("role") == role]


# ---- per-field sampling -----------------------------------------------------------------


def _pick(rng: np.random.Generator, dist: Mapping[Any, float], n: int) -> np.ndarray:
    values = list(dist.keys())
    probs = np.array([float(p) for p in dist.values()])
    idx = rng.choice(len(values), size=n, p=probs / probs.sum())
    return np.array(values, dtype=object)[idx]


def _lookup(cond: Mapping[Any, Any], key: Any) -> Any:
    for candidate in (key, str(key)):
        if candidate in cond:
            return cond[candidate]
    return cond["default"]


def _param(spec: Mapping[str, Any], key: str, rows: pd.DataFrame) -> np.ndarray:
    if f"{key}_expr" in spec:
        expr = spec[f"{key}_expr"]
        return np.array([float(evaluate(expr, r)) for r in rows.to_dict("records")])
    return np.full(len(rows), float(spec[key]))


def _draw(rng: np.random.Generator, spec: Mapping[str, Any], rows: pd.DataFrame) -> np.ndarray:
    n = len(rows)
    kind = spec["dist"]
    if kind == "poisson":
        values = rng.poisson(np.maximum(_param(spec, "mean", rows), 0.0)).astype(float)
    elif kind == "normal":
        values = rng.normal(_param(spec, "mean", rows), float(spec.get("sd", 1.0)))
    elif kind == "lognormal":
        median = _param(spec, "median", rows)
        values = np.exp(rng.normal(np.log(median), float(spec.get("sigma", 0.6))))
    elif kind == "uniform":
        values = rng.uniform(float(spec["low"]), float(spec["high"]), size=n)
    elif kind == "beta":
        values = rng.beta(float(spec["a"]), float(spec["b"]), size=n)
    elif kind == "choice":
        values = _pick(rng, spec["values"], n).astype(float)
    elif kind == "bernoulli":
        values = (rng.random(n) < _param(spec, "p", rows)).astype(float)
    else:
        raise ValueError(f"unknown dist: {kind}")
    if "p_zero" in spec:
        values = np.where(rng.random(n) < float(spec["p_zero"]), 0.0, values)
    return values


def _sample_field(rng: np.random.Generator, spec: Mapping[str, Any], df: pd.DataFrame) -> pd.Series:
    n = len(df)
    ftype = spec.get("type", "category")
    parents = spec.get("depends_on", [])
    cond = spec.get("conditional")
    source = spec.get("source", {})

    if source.get("kind") == "sequence":
        prefix = source.get("prefix", "")
        return pd.Series([f"{prefix}{i + 1:06d}" for i in range(n)], index=df.index, dtype=object)

    if source.get("kind") == "list":
        key_fields = source.get(
            "from_fields", [source["from_field"]] if "from_field" in source else []
        )
        if key_fields:
            keys = df[key_fields].astype(str).agg("|".join, axis=1)
        else:
            keys = pd.Series("default", index=df.index)
        out = pd.Series(index=df.index, dtype=object)
        for key, idx in keys.groupby(keys).groups.items():
            names = np.array(_lookup(source["lists"], key), dtype=object)
            out.loc[idx] = rng.choice(names, size=len(idx))
        return out

    if ftype == "category":
        if cond and parents:
            parent = df[parents[0]]
            out = pd.Series(index=df.index, dtype=object)
            for key, idx in parent.groupby(parent).groups.items():
                out.loc[idx] = _pick(rng, _lookup(cond, key), len(idx))
            return out
        return pd.Series(_pick(rng, spec["distribution"], n), index=df.index, dtype=object)

    # numeric / boolean
    if cond and parents and "dist" not in cond:
        parent = df[parents[0]]
        values = np.empty(n)
        for key, idx in parent.groupby(parent).groups.items():
            pos = df.index.get_indexer(idx)
            values[pos] = _draw(rng, _lookup(cond, key), df.loc[idx])
    else:
        values = _draw(rng, cond or spec["distribution"], df)
    if "range" in spec:
        low, high = spec["range"]
        values = np.clip(values, low, high)
    if ftype == "integer":
        return pd.Series(np.rint(values).astype(int), index=df.index)
    if ftype == "boolean":
        return pd.Series(values.astype(bool), index=df.index)
    return pd.Series(np.round(values, 4), index=df.index)


def sample(
    dictionary: Dictionary,
    n: int,
    rng: np.random.Generator,
    fixed: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Ancestral sampling of ``n`` rows. ``fixed`` pins fields (stratified sampling)."""
    fixed = dict(fixed or {})
    df = pd.DataFrame(index=pd.RangeIndex(n))
    for name in dictionary.order():
        if name in fixed:
            df[name] = fixed[name]
        else:
            df[name] = _sample_field(rng, dictionary.fields[name], df)
    return df


# ---- rules ------------------------------------------------------------------------------


def rule_violations(dictionary: Dictionary, df: pd.DataFrame, severity: str = "hard") -> pd.Series:
    """Boolean Series: True where a row breaks at least one rule of ``severity``."""
    rules = [r["expr"] for r in dictionary.rules if r.get("severity", "hard") == severity]
    flags = [any(not evaluate(expr, row) for expr in rules) for row in df.to_dict("records")]
    return pd.Series(flags, index=df.index, dtype=bool)


def apply_label(dictionary: Dictionary, df: pd.DataFrame) -> pd.DataFrame:
    if dictionary.label_rule:
        name, expr = dictionary.label_rule["name"], dictionary.label_rule["expr"]
        df[name] = [int(bool(evaluate(expr, r))) for r in df.to_dict("records")]
    return df


@dataclass
class GenerationReport:
    requested: int
    rows: int
    rejected: int
    resample_rounds: int


def _restore_types(dictionary: Dictionary, df: pd.DataFrame, names: list[str]) -> None:
    for name in names:
        ftype = dictionary.fields[name].get("type")
        if ftype == "integer":
            df[name] = df[name].astype(int)
        elif ftype == "float":
            df[name] = df[name].astype(float)
        elif ftype == "boolean":
            df[name] = df[name].astype(bool)


def generate(
    dictionary: Dictionary, n: int, seed: int, fixed: Mapping[str, Any] | None = None
) -> tuple[pd.DataFrame, GenerationReport]:
    """Sample, enforce hard rules (resample violators, then drop), add the label."""
    rng = np.random.default_rng(seed)
    df = sample(dictionary, n, rng, fixed)
    rounds = 0
    bad = rule_violations(dictionary, df)
    while bad.any() and rounds < MAX_RESAMPLE_ROUNDS:
        rounds += 1
        replacement = sample(dictionary, int(bad.sum()), rng, fixed)
        replacement.index = df.index[bad]
        df.loc[bad, :] = replacement
        bad = rule_violations(dictionary, df)
    rejected = int(bad.sum())
    df = df.loc[~bad].reset_index(drop=True)
    _restore_types(dictionary, df, list(dictionary.fields))
    for name, spec in dictionary.fields.items():  # re-number ids after rejections
        if spec.get("source", {}).get("kind") == "sequence":
            df[name] = _sample_field(rng, spec, df)
    df = apply_label(dictionary, df)
    return df, GenerationReport(n, len(df), rejected, rounds)


# ---- counterfactual twins ---------------------------------------------------------------


def twins(
    dictionary: Dictionary,
    df: pd.DataFrame,
    attribute: str,
    flip: Mapping[Any, Any],
    mode: str,
    seed: int,
) -> pd.DataFrame:
    """Flip ``attribute`` via ``flip`` (old value to new value).

    ``ceteris_paribus``: only the attribute changes (tests direct use).
    ``causal``: its descendants in the DAG are re-sampled given the new value (exposes
    proxies), retrying rows that then break a hard rule.
    """
    rng = np.random.default_rng(seed)
    out = df.copy()
    out[attribute] = out[attribute].map(lambda v: flip.get(v, v))
    if mode == "ceteris_paribus":
        return out
    if mode != "causal":
        raise ValueError(f"unknown twin mode: {mode}")
    targets = [t for t in dictionary.descendants(attribute) if t in out.columns]
    todo = pd.Series(True, index=out.index)
    for _ in range(MAX_RESAMPLE_ROUNDS):
        part = out.loc[todo].copy()
        for name in targets:
            part[name] = _sample_field(rng, dictionary.fields[name], part)
        out.loc[todo, targets] = part[targets]
        todo = rule_violations(dictionary, out) & todo
        if not todo.any():
            break
    _restore_types(dictionary, out, targets)
    return out
