"""The regulation-change flow (plan 01 §9) on the agents side: obligation-map impact,
the change judge's focused re-run, stale marks and the delta report (no network)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pipeline.decision import Decision
from pipeline.impact import impact_index, judge_brief
from pipeline.obligations import resolve_obligation_map
from pipeline.schemas import ChangeJudgement

from schema.audits import ChangeJudgeIn
from utils.change_judge import (
    build_delta_report,
    finding_metrics,
    judge_change,
    merge_systems,
    watch_delta,
)

CATALOGUE = yaml.safe_load(
    (
        Path(__file__).resolve().parents[2]
        / "mnamon"
        / "reg-memory"
        / "corpus"
        / "obligations.yaml"
    ).read_text(encoding="utf-8")
)

CARDS = {
    "SYS-001": {
        "id": "SYS-001",
        "role": "provider",
        "risk_class": "high_risk",
        "annex_basis": "Annex III 4(a)",
    },
    "SYS-002": {
        "id": "SYS-002",
        "role": "provider",
        "risk_class": "high_risk",
        "annex_basis": "Annex III 5(b)",
    },
    "SYS-003": {
        "id": "SYS-003",
        "role": "deployer",
        "risk_class": "high_risk",
        "annex_basis": "Annex III 5(a)",
    },
}

#: A guideline change (the demo mirror) whose interpretation relates to Art. 10(2)(f).
CHANGE = {
    "id": "RC-2026.11.15-2",
    "from_kb_version": "2026.11.15-1",
    "to_kb_version": "2026.11.15-2",
    "change_types": {"new_interpretation": 1},
    "impacted_requirements": [],
    "impacted_obligations": [
        {"obligation_id": "OBL.AIA.10.2.f.bias-examination", "via": ["AIA.10.2.f"]}
    ],
    "provisions": [],
    "interpretations": [
        {
            "id": "INT.demo-art6-guideline-mirror.s4",
            "kind": "interpretation",
            "change": "changed",
            "relates_to": ["AIA.10.2.f"],
        }
    ],
}

INDEX = [
    {
        "system_id": "SYS-001",
        "name": "CV Screener",
        "audit_id": "SYS-001-20261115-0900",
        "kb_version": "2026.11.15-1",
        "findings": [
            {
                "id": "F-bias",
                "requirement": "REQ.AIA.10.2.f.bias-examination",
                "verdict": "gap",
                "metrics": {"selection_rate_ratio": 0.62},
            },
            {"id": "F-acc", "requirement": "REQ.AIA.15.1.accuracy-consistency", "verdict": "pass"},
        ],
        "tests": [],
    },
    {"system_id": "SYS-002", "name": "Credit Scorer", "audit_id": None, "findings": []},
    {"system_id": "SYS-003", "name": "Benefits Triage", "audit_id": None, "findings": []},
]


async def _resolver(card, kb_version, *, iris=None, regmem=None):
    return await resolve_obligation_map(card, kb_version, iris=iris, catalogue=CATALOGUE)


async def _maps() -> dict[str, list[dict[str, Any]]]:
    return {sid: await _resolver(card, CHANGE["to_kb_version"]) for sid, card in CARDS.items()}


class Recorder:
    """BackendInternal stand-in for many audits (artifacts per audit id)."""

    def __init__(self) -> None:
        self.artifacts: dict[str, list[dict[str, Any]]] = {}
        self.audits: dict[str, dict[str, Any]] = {}

    def __call__(self, audit_id: str) -> Recorder.Scoped:
        return Recorder.Scoped(self, audit_id)

    class Scoped:
        def __init__(self, parent: Recorder, audit_id: str) -> None:
            self.parent, self.audit_id = parent, audit_id

        async def write_artifact(self, kind, data, *, name="main", file_refs=None, status="x"):
            items = self.parent.artifacts.setdefault(self.audit_id, [])
            art = {"id": f"art-{len(items) + 1}", "kind": kind, "name": name, "data": data}
            items.append(art)
            return art

        async def audit(self) -> dict[str, Any]:
            audit = self.parent.audits.get(self.audit_id) or {"id": self.audit_id}
            if callable(audit):
                audit = audit()
            return {"audit": {**audit, "artifacts": self.parent.artifacts.get(self.audit_id, [])}}


class Impact:
    def __init__(self) -> None:
        self.started: list[tuple[str, dict[str, Any]]] = []
        self.stored: list[tuple[str, list[dict[str, Any]], str]] = []

    async def impact_index(self):
        return [dict(s) for s in INDEX]

    async def start_audit(self, system_id, data):
        self.started.append((system_id, dict(data)))
        return {"id": f"{system_id}-20261115-1200"}

    async def store_judgement(self, change_id, affected, decided_by):
        self.stored.append((change_id, affected, decided_by))


class Judge:
    name = "iris"

    def __init__(self) -> None:
        self.briefs: list[dict[str, Any]] = []

    async def judge(self, brief, scope):
        self.briefs.append(brief)
        has_findings = any(f.get("obligation_id") for f in brief["findings"])
        decision = "rerun_tests" if has_findings else "new_tests_needed"
        return Decision(
            result=ChangeJudgement(
                decision=decision,
                rationale="r",
                strongest_counter_argument="c",
                affected_findings=[],
                affected_requirements=list(brief["impacted_requirements"]),
                confidence=0.8,
            ),
            model="iris",
            fallback=False,
            latency_ms=1,
        )


class Findings:
    def __init__(self, sealed: list[dict[str, Any]] | None = None) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.sealed = sealed or []

    async def status_event(self, finding_id, body):
        self.events.append((finding_id, body))
        return {"id": "ev-1"}

    async def audit_findings(self, audit_id):
        return self.sealed


async def test_impact_goes_through_the_obligation_map():
    maps = await _maps()
    affected = {a.system_id: a for a in impact_index(CHANGE, INDEX, maps)}
    # the deployer's map has no Art. 10 obligation; both providers' maps do
    assert set(affected) == {"SYS-001", "SYS-002"}
    sys1 = affected["SYS-001"]
    assert "OBL.AIA.10.2.f.bias-examination" in sys1.via_obligations
    assert "OBL.AIA.4a.special-category-data" in sys1.via_obligations  # related AIA.10.2.f
    assert [f["id"] for f in sys1.affected_findings] == ["F-bias"]
    brief = judge_brief(CHANGE, sys1)
    assert {o["obligation_id"] for o in brief["affected_obligations"]} == set(sys1.via_obligations)
    bias = next(f for f in brief["findings"] if f["id"] == "F-bias")
    assert bias["obligation_id"] == "OBL.AIA.10.2.f.bias-examination"
    assert "REQ.AIA.10.2.f.bias-examination" in brief["impacted_requirements"]
    # without maps the old evidence paths still decide (no requirement listed -> nothing)
    assert impact_index(CHANGE, INDEX) == []


async def test_judge_starts_focused_reruns_marks_stale_and_spawns_the_delta_watcher():
    rec, impact, judge, findings = Recorder(), Impact(), Judge(), Findings()
    spawned: list[Any] = []
    out = await judge_change(
        CHANGE["id"],
        ChangeJudgeIn(
            change=CHANGE,
            rerun=True,
            systems=[{"system_id": sid, "card": card} for sid, card in CARDS.items()],
        ),
        backend=impact,  # type: ignore[arg-type]
        model=judge,  # type: ignore[arg-type]
        audit_backend=rec,  # type: ignore[arg-type]
        resolver=_resolver,
        iris=False,
        findings_api=findings,  # type: ignore[arg-type]
        spawn=spawned.append,
    )
    by = {j.system_id: j for j in out.judgements}
    assert set(by) == {"SYS-001", "SYS-002"}
    assert by["SYS-001"].decision == "rerun_tests" and by["SYS-002"].decision == "new_tests_needed"
    assert by["SYS-001"].stale_findings == ["F-bias"]
    started = dict(impact.started)
    focused = started["SYS-001"]
    assert focused["kb_version"] == "2026.11.15-2" and focused["focused"] is True
    assert "OBL.AIA.10.2.f.bias-examination" in focused["obligations"]
    assert focused["previous_audit_id"] == "SYS-001-20261115-0900"
    assert focused["change_id"] == CHANGE["id"]
    # SYS-001's judgement on its latest audit; SYS-002 has none -> on its re-run
    old = rec.artifacts["SYS-001-20261115-0900"]
    assert {a["kind"] for a in old} == {"change_judgement", "finding_status"}
    stale = next(a for a in old if a["kind"] == "finding_status")
    assert stale["data"]["finding"] == "F-bias" and stale["data"]["status"] == "stale"
    assert stale["data"]["reg_change_id"] == CHANGE["id"]
    assert rec.artifacts["SYS-002-20261115-1200"][0]["kind"] == "change_judgement"
    assert len(spawned) == 2
    for coro in spawned:
        coro.close()
    ((_, rows, decided_by),) = impact.stored
    row = next(r for r in rows if r["systemId"] == "SYS-001")
    assert decided_by == "iris" and row["obligations"] == by["SYS-001"].affected_obligations
    assert row["staleFindings"] == ["F-bias"]


async def test_sealed_findings_get_a_status_event():
    sealed = {
        "id": "fnd-1",
        "audit_id": "SYS-001-20261115-0900",
        "obligation_id": "OBL.AIA.10.2.f.bias-examination",
        "verdict": "gap",
        "hash": "sha256:abcdefgh",
        "kb_version": "2026.11.15-1",
    }
    rec, impact, findings = Recorder(), Impact(), Findings()
    out = await judge_change(
        CHANGE["id"],
        ChangeJudgeIn(
            change=CHANGE,
            system_ids=["SYS-001"],
            systems=[{"system_id": "SYS-001", "card": CARDS["SYS-001"], "findings": [sealed]}],
        ),
        backend=impact,  # type: ignore[arg-type]
        model=Judge(),  # type: ignore[arg-type]
        audit_backend=rec,  # type: ignore[arg-type]
        resolver=_resolver,
        iris=False,
        findings_api=findings,  # type: ignore[arg-type]
        spawn=lambda coro: coro.close(),
    )
    assert out.judgements[0].stale_findings == ["fnd-1"]
    ((fid, body),) = findings.events
    assert fid == "fnd-1" and body["status"] == "stale"
    assert body["data"]["reg_change_id"] == CHANGE["id"]
    assert impact.started == []  # no rerun asked
    kinds = [a["kind"] for a in rec.artifacts["SYS-001-20261115-0900"]]
    assert kinds == ["change_judgement"]


def test_merge_systems_prefers_sealed_findings():
    merged = merge_systems(
        INDEX,
        [{"system_id": "SYS-001", "card": CARDS["SYS-001"], "findings": [{"id": "fnd-1"}]}],
    )
    sys1 = next(s for s in merged if s["system_id"] == "SYS-001")
    assert sys1["card"]["id"] == "SYS-001" and sys1["findings"] == [{"id": "fnd-1", "sealed": True}]


@pytest.mark.parametrize(
    ("old_model", "new_model", "reason"),
    [("v3", "v3", "law_changed"), ("v3", "v4", "law_and_model_changed")],
)
def test_delta_report_rows(old_model, new_model, reason):
    old = [
        {
            "id": "F-bias",
            "obligation_id": "OBL.AIA.10.2.f.bias-examination",
            "verdict": "gap",
            "kb_version": "2026.11.15-1",
            "metrics": {"selection_rate_ratio": 0.62},
        }
    ]
    new = [
        {
            "id": "fnd-9",
            "obligation_id": "OBL.AIA.10.2.f.bias-examination",
            "verdict": "partial",
            "kb_version": "2026.11.15-2",
            "metrics_ref": [{"metric": "selection_rate_ratio", "value": 0.78}],
        },
        {"id": "fnd-10", "obligation_id": "OBL.AIA.4a.special-category-data", "verdict": "pass"},
    ]
    ctx = {
        "change_id": CHANGE["id"],
        "system_id": "SYS-001",
        "from_kb_version": "2026.11.15-1",
        "to_kb_version": "2026.11.15-2",
        "obligations": ["OBL.AIA.10.2.f.bias-examination", "OBL.AIA.4a.special-category-data"],
    }
    report = build_delta_report(
        ctx,
        old,
        new,
        old_audit={"id": "A1", "pins": {"model_version": old_model}},
        new_audit={"id": "A2", "status": "done", "pins": {"model_version": new_model}},
    )
    rows = {r["obligation_id"]: r for r in report["obligations"]}
    bias = rows["OBL.AIA.10.2.f.bias-examination"]
    assert bias["verdict_change"] == "gap -> partial" and bias["verdict_changed"]
    assert bias["reason"] == reason
    assert bias["metric_deltas"] == [
        {"metric": "selection_rate_ratio", "old": 0.62, "new": 0.78, "delta": 0.16}
    ]
    assert rows["OBL.AIA.4a.special-category-data"]["reason"] == "new_evidence"
    assert report["audit_id"] == "A2" and "1 verdict(s) changed" not in report["summary"]
    assert "2 verdict(s) changed" in report["summary"]


def test_finding_metrics_shapes():
    assert finding_metrics({"metric": "f1", "value": 0.7}) == {"f1": 0.7}
    assert finding_metrics({"data": {"metrics": {"a": {"value": 1}, "b": "x"}}}) == {"a": 1.0}


async def test_watch_delta_waits_for_the_audit_then_writes_the_report():
    rec, findings = (
        Recorder(),
        Findings(
            sealed=[
                {
                    "id": "fnd-9",
                    "obligation_id": "OBL.AIA.10.2.f.bias-examination",
                    "verdict": "pass",
                    "kb_version": "2026.11.15-2",
                }
            ]
        ),
    )
    statuses = iter(["running", "waiting_approval", "done"])
    rec.audits["SYS-001-20261115-1200"] = lambda: {
        "id": "SYS-001-20261115-1200",
        "status": next(statuses, "done"),
    }
    slept: list[float] = []

    async def sleep(seconds):
        slept.append(seconds)

    ctx = {
        "change_id": CHANGE["id"],
        "system_id": "SYS-001",
        "previous_audit_id": "SYS-001-20261115-0900",
        "from_kb_version": "2026.11.15-1",
        "to_kb_version": "2026.11.15-2",
        "obligations": ["OBL.AIA.10.2.f.bias-examination"],
        "old_findings": [
            {"id": "F-bias", "requirement": "REQ.AIA.10.2.f.bias-examination", "verdict": "gap"}
        ],
        "entries": await _resolver(CARDS["SYS-001"], "2026.11.15-2"),
    }
    report = await watch_delta(
        "SYS-001-20261115-1200",
        ctx,
        audit_backend=rec,  # type: ignore[arg-type]
        findings_api=findings,  # type: ignore[arg-type]
        poll_seconds=1,
        sleep=sleep,
    )
    assert report is not None and slept == [1, 1]
    (art,) = rec.artifacts["SYS-001-20261115-1200"]
    assert art["kind"] == "delta_report" and art["name"] == CHANGE["id"]
    (row,) = art["data"]["obligations"]
    assert row["verdict_change"] == "gap -> pass" and row["reason"] == "law_changed"
