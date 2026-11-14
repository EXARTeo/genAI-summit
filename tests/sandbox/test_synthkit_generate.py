"""synthkit generate: determinism, rules, twins, edge cases, custom samplers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml
from synthkit.generate import generate
from synthkit.sampler import Sampler
from synthkit.spec import SpecError, load_spec

SPEC = {
    "version": 1,
    "name": "SYS-001.cv-ranker.twins",
    "dictionary": "data-dictionary.yaml",
    "plugin": "plugin.yaml",
    "n": 90,
    "strata": {"by": ["nationality"]},
    "coverage": {"cells": ["sex", "nationality"], "min_per_cell": 12},
    "transforms": [
        {"kind": "twins", "attribute": "nationality", "max_base": 30},
        {
            "kind": "twins",
            "attribute": "sex",
            "modes": ["attribute_only", "causal"],
            "max_base": 30,
        },
        {
            "kind": "edge_cases",
            "fields": ["years_experience", "career_gap_months", "education_level"],
        },
        {"kind": "perturbation", "fields": ["years_experience"], "delta": 1, "max_base": 20},
    ],
}


def write_spec(case_dir: Path, **changes) -> Path:
    path = case_dir / "generation-spec.yaml"
    path.write_text(yaml.safe_dump({**SPEC, **changes}), encoding="utf-8")
    return path


def test_same_spec_and_seed_same_dataset(case_dir):
    spec = load_spec(write_spec(case_dir))
    a = generate(spec, 42, case_dir / "a")
    b = generate(spec, 42, case_dir / "b")
    c = generate(spec, 43, case_dir / "c")
    assert a["content_sha256"] == b["content_sha256"]
    assert a["dataset_id"] == b["dataset_id"]
    csv_a = (case_dir / "a" / "dataset.csv").read_bytes()
    assert csv_a == (case_dir / "b" / "dataset.csv").read_bytes()
    assert c["content_sha256"] != a["content_sha256"]
    assert c["dataset_id"] != a["dataset_id"]


def test_hard_rules_hold_and_card_is_complete(case_dir):
    spec = load_spec(write_spec(case_dir))
    card = generate(spec, 1, case_dir / "out")
    hard = {r["id"] for r in spec.dictionary.rules if r.get("severity", "hard") == "hard"}
    assert all(card["rules"]["pass_rate_base"][rid] == 1.0 for rid in hard)
    df = pd.read_parquet(case_dir / "out" / "dataset.parquet")
    sampler = Sampler(spec.dictionary)
    fields = list(spec.dictionary.fields)
    base = df[df._test == "base"]
    assert all(not sampler.failed_rules(r) for r in base[fields].to_dict(orient="records"))
    assert base.nationality.value_counts().min() >= 30  # balanced strata
    assert all(v >= 12 for v in card["coverage"]["counts"].values())
    for key in (
        "dataset_id",
        "generation",
        "provenance",
        "composition",
        "distributions",
        "group_balance",
        "rules",
        "sample_rows",
        "twin_pairs",
        "population",
    ):
        assert key in card
    assert card["provenance"]["fields"]["postcode_region"] == "llm_assumption"
    assert any(a.get("field") == "postcode_region" for a in card["generation"]["assumptions"])
    assert card["ai_generated"] is False
    on_disk = yaml.safe_load((case_dir / "out" / "DataCard.yaml").read_text(encoding="utf-8"))
    assert on_disk["dataset_id"] == card["dataset_id"]


def test_twin_modes(case_dir):
    spec = load_spec(write_spec(case_dir))
    generate(spec, 5, case_dir / "out")
    df = pd.read_parquet(case_dir / "out" / "dataset.parquet").set_index("_row_id")
    sampler = Sampler(spec.dictionary)
    fields = list(spec.dictionary.fields)
    twins = df[(df._test == "twin") & df._flip.str.startswith("nationality:")]
    proxy = df[(df._test == "twin") & (df._twin_mode == "proxy_only")]
    assert set(twins._twin_mode) == {"attribute_only", "causal"}
    assert len(proxy) > 0
    desc = sampler.descendants("nationality")
    for rid, t in pd.concat([twins, proxy]).iterrows():
        b = df.loc[t._twin_of]
        changed = {f for f in fields if str(b[f]) != str(t[f])}
        if t._twin_mode == "attribute_only":
            assert changed == {"nationality"}
        elif t._twin_mode == "causal":
            assert "nationality" in changed
            assert changed <= desc | {"nationality"}
            assert not sampler.failed_rules({f: t[f] for f in fields}), rid
        else:
            assert b.nationality == t.nationality
            assert changed
            assert all(spec.dictionary.fields[f]["role"] == "proxy" for f in changed)


def test_edge_cases_and_perturbations(case_dir):
    generate(load_spec(write_spec(case_dir)), 3, case_dir / "out")
    df = pd.read_csv(case_dir / "out" / "dataset.csv")
    edges = set(df[df._test == "edge"]._edge)
    assert {
        "years_experience:min",
        "years_experience:above_max",
        "career_gap_months:null",
        "education_level:unknown_category",
    } <= edges
    assert not df[df._edge == "years_experience:above_max"]._expect_valid.any()
    pert = df[df._test == "perturbation"].set_index("_twin_of")
    base = df.set_index("_row_id")
    assert len(pert)
    for twin_of, row in pert.iterrows():
        assert row.years_experience == base.loc[twin_of].years_experience + 1


def test_unknown_field_is_refused(case_dir):
    with pytest.raises(SpecError):
        load_spec(write_spec(case_dir, fields={"shoe_size": {"type": "integer"}}))
    with pytest.raises(SpecError):
        load_spec(write_spec(case_dir, rules=[{"id": "X1", "expr": "open('x')"}]))
    with pytest.raises(SpecError):
        load_spec(write_spec(case_dir, transforms=[{"kind": "twins", "attribute": "nope"}]))


def test_custom_sampler_is_flagged(case_dir):
    (case_dir / "custom.py").write_text(
        "from synthkit.sampler import sampler\n\n\n"
        "@sampler('fixed_name')\n"
        "def fixed_name(row, rng):\n"
        "    return 'Test Person ' + str(int(rng.integers(100)))\n",
        encoding="utf-8",
    )
    override = {"source": {"kind": "custom", "fn": "fixed_name"}, "provenance": "llm_assumption"}
    path = write_spec(case_dir, custom="custom.py", fields={"full_name": override})
    card = generate(load_spec(path), 2, case_dir / "out")
    assert card["ai_generated"] is True
    assert card["generation"]["custom"]["ai_generated"] is True
    df = pd.read_csv(case_dir / "out" / "dataset.csv")
    assert df.full_name.str.startswith("Test Person").all()
