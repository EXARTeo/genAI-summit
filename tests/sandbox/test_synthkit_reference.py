"""synthkit ``generation.mode: reference_sample``: fit the dictionary DAG to a public
sample (mapped by mapping.yaml), keep hard rules, record provenance in the Data Card."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from synthkit.analyze import run_analysis
from synthkit.generate import generate
from synthkit.reference import map_reference
from synthkit.spec import SpecError, load_spec

DICTIONARY = {
    "version": 1,
    "population": {"stats": {"sex.female": 0.46}},
    "fields": {
        "applicant_id": {"type": "id", "role": "id", "source": {"kind": "sequence"}},
        "sex": {
            "type": "category",
            "role": "protected",
            "values": ["female", "male"],
            "distribution": {"female": 0.5, "male": 0.5},
        },
        "age_band": {
            "type": "category",
            "role": "protected",
            "values": ["18-25", "26-35", "36-50", "51-65", "66-75"],
            "distribution": {"18-25": 0.2, "26-35": 0.2, "36-50": 0.2, "51-65": 0.2, "66-75": 0.2},
        },
        "loan_amount": {
            "type": "float",
            "range": [500, 100000],
            "depends_on": ["sex"],
            "conditional": {
                "female": {"dist": "lognormal", "median": 8000, "sigma": 0.7},
                "male": {"dist": "lognormal", "median": 8000, "sigma": 0.7},
            },
        },
        "employment_years": {
            "type": "integer",
            "range": [0, 50],
            "depends_on": ["age_band"],
            "conditional": {
                "dist": "poisson",
                "mean_expr": "max(0.5, (age_mid(age_band) - 21) * 0.6)",
            },
        },
        "debt_to_income": {
            "type": "float",
            "range": [0, 1.5],
            "distribution": {"dist": "beta", "a": 2, "b": 6},
        },
    },
    "rules": [
        {"id": "R1", "severity": "hard", "expr": "employment_years <= age_max(age_band) - 16"},
        {"id": "R2", "severity": "hard", "expr": "loan_amount <= 15000 or sex == 'male'"},
    ],
}


def _reference(n: int = 600, seed: int = 3) -> pd.DataFrame:
    """A 'public' sample: coded sex, numeric age, amounts that depend on sex."""
    rng = np.random.default_rng(seed)
    status = rng.choice(["male single", "female div/dep/mar", "male mar/wid"], n, p=[0.5, 0.3, 0.2])
    female = np.char.startswith(status.astype(str), "female")
    amount = np.where(
        female, rng.lognormal(np.log(2000), 0.3, n), rng.lognormal(np.log(6000), 0.3, n)
    )
    return pd.DataFrame(
        {
            "personal_status": status,
            "age": rng.integers(19, 75, n),
            "credit_amount": amount.round(0).astype(int),
            "installment_commitment": rng.integers(1, 5, n),  # a 1-4 class, not a ratio
            "email": [f"p{i}@example.com" for i in range(n)],
            "class": rng.choice(["good", "bad"], n, p=[0.7, 0.3]),
        }
    )


MAPPING = {
    "version": 1,
    "source": {
        "id": "openml:31",
        "name": "credit-g",
        "url": "https://www.openml.org/d/31",
        "licence": "CC-BY-4.0",
        "licence_status": "allowed",
    },
    "fields": {
        "sex": {
            "column": "personal_status",
            "transform": "value_map",
            "values": {
                "male single": "male",
                "female div/dep/mar": "female",
                "male mar/wid": "male",
            },
        },
        "age_band": {"column": "age", "transform": "bin"},
        "loan_amount": {"column": "credit_amount"},
        "debt_to_income": {"column": "installment_commitment"},
    },
    "label": {"column": "class", "name": "repaid", "values": {"good": 1, "bad": 0}},
    "dropped_columns": [{"column": "email", "reason": "direct identifier (PII)"}],
}


@pytest.fixture
def case(tmp_path: Path) -> Path:
    (tmp_path / "data-dictionary.yaml").write_text(yaml.safe_dump(DICTIONARY), encoding="utf-8")
    ref_dir = tmp_path / "datasets" / "public" / "openml-31-credit-g"
    ref_dir.mkdir(parents=True)
    _reference().drop(columns=["email"]).to_csv(ref_dir / "data.csv", index=False)
    (ref_dir / "mapping.yaml").write_text(yaml.safe_dump(MAPPING), encoding="utf-8")
    spec = {
        "version": 1,
        "name": "SYS-002.credit.reference",
        "dictionary": "data-dictionary.yaml",
        "generation": {
            "mode": "reference_sample",
            "reference": "datasets/public/openml-31-credit-g/data.csv",
            "mapping": "datasets/public/openml-31-credit-g/mapping.yaml",
        },
        "n": 500,
        "transforms": [{"kind": "twins", "attribute": "sex", "max_base": 40}],
    }
    (tmp_path / "generation-spec.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return tmp_path


def test_mapping_recodes_bins_and_refuses_semantic_mismatches(case: Path):
    ref = _reference()
    mapped, info = map_reference(ref, MAPPING, DICTIONARY["fields"])
    assert set(mapped["sex"].dropna()) == {"female", "male"}
    assert set(mapped["age_band"].dropna()) <= set(DICTIONARY["fields"]["age_band"]["values"])
    assert info["debt_to_income"]["status"] == "skipped"
    assert "outside the dictionary range" in info["debt_to_income"]["reason"]
    assert {f for f, i in info.items() if i["status"] == "fitted"} == {
        "sex",
        "age_band",
        "loan_amount",
    }


def test_reference_mode_fits_marginals_and_conditionals(case: Path):
    spec = load_spec(case / "generation-spec.yaml")
    fields = spec.dictionary.fields
    assert spec.mode == "reference_sample"
    assert fields["sex"]["provenance"] == "reference:openml:31"
    assert fields["sex"]["distribution"]["female"] == pytest.approx(0.3, abs=0.05)
    # loan_amount | sex is fitted per sex cell with empirical quantiles.
    cond = fields["loan_amount"]["conditional"]
    assert cond["female"]["dist"] == "empirical" and "default" in cond
    assert np.median(cond["female"]["quantiles"]) < np.median(cond["male"]["quantiles"])
    # Unmapped / refused fields stay zero-shot from the dictionary.
    assert fields["employment_years"]["conditional"]["dist"] == "poisson"
    assert fields["debt_to_income"]["distribution"]["dist"] == "beta"
    assert spec.reference["zero_shot"] == ["debt_to_income", "employment_years"]


def test_reference_mode_is_deterministic_and_keeps_hard_rules(case: Path, tmp_path: Path):
    spec = load_spec(case / "generation-spec.yaml")
    a = generate(spec, 11, tmp_path / "a", fmt="csv")
    b = generate(load_spec(case / "generation-spec.yaml"), 11, tmp_path / "b", fmt="csv")
    assert a["content_sha256"] == b["content_sha256"]
    assert a["dataset_id"] == b["dataset_id"]
    assert a["rules"]["pass_rate_base"] == {"R1": 1.0, "R2": 1.0}
    frame = pd.read_csv(tmp_path / "a" / "dataset.csv")
    base = frame[frame["_test"] == "base"]
    female = base[base["sex"] == "female"]["loan_amount"]
    male = base[base["sex"] == "male"]["loan_amount"]
    assert female.median() < male.median()  # the reference's dependency survives
    assert (base["sex"] == "female").mean() == pytest.approx(0.3, abs=0.07)


def test_data_card_records_reference_provenance(case: Path, tmp_path: Path):
    card = generate(load_spec(case / "generation-spec.yaml"), 5, tmp_path / "out", fmt="csv")
    assert card["generation"]["method"] == "reference_sample"
    ref = card["reference"]
    assert ref["source"]["id"] == "openml:31"
    assert ref["licence"] == "CC-BY-4.0"
    assert ref["fitted_fields"] == ["age_band", "loan_amount", "sex"]
    assert ref["label_rate"] == pytest.approx(0.7, abs=0.06)
    assert ref["dropped_columns"][0]["column"] == "email"
    assert ref["realism_vs_reference"]["TVComplement.sex"] > 0.9
    assert any(i.get("kind") == "reference_sample" for i in card["inputs_used"])
    assert "public:CC-BY-4.0" in card["reference_data"]
    assert "public reference" in card["limitations"][0]


def test_realism_gate_compares_against_the_reference(case: Path, tmp_path: Path):
    spec = load_spec(case / "generation-spec.yaml")
    generate(spec, 5, tmp_path / "out", fmt="csv")
    frame = pd.read_csv(tmp_path / "out" / "dataset.csv")
    realism = run_analysis(frame, spec, seed=5)["gates"]["realism"]
    assert set(realism["vs_reference_sample"]) == {
        "TVComplement.sex",
        "TVComplement.age_band",
        "KSComplement.loan_amount",
    }
    # The stated population (46% female) differs from the reference (30%): flagged.
    assert realism["population_stats"]["sex.female"]["within_tolerance"] is False
    assert realism["status"] == "warn"


def test_zero_shot_spec_is_unchanged(case: Path, tmp_path: Path):
    path = case / "generation-spec.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("generation")
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    spec = load_spec(path)
    assert spec.reference is None and spec.mode == "zero_shot"
    card = generate(spec, 5, tmp_path / "z", fmt="csv")
    assert card["generation"]["method"] == "dag_sampler"
    assert card["reference"] is None


def test_bad_reference_inputs_are_spec_errors(case: Path):
    path = case / "generation-spec.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["generation"]["reference"] = "missing.csv"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(SpecError, match="reference sample not found"):
        load_spec(path)
    raw["generation"] = {"mode": "magic"}
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(SpecError, match="generation.mode"):
        load_spec(path)
