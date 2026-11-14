"""Whitelisted expression evaluator for data-dictionary rules (no ``eval``).

Grammar (docs/architecture/synthetic-data.md § 4): comparisons, ``and/or/not``,
``in``, ``is null``, arithmetic, ``min/max/abs/round`` and the declared helpers
``age_min``, ``age_max``, ``age_mid`` (for bands such as ``"25-34"``).
"""

import ast
import math
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any


def _band(value: Any) -> tuple[float, float]:
    low, high = str(value).split("-", 1)
    return float(low), float(high)


def age_min(value: Any) -> float:
    return _band(value)[0]


def age_max(value: Any) -> float:
    return _band(value)[1]


def age_mid(value: Any) -> float:
    low, high = _band(value)
    return (low + high) / 2


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "log": math.log,
    "age_min": age_min,
    "age_max": age_max,
    "age_mid": age_mid,
}

_CONSTANTS = {
    "null": None,
    "None": None,
    "true": True,
    "True": True,
    "false": False,
    "False": False,
}

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}

_CMPOPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}


class ExpressionError(ValueError):
    """The expression uses syntax or names outside the whitelist."""


def _normalise(expr: str) -> str:
    return expr.replace(" is not null", " is not None").replace(" is null", " is None")


@lru_cache(maxsize=512)
def compile_expr(expr: str) -> ast.Expression:
    """Parse once and reject anything outside the whitelist."""
    tree = ast.parse(_normalise(expr), mode="eval")
    allowed = (
        ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
        ast.BinOp, ast.Compare, ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple, ast.Call,
        *_BINOPS, *_CMPOPS,
    )  # fmt: skip
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ExpressionError(f"not allowed in rule expressions: {type(node).__name__}")
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords
        ):
            raise ExpressionError("only whitelisted helper calls are allowed")
    return tree


def _eval(node: ast.AST, env: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ExpressionError(f"unknown field: {node.id}")
    if isinstance(node, ast.List | ast.Tuple):
        return [_eval(e, env) for e in node.elts]
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, env) for v in node.values)
        return any(_eval(v, env) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not value
        return -value if isinstance(node.op, ast.USub) else +value
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval(comparator, env)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)  # noqa: S101  (guaranteed by compile_expr)
        return FUNCTIONS[node.func.id](*[_eval(a, env) for a in node.args])
    raise ExpressionError(f"not allowed: {type(node).__name__}")


def evaluate(expr: str, env: Mapping[str, Any]) -> Any:
    """Evaluate ``expr`` against one row (NaN values count as null)."""
    clean = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in env.items()}
    return _eval(compile_expr(expr), clean)
