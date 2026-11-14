"""synthkit analyze (five gates, twin validity) and scenarios-check."""

from __future__ import annotations

import pandas as pd
import yaml
from synthkit.analyze import run_analysis, to_markdown
from synthkit.cli import main
from synthkit.generate import generate
from synthkit.scenarios import check_scenarios
from synthkit.spec import Dictionary, load_spec
from test_synthkit_generate import write_spec


def _dataset(case_dir):
    spec = load_spec(write_spec(case_dir))
    generate(spec, 4, case_dir / "out")
    return spec, pd.read_parquet(case_dir / "out" / "dataset.parquet")


def test_gates_pass_on_a_generated_dataset(case_dir):
    spec, df = _dataset(case_dir)
    a = run_analysis(df, spec)
    g = a["gates"]
    assert g["schema"]["status"] == "pass", g["schema"]
    assert g["business_rules"]["status"] == "pass"
    assert g["coverage"]["status"] == "pass"
    assert g["privacy"]["status"] == "pass"
    assert g["realism"]["status"] in ("pass", "warn")  # balanced strata: warn by design
    assert a["twin_validity"]["attribute_only"]["valid_share"] == 1.0
    assert a["twin_validity"]["causal"]["valid_share"] == 1.0
    assert "Schema" in to_markdown(a, "x")


def test_gates_fail_on_broken_rows(case_dir):
    spec, df = _dataset(case_dir)
    first = df.index[df._test == "base"][0]
    df.loc[first, "age_band"] = "18-24"
    df.loc[first, "years_experience"] = 30  # R1: nobody works before 16
    df.loc[first, "full_name"] = "someone@example.com"
    a = run_analysis(df, spec)
    assert a["gates"]["business_rules"]["status"] == "fail"
    assert a["gates"]["privacy"]["status"] == "fail"
    assert a["overall"] == "fail"


def test_cli_generate_then_analyze(case_dir):
    spec = str(write_spec(case_dir))
    out = str(case_dir / "o")
    assert main(["generate", "--spec", spec, "--seed", "9", "--out-dir", out]) == 0
    dataset = str(case_dir / "o" / "dataset.csv")
    assert main(["analyze", "--dataset", dataset, "--spec", spec, "--out-dir", out]) == 0
    assert (case_dir / "o" / "dataset-analysis.json").exists()
    assert (case_dir / "o" / "dataset-analysis.md").exists()


def test_scenarios_check_flags_gaps(case_dir):
    plugin = yaml.safe_load((case_dir / "plugin.yaml").read_text(encoding="utf-8"))
    dictionary = Dictionary.load(case_dir / "data-dictionary.yaml")
    doc = {
        "scenarios": [
            {
                "id": "SC-01",
                "requirement": "REQ.AIA.10.2.f",
                "target": plugin["id"],
                "template": "counterfactual_twins",
                "expected_behaviour": "no gap",
                "data_needs": {"attribute": "nationality", "twin_modes": ["attribute_only"]},
                "protected": ["nationality"],
            },
            {
                "id": "SC-02",
                "template": "group_fairness",
                "target": "OTHER",
                "data_needs": {"fields": ["shoe_size"]},
            },
        ]
    }
    profile = {"sensitivity": {"postcode_region": {"moves_output": True}}}
    r = check_scenarios(doc, dictionary, plugin, profile)
    assert r["status"] == "gaps"
    issues = r["scenarios"][1]["issues"]
    assert any("missing requirement" in i for i in issues)
    assert any("unknown fields" in i for i in issues)
    assert any("not this plugin" in i for i in issues)
    whats = [m["what"] for m in r["missing"]]
    assert "fairness test for sex" in whats
    assert any("causal / proxy-only twins for nationality" in w for w in whats)
    proxy = next(m for m in r["missing"] if m["what"].startswith("proxy test for postcode_region"))
    assert proxy["priority"] == "high"
    assert any("years_experience" in w for w in whats)
