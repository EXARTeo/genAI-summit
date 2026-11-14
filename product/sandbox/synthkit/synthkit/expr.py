"""Whitelisted expression evaluator for rules and ``mean_expr`` (no ``eval``).

Grammar (docs/architecture/synthetic-data.md § 4): comparisons, ``and/or/not``,
``in``, ``is null`` / ``is not null``, arithmetic, ``min/max/abs/round/log`` and
the declared helpers ``age_min``, ``age_max``, ``age_mid`` (bands like ``"25-34"``).
The source is parsed with :mod:`ast` and every node is checked against a
whitelist before a small interpreter walks it; nothing is ever compiled or run
as Python. Null-safe: an ordering comparison or arithmetic with a null is false
/ null instead of an exception.
"""

from __future__ import annotations

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
_NULL_OK = (ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.In, ast.NotIn)

_ALLOWED = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.BinOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Call,
    *_BINOPS,
    *_CMPOPS,
)


class ExpressionError(ValueError):
    """The expression uses syntax or names outside the whitelist."""


def _normalise(expr: str) -> str:
    return expr.replace(" is not null", " is not None").replace(" is null", " is None")


@lru_cache(maxsize=1024)
def compile_expr(expr: str) -> ast.Expression:
    """Parse once and reject anything outside the whitelist."""
    try:
        tree = ast.parse(_normalise(expr), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression: {expr!r}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ExpressionError(f"not allowed in expressions: {type(node).__name__}")
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords
        ):
            raise ExpressionError("only whitelisted helper calls are allowed")
    return tree


def names(expr: str) -> set[str]:
    """Field names an expression reads (helpers and constants excluded)."""
    tree = compile_expr(expr)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id not in called and n.id not in _CONSTANTS
    }


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
        if value is None:
            return None
        return -value if isinstance(node.op, ast.USub) else +value
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, env), _eval(node.right, env)
        if left is None or right is None:
            return None
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval(comparator, env)
            if (left is None or right is None) and not isinstance(op, _NULL_OK):
                return False
            try:
                if not _CMPOPS[type(op)](left, right):
                    return False
            except TypeError:
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        args = [_eval(a, env) for a in node.args]
        if any(a is None for a in args):
            return None
        return FUNCTIONS[node.func.id](*args)  # type: ignore[union-attr]
    raise ExpressionError(f"not allowed: {type(node).__name__}")


def _clean(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if type(value).__name__ == "NAType":  # pandas.NA (nullable Int64 columns)
        return None
    if hasattr(value, "item") and not isinstance(value, str | bytes):
        try:
            return value.item()  # numpy scalar → Python
        except (ValueError, AttributeError):
            return value
    return value


def evaluate(expr: str, env: Mapping[str, Any]) -> Any:
    """Evaluate ``expr`` against one row (NaN counts as null)."""
    return _eval(compile_expr(expr), {k: _clean(v) for k, v in env.items()})
