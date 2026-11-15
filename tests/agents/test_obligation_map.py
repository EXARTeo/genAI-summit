"""``pipeline/obligations.py``: the system obligation map from the shipped catalogue
(``mnamon/reg-memory/corpus/obligations.yaml``) for the three seed systems, plus the
borderline rows Iris decides (a fake Iris; no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from pipeline.obligations import (
    activate_rows,
    applicable_ids,
    card_profile,
    resolve_obligation_map,
)

CATALOGUE_FILE = (
    Path(__file__).resolve().parents[2] / "mnamon" / "reg-memory" / "corpus" / "obligations.yaml"
)
TODAY = date(2026, 11, 15)

SYS_001 = {
    "id": "SYS-001",
    "name": "CV Screener",
    "role": "provider",
    "risk_class": "high_risk",
    "annex_basis": "Annex III 4(a)",
    "intended_purpose": "Rank applicants for software-engineering roles from their CVs.",
}
SYS_002 = {
    "id": "SYS-002",
    "name": "Credit Scorer",
    "role": "provider",
    "risk_class": "high_risk",
    "annex_basis": "Annex III 5(b)",
    "intended_purpose": "Score the creditworthiness of consumer-loan applicants.",
}
SYS_003 = {
    "id": "SYS-003",
    "name": "Benefits Eligibility Triage",
    "role": "deployer",
    "provider": "CivicLogic Software IKE (fictional)",
    "risk_class": "high_risk",
    "annex_basis": "Annex III 5(a)",
    "intended_purpose": "Pre-check minimum-income benefit applications for caseworkers.",
}

#: Every provider duty of a high-risk Annex III system without a 6(3) claim or features.
HIGH_RISK_PROVIDER = {
    "OBL.AIA.4.ai-literacy",
    "OBL.AIA.5.prohibited-practices-screening",
    "OBL.AIA.4a.special-category-data",
    "OBL.AIA.6.2.high-risk-classification",
    "OBL.AIA.9.1.risk-management-system",
    "OBL.AIA.9.2.risk-identification",
    "OBL.AIA.9.6.testing",
    "OBL.AIA.9.9.vulnerable-groups",
    "OBL.AIA.10.2.data-governance",
    "OBL.AIA.10.2.f.bias-examination",
    "OBL.AIA.10.2.g.bias-mitigation",
    "OBL.AIA.10.3.representativeness",
    "OBL.AIA.10.4.context-specific-data",
    "OBL.AIA.11.technical-documentation",
    "OBL.AIA.12.record-keeping",
    "OBL.AIA.13.instructions-for-use",
    "OBL.AIA.13.3.b.ii.declared-accuracy",
    "OBL.AIA.14.4.human-oversight",
    "OBL.AIA.15.1.accuracy",
    "OBL.AIA.15.3.declared-metrics",
    "OBL.AIA.15.4.robustness",
    "OBL.AIA.15.5.cybersecurity",
    "OBL.AIA.16.provider-duties",
    "OBL.AIA.17.quality-management-system",
    "OBL.AIA.18.documentation-keeping",
    "OBL.AIA.43.conformity-assessment",
    "OBL.AIA.47.eu-declaration-of-conformity",
    "OBL.AIA.48.ce-marking",
    "OBL.AIA.49.1.registration",
    "OBL.AIA.72.post-market-monitoring",
    "OBL.AIA.73.serious-incident-reporting",
}


@pytest.fixture(scope="module")
def catalogue() -> list[dict[str, Any]]:
    return yaml.safe_load(CATALOGUE_FILE.read_text(encoding="utf-8"))


class FakeIris:
    def __init__(self, answers: dict[str, float] | Exception) -> None:
        self.answers = answers
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def ask(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((state, questions))
        if isinstance(self.answers, Exception):
            raise self.answers
        return {k: {"noul": self.answers[k]} for k in questions}


def test_card_profile():
    assert card_profile(SYS_001) == {
        "role": "provider",
        "risk_class": "high",
        "basis": "annex_iii",
        "annex_point": "4.a",
        "features": None,
        "claims_6_3": False,
    }
    assert card_profile({"annex_basis": "AIA.ANNEX_III.5.b"})["annex_point"] == "5.b"
    assert card_profile({"annex_basis": "Annex I"})["basis"] == "annex_i"


@pytest.mark.parametrize("card", [SYS_001, SYS_002])
async def test_seed_providers_get_every_high_risk_duty(card, catalogue):
    entries = await resolve_obligation_map(card, "2026.11.15-1", catalogue=catalogue, on=TODAY)
    assert len(entries) == len(catalogue)
    assert set(applicable_ids(entries)) == HIGH_RISK_PROVIDER
    by_id = {e["obligation_id"]: e for e in entries}
    bias = by_id["OBL.AIA.10.2.f.bias-examination"]
    assert bias["article"] == "AIA.10.2.f" and bias["verification_mode"] == "model_test"
    assert bias["in_force_date"] == "2027-12-02" and bias["in_force_now"] is False
    assert bias["decided_by"] == "rule" and bias["checks"][0]["templates"]
    assert by_id["OBL.AIA.4.ai-literacy"]["in_force_now"] is True
    # no 6(3) claim: the exemption rows do not apply
    assert not by_id["OBL.AIA.6.4.non-high-risk-assessment"]["applicable"]
    # undeclared features: Art. 50 is a borderline row, not applicable by rule
    disclosure = by_id["OBL.AIA.50.1.ai-interaction-disclosure"]
    assert not disclosure["applicable"] and disclosure["borderline"]
    assert "declares no features" in disclosure["reason"]
    assert all(not k.startswith("_") for e in entries for k in e)


async def test_seed_deployer_keeps_only_operator_duties(catalogue):
    entries = await resolve_obligation_map(SYS_003, "2026.11.15-1", catalogue=catalogue, on=TODAY)
    assert set(applicable_ids(entries)) == {
        "OBL.AIA.4.ai-literacy",
        "OBL.AIA.5.prohibited-practices-screening",
    }
    accuracy = next(e for e in entries if e["obligation_id"] == "OBL.AIA.15.1.accuracy")
    assert "system role is deployer" in accuracy["reason"]


async def test_declared_features_trigger_art_50(catalogue):
    card = {**SYS_001, "features": ["interacts_with_persons"]}
    ids = set(applicable_ids(activate_rows(card, catalogue, on=TODAY)))
    assert "OBL.AIA.50.1.ai-interaction-disclosure" in ids
    assert "OBL.AIA.50.2.synthetic-content-marking" not in ids
    entries = await resolve_obligation_map(card, None, iris=FakeIris({}), catalogue=catalogue)
    assert all(e["decided_by"] == "rule" for e in entries)  # nothing borderline -> no call


async def test_iris_decides_features_borderline_rows(catalogue):
    iris = FakeIris(
        {"feature_interacts_with_persons": 0.91, "feature_generates_synthetic_content": 0.08}
    )
    entries = await resolve_obligation_map(SYS_001, None, iris=iris, catalogue=catalogue, on=TODAY)
    [(state, questions)] = iris.calls
    assert set(questions) == {
        "feature_interacts_with_persons",
        "feature_generates_synthetic_content",
    }
    assert state["system"]["id"] == "SYS-001" and "intended_purpose" in state["system"]
    by_id = {e["obligation_id"]: e for e in entries}
    yes = by_id["OBL.AIA.50.1.ai-interaction-disclosure"]
    no = by_id["OBL.AIA.50.2.synthetic-content-marking"]
    assert yes["applicable"] and yes["decided_by"] == "iris" and "p=0.91" in yes["reason"]
    assert not no["applicable"] and no["decided_by"] == "iris"
    assert by_id["OBL.AIA.15.1.accuracy"]["decided_by"] == "rule"


async def test_6_3_claim_is_borderline_and_iris_decides(catalogue):
    card = {**SYS_001, "exempt_6_3": True, "features": []}
    rule = {e["obligation_id"]: e for e in activate_rows(card, catalogue, on=TODAY)}
    # without Iris: conservative, both the high-risk duties and the 6(4) documentation apply
    assert (
        rule["OBL.AIA.15.1.accuracy"]["applicable"] and rule["OBL.AIA.15.1.accuracy"]["borderline"]
    )
    assert rule["OBL.AIA.6.4.non-high-risk-assessment"]["applicable"]
    holds = await resolve_obligation_map(
        card, None, iris=FakeIris({"derogation_6_3_holds": 0.8}), catalogue=catalogue, on=TODAY
    )
    by_id = {e["obligation_id"]: e for e in holds}
    assert not by_id["OBL.AIA.15.1.accuracy"]["applicable"]
    assert by_id["OBL.AIA.6.4.non-high-risk-assessment"]["applicable"]
    assert by_id["OBL.AIA.49.2.registration-non-high-risk"]["decided_by"] == "iris"
    assert by_id["OBL.AIA.4.ai-literacy"]["decided_by"] == "rule"  # not claim-gated
    rejected = await resolve_obligation_map(
        card, None, iris=FakeIris({"derogation_6_3_holds": 0.2}), catalogue=catalogue, on=TODAY
    )
    by_id = {e["obligation_id"]: e for e in rejected}
    assert by_id["OBL.AIA.15.1.accuracy"]["applicable"]
    assert not by_id["OBL.AIA.6.4.non-high-risk-assessment"]["applicable"]


async def test_iris_failure_keeps_rule_defaults(catalogue):
    entries = await resolve_obligation_map(
        SYS_001, None, iris=FakeIris(RuntimeError("http_503")), catalogue=catalogue, on=TODAY
    )
    assert set(applicable_ids(entries)) == HIGH_RISK_PROVIDER
    disclosure = next(e for e in entries if e["obligation_id"].startswith("OBL.AIA.50.1"))
    assert "Iris unavailable: http_503" in disclosure["reason"]
    assert disclosure["decided_by"] == "rule"


async def test_catalogue_is_fetched_from_reg_memory_when_not_given(catalogue):
    class FakeRegMemory:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def _get(self, path: str, **params: Any) -> Any:
            self.calls.append((path, params))
            return {"items": catalogue}

    regmem = FakeRegMemory()
    entries = await resolve_obligation_map(SYS_002, "2026.11.15-1", regmem=regmem, on=TODAY)
    assert regmem.calls == [
        ("/v1/obligations", {"kb_version": "2026.11.15-1", "include_not_applicable": "true"})
    ]
    assert set(applicable_ids(entries)) == HIGH_RISK_PROVIDER
