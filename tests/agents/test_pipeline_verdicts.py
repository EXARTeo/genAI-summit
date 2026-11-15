"""Plan 01 code paths: rule verdicts, severity, sealing, coverage, spec fixes, safe tools."""

from __future__ import annotations

from datetime import date

import yaml
from pipeline.clients import PipelineHTTPError
from pipeline.steps import StepScope, _regulation_tools
from pipeline.verdicts import (
    citation_problems,
    combine,
    coverage_problems,
    dossier_evidence,
    finding_hash,
    rule_verdict,
    seal,
    severity,
)
from pipeline.verify import coverage_feedback, dataset_problems, normalise_spec


def _row(status, value, ci, op="<=", thr=0.02):
    return {
        "id": "T-01/m",
        "metric": "m",
        "value": value,
        "ci95": ci,
        "status": status,
        "threshold": {"op": op, "value": thr},
    }


def test_rule_verdict_follows_the_org_threshold_and_the_ci():
    assert rule_verdict([])[0] == "inconclusive"
    assert rule_verdict([_row("error", None, None)])[0] == "inconclusive"
    assert rule_verdict([{**_row("inconclusive", 0.1, None), "threshold": None}])[0] == (
        "inconclusive"
    )
    assert rule_verdict([_row("pass", 0.01, [0.0, 0.015])])[0] == "pass"
    assert rule_verdict([_row("fail", 0.15, [0.11, 0.19])])[0] == "gap"
    # Point estimate fails but the CI reaches the threshold: partial, not gap.
    assert rule_verdict([_row("fail", 0.03, [0.01, 0.05])])[0] == "partial"
    assert rule_verdict([_row("inconclusive", 0.015, [0.01, 0.03])])[0] == "partial"


def test_judges_disagreeing_make_the_verdict_inconclusive_for_a_human():
    assert combine("gap", "gap", "gap") == ("gap", False)
    assert combine("gap", "gap", "pass") == ("inconclusive", True)
    assert combine("gap", None, "gap") == ("gap", False)
    assert combine("gap", "partial", None) == ("partial", True)


def test_severity_by_in_force_date():
    today = date(2026, 11, 15)
    now = {"article": "AIA.10.2.f", "in_force_date": "2025-01-01", "in_force_now": True}
    later = {"article": "AIA.10.2.f", "in_force_date": "2027-12-02", "in_force_now": False}
    soon = {"article": "AIA.12", "in_force_date": "2027-02-01", "in_force_now": False}
    assert severity("gap", now, today) == "critical"
    assert severity("gap", soon, today) == "high"
    assert severity("gap", later, today) == "medium"
    assert severity("partial", later, today) == "low"
    assert severity("inconclusive", now, today) == "medium"
    assert severity("pass", now, today) is None
    assert severity("not_assessable_by_testing", later, today, doc_gap=True) == "low"


def test_seal_chains_hashes_and_numbers_gaps():
    proposed = [
        {"obligation_id": "A", "verdict": "gap"},
        {"obligation_id": "B", "verdict": "pass"},
        {"obligation_id": "C", "verdict": "not_assessable_by_testing", "documentation_gap": True},
    ]
    sealed = seal(proposed, "SYS-001")
    assert [f["gap_id"] for f in sealed] == ["G-SYS-001-01", None, "G-SYS-001-02"]
    assert sealed[1]["prev_hash"] == sealed[0]["hash"]
    assert sealed[2]["hash"] == finding_hash(sealed[2], sealed[1]["hash"])
    assert len({f["hash"] for f in sealed}) == 3


def test_coverage_invariant():
    scope = [{"obligation_id": "A"}, {"obligation_id": "B"}]
    assert coverage_problems(scope, [{"obligation_id": "A"}, {"obligation_id": "B"}]) == []
    assert coverage_problems(scope, [{"obligation_id": "A"}]) == ["B: no verdict"]
    assert coverage_problems(scope, [{"obligation_id": x} for x in "ABB"]) == ["B: 2 verdicts"]
    assert coverage_problems(scope, [{"obligation_id": x} for x in "ABZ"]) == ["Z: not in scope"]


def test_citations_must_exist_and_belong_to_the_obligation():
    entry = {"article": "AIA.10.2", "related": ["AIA.4a"]}
    known = {"AIA.10.2.f": True, "AIA.4a.1": True, "AIA.15.1": True, "AIA.99": False}
    cites = [{"provision_id": p} for p in ("AIA.10.2.f", "AIA.4a.1", "AIA.15.1", "AIA.99")]
    problems = citation_problems(cites, entry, known)
    assert [p.split(":")[0] for p in problems] == ["AIA.15.1", "AIA.99"]


