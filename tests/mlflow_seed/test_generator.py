"""The DAG sampler and rule evaluator: deterministic, schema-correct, rules hold."""

import pandas as pd
import pytest

from seedlib.expr import ExpressionError, evaluate
from seedlib.sampler import Dictionary, generate, rule_violations, twins

DICTIONARIES = {
    "SYS-001": "plugins/cv-ranker/data/data-dictionary.yaml",
    "SYS-002": "plugins/credit-scorer/data/data-dictionary.yaml",
    "SYS-003": "plugins/benefits-triage/data/data-dictionary.yaml",
}


def load(cases_dir, system_id) -> Dictionary:
    return Dictionary.load(cases_dir / system_id / DICTIONARIES[system_id])


@pytest.mark.parametrize(
    ("expr", "row", "expected"),
    [
        ("years_experience <= age_max(age_band) - 16", {"years_experience": 5, "age_band": "18-24"},
         True),
        ("years_experience <= age_max(age_band) - 16", {"years_experience": 9, "age_band": "18-24"},
         False),
        ("gap is null or gap <= 3", {"gap": None}, True),
        ("gap is null or gap <= 3", {"gap": float("nan")}, True),
        ("edu in ['bachelor', 'phd'] and not x", {"edu": "phd", "x": False}, True),
    ],
)  # fmt: skip
def test_expr_evaluates(expr, row, expected):
    assert evaluate(expr, row) is expected


@pytest.mark.parametrize(
    "expr",
    ["__import__('os').system('x')", "a.__class__", "[x for x in y]", "open('f')", "lambda: 1"],
)
def test_expr_rejects_code(expr):
    with pytest.raises((ExpressionError, SyntaxError)):
        evaluate(expr, {"a": 1, "y": [1], "x": 1})


@pytest.mark.parametrize("system_id", list(DICTIONARIES))
def test_generation_is_deterministic(cases_dir, system_id):
    d = load(cases_dir, system_id)
    a, _ = generate(d, 400, seed=3)
    b, _ = generate(d, 400, seed=3)
    c, _ = generate(d, 400, seed=4)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


@pytest.mark.parametrize("system_id", list(DICTIONARIES))
def test_schema_and_hard_rules_hold(cases_dir, system_id):
    d = load(cases_dir, system_id)
    df, report = generate(d, 1500, seed=1)
    assert report.rows == len(df) > 1400
    assert not rule_violations(d, df).any()
    for name, spec in d.fields.items():
        col = df[name]
        assert col.notna().all(), name
        if "values" in spec:
            assert set(col.unique()) <= set(spec["values"]), name
        if "range" in spec:
            low, high = spec["range"]
            assert col.min() >= low and col.max() <= high, name
    ids = [n for n, s in d.fields.items() if s.get("role") == "id"]
    assert all(df[i].is_unique for i in ids)


def test_marginals_match_declared_population(cases_dir):
    d = load(cases_dir, "SYS-001")
    df, _ = generate(d, 5000, seed=2)
    assert abs((df["sex"] == "female").mean() - 0.38) < 0.03
    assert abs((df["nationality"] == "non_EU").mean() - 0.12) < 0.02


def test_proxy_dependence_is_planted(cases_dir):
    """postcode_region depends on nationality; career gaps on sex (the causal graph)."""
    d = load(cases_dir, "SYS-001")
    df, _ = generate(d, 5000, seed=2)
    west = df["postcode_region"].isin(["athens_west", "piraeus"])
    assert west[df["nationality"] == "non_EU"].mean() > west[df["nationality"] == "GR"].mean() + 0.2
    gap = df.groupby("sex")["career_gap_months"].mean()
    assert gap["female"] > gap["male"] * 1.5


def test_twins_modes(cases_dir):
    d = load(cases_dir, "SYS-001")
    df, _ = generate(d, 800, seed=5)
    flip = {"GR": "non_EU", "EU_other": "non_EU", "non_EU": "GR"}
    cp = twins(d, df, "nationality", flip, "ceteris_paribus", seed=1)
    causal = twins(d, df, "nationality", flip, "causal", seed=1)
    others = [c for c in df.columns if c not in {"nationality", *d.descendants("nationality")}]
    assert (cp["nationality"] != df["nationality"]).all()
    pd.testing.assert_frame_equal(cp.drop(columns="nationality"), df.drop(columns="nationality"))
    pd.testing.assert_frame_equal(causal[others], df[others])
    assert (causal["postcode_region"] != df["postcode_region"]).mean() > 0.3
    assert not rule_violations(d, causal).any()
