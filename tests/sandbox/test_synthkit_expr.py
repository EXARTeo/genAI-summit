"""The rule expression language: whitelist only, null-safe."""

import pytest
from synthkit.expr import ExpressionError, evaluate, names


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('x')",
        "x.__class__",
        "(lambda: 1)()",
        "[a for a in b]",
        "open('f')",
        "x[0]",
    ],
)
def test_rejects_anything_outside_the_whitelist(expr):
    with pytest.raises(ExpressionError):
        evaluate(expr, {"x": 1, "b": [1]})


def test_rules_from_the_dictionary():
    row = {"years_experience": 5, "age_band": "25-34", "career_gap_months": None}
    assert evaluate("years_experience <= age_max(age_band) - 16", row) is True
    assert evaluate("career_gap_months is null or career_gap_months <= 10", row) is True
    assert evaluate("career_gap_months > 3", row) is False  # null-safe, no TypeError
    assert evaluate("age_band in ['18-24', '25-34']", row) is True
    assert names("years_experience <= age_max(age_band) - 16") == {"years_experience", "age_band"}
