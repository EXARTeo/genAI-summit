"""Ancestral sampling over the dictionary's DAG, with hard-rule repair.

One ``numpy.random.Generator`` drives everything (Faker included, re-seeded per
value from it), so ``(spec, seed)`` decides every row.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
from faker import Faker

from synthkit.expr import evaluate
from synthkit.spec import Dictionary, field_parents, topo_order

#: Custom samplers registered from a spec's custom.py: ``fn(row, rng) -> value``.
CUSTOM_SAMPLERS: dict[str, Callable[[dict, np.random.Generator], Any]] = {}


def sampler(name: str):  # noqa: ANN201 - decorator
    """Register a custom value sampler (the spec's ``custom.py`` escape hatch)."""

    def wrap(fn):
        CUSTOM_SAMPLERS[name] = fn
        return fn

    return wrap


def _probs(mapping: dict) -> tuple[list, np.ndarray]:
    values = list(mapping.keys())
    p = np.array([float(mapping[v]) for v in values], dtype=float)
    total = p.sum()
    if total <= 0:
        raise ValueError("probabilities sum to zero")
    return values, p / total


def _coerce(value: Any) -> Any:
    """YAML keys like ``1`` come back as int already; keep strings as strings."""
    if isinstance(value, np.generic):
        return value.item()
    return value


class Sampler:
    def __init__(self, dictionary: Dictionary) -> None:
        self.d = dictionary
        self.fields = dictionary.fields
        self.order = topo_order(self.fields)
        self.parents = {n: field_parents(f) for n, f in self.fields.items()}
        self.hard_rules = [r for r in dictionary.rules if r.get("severity", "hard") == "hard"]
        self.soft_rules = [r for r in dictionary.rules if r.get("severity") == "soft"]
        self._fakers: dict[str, Faker] = {}

    # -- graph ---------------------------------------------------------------
    def descendants(self, name: str) -> set[str]:
        out: set[str] = set()
        frontier = [name]
        while frontier:
            current = frontier.pop()
            for child, parents in self.parents.items():
                if current in parents and child not in out:
                    out.add(child)
                    frontier.append(child)
        return out

    # -- one value -------------------------------------------------------------
    def _cond_key(self, fdef: dict, row: dict) -> str:
        parents = fdef.get("depends_on") or []
        return "|".join(str(row.get(p)) for p in parents)

    def _pick_conditional(self, fdef: dict, row: dict) -> Any:
        cond = fdef["conditional"]
        if "dist" in cond:
            return cond  # one parametrised distribution (``*_expr`` params)
        key = self._cond_key(fdef, row)
        if key in cond:
            return cond[key]
        # Single-parent shortcut: the first parent's value alone.
        first = str(row.get((fdef.get("depends_on") or [None])[0]))
        return cond.get(first, cond.get("default"))

    def _param(self, spec: dict, key: str, row: dict, default: Any = None) -> Any:
        if f"{key}_expr" in spec:
            return evaluate(spec[f"{key}_expr"], row)
        return spec.get(key, default)

    def _draw_dist(self, spec: dict, fdef: dict, row: dict, rng: np.random.Generator) -> Any:
        bounds = fdef.get("range") or [None, None]
        lo, hi = bounds[0], bounds[1]
        if "p_zero" in spec and rng.random() < float(spec["p_zero"]):
            return 0
        dist = spec.get("dist")
        if dist is None:  # a plain {value: p} table
            values, p = _probs(spec)
            return _coerce(values[rng.choice(len(values), p=p)])
        if dist == "choice":
            values, p = _probs(spec["values"])
            return _coerce(values[rng.choice(len(values), p=p)])
        if dist == "empirical":  # quantiles fitted from a reference sample
            q = np.asarray(spec["quantiles"], dtype=float)
            return float(np.interp(rng.random(), np.linspace(0.0, 1.0, len(q)), q))
        if dist == "poisson":
            return float(rng.poisson(max(0.0, float(self._param(spec, "mean", row, 1.0)))))
        if dist == "lognormal":
            median = float(self._param(spec, "median", row, 1.0))
            sigma = float(self._param(spec, "sigma", row, 0.75))
            return float(rng.lognormal(math.log(max(median, 1e-9)), sigma))
        if dist == "normal":
            mean = float(self._param(spec, "mean", row, 0.0))
            return float(rng.normal(mean, float(self._param(spec, "sd", row, 1.0))))
        if dist == "exponential":
            return float(rng.exponential(float(self._param(spec, "mean", row, 1.0))))
        if dist == "uniform":
            low = float(self._param(spec, "low", row, lo if lo is not None else 0.0))
            high = float(self._param(spec, "high", row, hi if hi is not None else 1.0))
            return float(rng.uniform(low, high))
        if dist == "bernoulli":
            hit = bool(rng.random() < float(self._param(spec, "p", row, 0.5)))
            return hit if fdef["type"] == "boolean" else float(hit)
        if dist == "beta":
            x = float(rng.beta(float(spec.get("a", 2)), float(spec.get("b", 2))))
            if lo is not None and hi is not None:
                return lo + x * (hi - lo)
            return x
        raise ValueError(f"unknown dist {dist!r}")

    def _finish_numeric(self, value: Any, fdef: dict) -> Any:
        if value is None:
            return None
        rng_ = fdef.get("range")
        if rng_:
            value = min(max(value, rng_[0]), rng_[1])
        if fdef["type"] == "integer":
            return int(round(value))
        if fdef["type"] == "float":
            return round(float(value), 6)
        return value

    def _faker(self, locale: str) -> Faker:
        if locale not in self._fakers:
            self._fakers[locale] = Faker(locale)
        return self._fakers[locale]

    def _surface(self, fdef: dict, row: dict, rng: np.random.Generator, index: int) -> Any:
        source = fdef.get("source") or {}
        kind = source.get("kind")
        if kind == "sequence":
            return f"{source.get('prefix', '')}{index:06d}"
        if kind == "constant":
            return source.get("value")
        if kind == "list":
            key = "|".join(str(row.get(f)) for f in source.get("from_fields") or [])
            options = (source.get("lists") or {}).get(key) or source.get("values") or []
            return options[int(rng.integers(len(options)))] if options else None
        if kind == "faker":
            locale = source.get("locale", "en_US")
            if source.get("locale_from"):
                mapped = (source.get("locale_map") or {}).get(str(row.get(source["locale_from"])))
                if isinstance(mapped, list):
                    mapped = mapped[int(rng.integers(len(mapped)))]
                locale = mapped or locale
            fake = self._faker(locale)
            fake.seed_instance(int(rng.integers(2**31 - 1)))
            provider = source.get("provider", "name")
            gender = str(row.get(source.get("gender_from", ""), "")).lower()
            if provider == "name" and gender in ("female", "male"):
                provider = f"name_{gender}"
            return str(getattr(fake, provider)())
        if kind == "custom":
            fn = CUSTOM_SAMPLERS.get(source.get("fn", ""))
            if fn is None:
                raise ValueError(f"custom sampler {source.get('fn')!r} is not registered")
            return fn(dict(row), rng)
        return None

    def sample_value(self, name: str, row: dict, rng: np.random.Generator, index: int = 0) -> Any:
        fdef = self.fields[name]
        ftype = fdef["type"]
        if fdef.get("source"):
            return self._surface(fdef, row, rng, index)
        if ftype in ("string", "id"):
            return f"{name}-{index:06d}"
        if ftype == "boolean" and not (fdef.get("distribution") or fdef.get("conditional")):
            return bool(rng.random() < float(fdef.get("p_true", 0.5)))
        spec: Any
        if fdef.get("conditional"):
            spec = self._pick_conditional(fdef, row)
        else:
            spec = fdef.get("distribution")
        if ftype == "category":
            if spec is None:
                values = fdef.get("values") or []
                return _coerce(values[int(rng.integers(len(values)))])
            return self._draw_dist(spec, fdef, row, rng)
        if spec is None:
            spec = {"dist": "uniform"}
        return self._finish_numeric(self._draw_dist(spec, fdef, row, rng), fdef)

    # -- rows ---------------------------------------------------------------
    def sample_row(
        self, rng: np.random.Generator, given: dict | None = None, index: int = 0
    ) -> dict:
        row: dict = {}
        given = given or {}
        for name in self.order:
            row[name] = given[name] if name in given else self.sample_value(name, row, rng, index)
        return {n: row[n] for n in self.fields}

    def failed_rules(self, row: dict, severity: str = "hard") -> list[str]:
        rules = self.hard_rules if severity == "hard" else self.soft_rules
        failed = []
        for rule in rules:
            try:
                ok = bool(evaluate(rule["expr"], row))
            except (TypeError, ValueError, ZeroDivisionError):
                ok = False
            if not ok:
                failed.append(rule["id"])
        return failed

    def valid_row(
        self, rng: np.random.Generator, given: dict | None = None, index: int = 0, tries: int = 25
    ) -> tuple[dict | None, int]:
        """Sample, then repair by resampling the free fields; ``(None, n)`` = rejected."""
        for attempt in range(1, tries + 1):
            row = self.sample_row(rng, given, index)
            if not self.failed_rules(row):
                return row, attempt - 1
        return None, tries

    def label(self, row: dict) -> Any:
        rule = self.d.label_rule
        if not rule:
            return None
        try:
            return int(bool(evaluate(rule["expr"], row)))
        except (TypeError, ValueError, ZeroDivisionError):
            return None
