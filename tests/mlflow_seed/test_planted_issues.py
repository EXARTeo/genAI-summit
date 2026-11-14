"""The planted issues show up in the trained models (small n, no MLflow server)."""

import pandas as pd
import pytest
from conftest import built

from seedmodels.benefits import BenefitsTriageModel
from seedmodels.cv import PARSER_OUTPUT, parse_cvs


def metrics_of(system_id: str, name: str) -> dict:
    return next(m for m in built(system_id).models if m.name == name).metrics


def test_sys001_proxy_bias_by_nationality():
    m = metrics_of("SYS-001", "sys-001-cv-ranker")
    assert m["selection_rate_ratio.nationality"] < 0.85
    assert m["cf_flip_rate.nationality.cp"] == 0.0  # no direct use
    assert m["cf_flip_rate.nationality.causal"] > 0.05  # via postcode_region
    assert m["cf_flip_rate.postcode_region.proxy_only"] > 0.05


def test_sys001_career_gap_equal_opportunity_gap():
    m = metrics_of("SYS-001", "sys-001-cv-ranker")
    assert m["equal_opportunity_gap.sex"] > 0.03
    assert m["tpr.sex.female"] < m["tpr.sex.male"]
    assert m["cf_flip_rate.sex.cp"] == 0.0
    assert m["cf_flip_rate.sex.causal"] > 0.02


def test_sys001_parser_output_is_ranker_input():
    parser, ranker = built("SYS-001").models
    out = parser.python_model.predict(None, parser.input_example)
    assert list(out.columns) == PARSER_OUTPUT == list(ranker.input_example.columns)
    pred = ranker.python_model.predict(None, out)
    assert list(pred.columns) == ["shortlist", "proba"]
    assert pred["proba"].between(0, 1).all()
    assert m_parse_ok(parser.metrics)


def m_parse_ok(m: dict) -> bool:
    return all(v == 1.0 for k, v in m.items() if k.startswith("parse_exact_match"))


def test_sys001_parser_rules():
    raw = pd.DataFrame(
        [
            {
                "candidate_id": "C1", "full_name": "Test Person", "sex": "Female", "age": 30,
                "nationality_code": "de", "postcode": "121 34", "highest_degree": "MSc Physics",
                "years_experience": 4, "career_break_months": None,
                "skills": "Python, SQL, excel", "languages": "Greek, English",
            }
        ]
    )  # fmt: skip
    row = parse_cvs(raw).iloc[0]
    assert row["age_band"] == "25-34"
    assert row["nationality"] == "EU_other"
    assert row["postcode_region"] == "athens_west"
    assert row["education_level"] == "master"
    assert row["career_gap_months"] == 0
    assert row["skills_match"] == 0.25
    assert row["languages"] == 2


def test_sys002_nearly_clean_but_young_accuracy_gap():
    m = metrics_of("SYS-002", "sys-002-credit-scorer")
    assert m["accuracy"] > 0.85
    assert m["selection_rate_ratio.sex"] > 0.9
    assert m["equal_opportunity_gap.sex"] < 0.05
    assert m["accuracy_gap.age_band.18-25_vs_rest"] > 0.04


def test_sys003_robustness_planted():
    spec = built("SYS-003").models[0]
    assert spec.metrics["robustness.crash_rate"] > 0
    assert spec.metrics["robustness.nonsense_rate"] > 0
    model: BenefitsTriageModel = spec.python_model
    base = spec.input_example.iloc[[0]].copy()
    with pytest.raises(ZeroDivisionError):
        model.predict(None, base.assign(household_size=0))
    with pytest.raises(ValueError):
        model.predict(None, base.assign(monthly_income=float("nan")))
    out = model.predict(None, base.assign(monthly_income=-5000.0, household_size=2))
    assert out.loc[0, "eligible"] == 1 and out.loc[0, "estimated_benefit_eur"] > 3000


def test_sys003_valid_input_is_fine():
    spec = built("SYS-003").models[0]
    out = spec.python_model.predict(None, spec.input_example)
    assert set(out["triage"]) <= {"fast_track", "standard", "not_eligible"}
    assert out["estimated_benefit_eur"].between(0, 3000).all()
    assert spec.metrics["accuracy"] > 0.8