def test_documentary_evidence_by_file_name():
    entry = {"evidence_types": ["dpia", "risk_management_plan", "classification_record"]}
    found = dossier_evidence(
        entry, ["docs/dpia-summary.md", "docs/risk-management-summary.md", "system-card.yaml"]
    )
    assert found["missing"] == ["classification_record"]
    assert len(found["present"]) == 2


DICTIONARY = yaml.safe_dump({"fields": {"sex": {"type": "category"}, "years": {"type": "integer"}}})


def test_spec_fixed_keys_and_categorical_cells_are_set_by_code():
    draft = yaml.safe_dump(
        {
            "version": 1,
            "name": "x",
            "dictionary": "../input/plugins/cv-ranker/data/data-dictionary.yaml",
            "plugin": "/abs/plugin.yaml",
            "n": 100,
            "coverage": {"cells": ["sex", "years"], "min_per_cell": 20},
        }
    )
    fixed, notes = normalise_spec(draft, DICTIONARY)
    spec = yaml.safe_load(fixed)
    assert spec["dictionary"] == "data/data-dictionary.yaml"
    assert spec["plugin"] == "plugin.yaml" and spec["model_profile"] == "model-profile.json"
    assert spec["coverage"]["cells"] == ["sex"]
    assert any("years" in n for n in notes)
    no_profile, _ = normalise_spec(draft, DICTIONARY, has_profile=False)
    assert "model_profile" not in yaml.safe_load(no_profile)


def test_coverage_feedback_names_the_cells_and_counts():
    gate = {
        "status": "fail",
        "cells": ["sex", "nationality"],
        "min_per_cell": 20,
        "counts": {"female|GR": 40, "female|non_EU": 3, "male|non_EU": 12},
        "below_min": {"female|non_EU": 3, "male|non_EU": 12},
    }
    (problem,) = dataset_problems({"gates": {"coverage": gate}})
    assert problem == coverage_feedback(gate)
    assert "2 of 3 cells" in problem and "female|non_EU (3)" in problem
    assert "min_per_cell=20" in problem


class _RegMem:
    def __init__(self, body=None, exc=None):
        self.body, self.exc = body, exc

    async def provision(self, provision_id, kb_version=None):
        if self.exc:
            raise self.exc
        return self.body

    async def search_provisions(self, **kw):
        raise RuntimeError("boom")


def _tool(regmem, name):
    scope = StepScope(audit_id="A", system_id="S", kb_version="kb1", step="assess", regmem=regmem)
    return next(t for t in _regulation_tools(scope) if t.name == name)


async def test_lookup_provision_reads_id_string_children_and_never_raises():
    body = {
        "id": "AIA.10",
        "text": "t",
        "children": ["AIA.10.1", "AIA.10.2"],
        "interpretations": ["I-1"],
    }
    text = await _tool(_RegMem(body), "lookup_provision").ainvoke({"provision_id": "AIA.10"})
    assert "AIA.10.1" in text and "I-1" in text
    text = await _tool(
        _RegMem(exc=PipelineHTTPError("reg-memory", 404, "x")), "lookup_provision"
    ).ainvoke({"provision_id": "AIA.99"})
    assert "404" in text
    text = await _tool(_RegMem(), "search_regulation").ainvoke({"query": "bias"})
    assert text.startswith("search_regulation failed: RuntimeError")


def test_spec_rule_ids_transforms_and_unknown_fields_are_repaired():
    dictionary = yaml.safe_dump(
        {"fields": {"sex": {"type": "category"}, "years": {"type": "integer"}}}
    )
    draft = yaml.safe_dump(
        {
            "version": 1,
            "name": "x",
            "n": 100,
            "rules": [{"id": "R1", "expr": "years >= 0"}, {"id": "R1", "expr": "years < 60"}],
            "fields": {"nope": {"provenance": "llm_assumption"}},
            "transforms": [
                {"kind": "twins", "attribute": "sex", "modes": ["causal", "bogus"]},
                {"kind": "twins", "attribute": "ghost"},
                {"kind": "perturbation", "fields": ["years", "ghost", "sex"]},
                {"kind": "shuffle"},
            ],
        }
    )
    fixed, _ = normalise_spec(draft, dictionary)
    spec = yaml.safe_load(fixed)
    assert [r["id"] for r in spec["rules"]] == ["R1", "S1"]
    assert spec["fields"] == {}
    assert spec["transforms"] == [
        {"kind": "twins", "attribute": "sex", "modes": ["causal"]},
        {"kind": "perturbation", "fields": ["years"]},
    ]
