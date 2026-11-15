"""The copilot's history tools (``harness/tools/workspace_api/history.py`` + ``rerun.py``).

Recorded shapes of the backend and reg-memory behind an ``httpx.MockTransport``;
no network, no model. Covers the tool shapes, the deterministic
``audit_needs_rerun`` rule, the fallbacks for routes that land later (diff,
findings, obligations), the extended ``start_audit`` intake and the approval
gates on the two writes.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from conftest import CLIENT_ID, SERVICE_ROOT

from harness.tools import builtins
from harness.tools.workspace_api import WorkspaceAPI, WorkspaceScope, build_workspace_tool, rerun
from harness.tools.workspace_api import client as workspace_client
from utils.agents import build_registry

SLUG = "mnamon"
AUDIT = "SYS-001-20261115-0026"
OLD_KB = "2026.11.14-1"
NEW_KB = "2026.11.15-1"

RELEASES = {
    "active": NEW_KB,
    "items": [
        {
            "kb_version": NEW_KB,
            "status": "active",
            "parent": OLD_KB,
            "counts": {"provisions": 1720},
        },
        {"kb_version": OLD_KB, "status": "superseded", "parent": None},
    ],
}

REGMEM_CHANGES = {
    "items": [{"id": "RC-2026.11.15-1", "from_kb_version": OLD_KB, "to_kb_version": NEW_KB}]
}


def _change(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "RC-2026.11.15-1",
        "from_kb_version": OLD_KB,
        "to_kb_version": NEW_KB,
        "provisions": [{**r, "old_text": "long text", "new_text": "long text"} for r in rows],
    }


SUBSTANTIVE = [
    {"id": "AIA.10.2.f", "change": "changed", "change_type": "substantive"},
    {"id": "AIA.101.1", "change": "changed", "change_type": "editorial"},
]

BACKEND_CHANGES = [
    {
        "id": "RC-2026.11.15-1",
        "title": "Data governance",
        "status": "accepted",
        "changeType": "scope_change",
        "candidateKbVersion": NEW_KB,
        "detectedAt": "2026-11-15T00:08:45+00:00",
        "provisions": ["AIA.10.2.f", "AIA.101.1"],
        "summary": "2 provisions changed",
        "affected": [
            {
                "systemId": "SYS-001",
                "systemName": "CV Screener",
                "decision": "rerun_tests",
                "confidence": 0.8,
                "reasoning": "Art. 10(2)(f) changed",
                "findings": ["F-01"],
            }
        ],
        "impactedRequirements": [{"requirement_id": "REQ.AIA.10.2.f", "via": ["AIA.10.2.f"]}],
        "judge": "done",
    }
]


def _audit(kb: str | None = OLD_KB, *, with_map: bool = True) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = [
        {
            "id": "art-ctx",
            "kind": "context",
            "name": "main",
            "version": 1,
            "status": "proposed",
            "data": {
                "kb_version": kb or "unknown",
                "requirements": [
                    {"id": "REQ.AIA.15.1.accuracy", "source": "AIA.15.1", "related": []}
                ],
            },
        },
        {
            "id": "art-f1",
            "kind": "finding",
            "name": "F-01",
            "version": 1,
            "status": "superseded",
            "data": {"id": "F-01", "verdict": "inconclusive"},
        },
        {
            "id": "art-f1b",
            "kind": "finding",
            "name": "F-01",
            "version": 2,
            "status": "proposed",
            "data": {
                "id": "F-01",
                "requirement": "REQ.AIA.10.2.f.bias",
                "title": "Nationality proxy via postcode",
                "verdict": "indicates_gap",
                "confidence": 0.8,
                "reasoning": "Selection rate ratio below the org threshold.",
                "evidence": [
                    {
                        "test_id": "T-01",
                        "metric": "selection_rate_ratio",
                        "value": 0.62,
                        "threshold": ">= 0.80",
                        "threshold_source": "system-card org_thresholds",
                    }
                ],
                "counter_evidence": ["Small subgroup"],
                "citations": [{"provision_id": "AIA.10.2.f", "kb_version": kb}],
            },
        },
        {
            "id": "art-scen",
            "kind": "scenarios",
            "name": "main",
            "version": 1,
            "status": "approved",
            "data": {},
        },
    ]
    if with_map:
        artifacts.append(
            {
                "id": "art-map",
                "kind": "obligation_map",
                "name": "main",
                "version": 1,
                "status": "approved",
                "data": {
                    "obligations": [
                        {"id": "OBL.AIA.10.2.f", "applies": True, "provisions": ["AIA.10.2.f"]},
                        {"id": "OBL.AIA.15.1", "applies": True, "provisions": ["AIA.15.1"]},
                        {"id": "OBL.AIA.50.1", "applies": False, "provisions": ["AIA.50.1"]},
                    ]
                },
            }
        )
    data: dict[str, Any] = {}
    if kb:
        data["pins"] = {"kb_version": kb, "dossier_version": 3, "seeds": {"data": 7}}
    return {
        "id": AUDIT,
        "systemId": "SYS-001",
        "status": "completed",
        "stage": "report",
        "data": data,
        "artifacts": artifacts,
        "approvals": [
            {
                "id": "ap-1",
                "auditId": AUDIT,
                "artifactId": "art-scen",
                "gate": "scenarios",
                "decision": "rejected",
                "reasonCategory": "wrong_obligation",
                "comment": "T-03 tests deployer duties, not ours.",
                "edits": {},
                "decidedBy": "client:abc",
                "at": "2026-11-15T00:30:00Z",
            },
            {
                "id": "ap-2",
                "auditId": AUDIT,
                "artifactId": None,
                "gate": "datasets",
                "decision": "approved",
                "edits": {"n": 2000},
                "decidedBy": "client:abc",
                "at": "2026-11-15T00:40:00Z",
            },
        ],
    }


class _Fake:
    """Backend + reg-memory: canned bodies per route, every request recorded."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.audit = _audit()
        self.change_rows = SUBSTANTIVE
        self.diff_route = False
        self.findings_route = False
        self.obligations_route = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path == "/v1/releases":
            return httpx.Response(200, json=RELEASES)
        if "/diff/" in path:
            if not self.diff_route:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json={"provisions": self.change_rows})
        if path == "/v1/changes":
            return httpx.Response(200, json=REGMEM_CHANGES)
        if path.startswith("/v1/changes/"):
            return httpx.Response(200, json=_change(self.change_rows))
        if path == "/v1/regulation/changes":
            return httpx.Response(200, json=BACKEND_CHANGES)
        if path.startswith("/v1/regulation/changes/"):
            return httpx.Response(200, json=BACKEND_CHANGES[0])
        if path == "/v1/obligations":
            if not self.obligations_route:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json={"items": [{"id": "OBL.AIA.10.2.f"}]})
        if path == "/v1/requirements":
            return httpx.Response(200, json={"items": [{"id": "REQ.AIA.10.2.f", "source": "x"}]})
        if path.endswith("/findings"):
            if not self.findings_route:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "fnd-1",
                        "auditId": AUDIT,
                        "gap_id": "G-SYS-001-01",
                        "verdict": "gap",
                        "sealed": True,
                        "obligation_id": "OBL.AIA.10.2.f",
                    }
                ],
            )
        if path == "/v1/audits":
            return httpx.Response(200, json=[{"id": AUDIT, "systemId": "SYS-001"}])
        if path == f"/v1/audits/{AUDIT}":
            return httpx.Response(200, json=self.audit)
        if path == "/v1/systems/SYS-001" and method == "GET":
            card = {"role": "provider", "risk_class": "high_risk", "annex_basis": "Annex III 4(a)"}
            return httpx.Response(200, json={"id": "SYS-001", "data": {"card": card}})
        if path == "/v1/systems/SYS-001/audits" and method == "POST":
            return httpx.Response(
                201, json={"id": "SYS-001-20261115-1200", "systemId": "SYS-001", "status": "queued"}
            )
        if path == "/v1/systems/SYS-001/files/from-attachment":
            body = json.loads(request.content)
            return httpx.Response(
                201, json={"file": {"path": body["path"], "version": 1}, "changed": True}
            )
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def fake(monkeypatch) -> _Fake:
    fake = _Fake()
    monkeypatch.setattr(workspace_client, "transport", httpx.MockTransport(fake))
    return fake


def _tool(name: str, **scope):
    bound = WorkspaceScope(client_id=CLIENT_ID, agent_slug=SLUG, **scope)
    return build_workspace_tool(name, bound, WorkspaceAPI(client_id=CLIENT_ID, agent_slug=SLUG))


async def _call(name: str, args: dict[str, Any] | None = None, **scope) -> Any:
    out = await _tool(name, **scope).ainvoke(args or {})
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_pins_prefer_data_pins_then_data_then_artifacts():
    assert rerun.audit_pins(_audit())["kb_version"] == OLD_KB
    assert rerun.audit_pins(_audit())["source"] == "pins"
    legacy = {"data": {"kb_version": "kb-x"}, "artifacts": []}
    assert rerun.audit_pins(legacy) == {"kb_version": "kb-x", "source": "audit.data"}
    stamped = {"data": {}, "artifacts": [{"kind": "context", "data": {"kb_version": "kb-y"}}]}
    assert rerun.audit_pins(stamped)["source"] == "artifact:context"
    assert rerun.audit_pins({"data": {}, "artifacts": []}) == {"source": "none"}


def test_release_chain_walks_parents_and_refuses_a_gap():
    items = [
        {"kb_version": "c", "parent": "b"},
        {"kb_version": "b", "parent": "a"},
        {"kb_version": "a", "parent": None},
    ]
    assert rerun.release_chain(items, "c", "a") == ["b", "c"]
    assert rerun.release_chain(items, "c", "zzz") is None


def test_touches_matches_parents_and_children_only():
    assert rerun.touches("AIA.10.2.f", "AIA.10.2")
    assert rerun.touches("AIA.10.2", "AIA.10.2.f")
    assert not rerun.touches("AIA.10.20", "AIA.10.2")
    assert not rerun.touches("AIA.6.3", "AIA.6.2")


def test_audit_provisions_skip_obligations_that_do_not_apply():
    relied = rerun.audit_provisions(_audit())
    assert relied["OBL.AIA.10.2.f"] == {"AIA.10.2.f"}
    assert "OBL.AIA.50.1" not in relied
    assert relied["finding:F-01"] == {"AIA.10.2.f"}
    assert relied["REQ.AIA.15.1.accuracy"] == {"AIA.15.1"}


# ---------------------------------------------------------------------------
# audit_needs_rerun
# ---------------------------------------------------------------------------
async def test_a_substantive_change_on_a_relied_provision_needs_a_rerun(fake):
    out = await _call("audit_needs_rerun", {"audit_id": AUDIT})
    assert out["needs_rerun"] is True
    assert out["pinned_kb_version"] == OLD_KB and out["active_kb_version"] == NEW_KB
    assert [p["id"] for p in out["changed_provisions"]] == ["AIA.10.2.f"]
    assert {o["id"] for o in out["affected_obligations"]} == {
        "OBL.AIA.10.2.f",
        "REQ.AIA.10.2.f.bias",
    }
    assert out["affected_findings"] == ["F-01"]
    (related,) = out["related_reg_changes"]
    assert related["id"] == "RC-2026.11.15-1"
    assert related["judge_decision"] == "rerun_tests"
    assert out["diff_source"] == "changes on the release chain"
    assert "AIA.10.2.f" in out["reason"]
    assert out["pins"]["dossier_version"] == 3
    # Summaries only: no provision texts reach the model.
    assert "old_text" not in json.dumps(out)


async def test_the_audit_comes_from_the_conversation_scope(fake):
    out = await _call("audit_needs_rerun", audit_id=AUDIT)
    assert out["audit_id"] == AUDIT


async def test_only_editorial_changes_do_not_need_a_rerun(fake):
    fake.change_rows = [{"id": "AIA.10.2.f", "change": "changed", "change_type": "editorial"}]
    out = await _call("audit_needs_rerun", {"audit_id": AUDIT})
    assert out["needs_rerun"] is False
    assert "only editorial" in out["reason"]


async def test_changes_elsewhere_do_not_need_a_rerun(fake):
    fake.change_rows = [{"id": "AIA.101.1", "change": "changed", "change_type": "substantive"}]
    out = await _call("audit_needs_rerun", {"audit_id": AUDIT})
    assert out["needs_rerun"] is False and out["changed_provisions"] == []
    assert "none touches" in out["reason"]


async def test_an_audit_on_the_active_kb_needs_no_rerun_and_no_diff(fake):
    fake.audit = _audit(NEW_KB)
    out = await _call("audit_needs_rerun", {"audit_id": AUDIT})
    assert out["needs_rerun"] is False and NEW_KB in out["reason"]
    assert not any("/changes" in r.url.path for r in fake.requests)


async def test_an_audit_without_pins_cannot_be_compared(fake):
    fake.audit = _audit(None)
    out = await _call("audit_needs_rerun", {"audit_id": AUDIT})
    assert out["needs_rerun"] is False and "pinned no kb_version" in out["reason"]


async def test_the_reg_memory_diff_route_is_used_when_deployed(fake):
    fake.diff_route = True
    out = await _call("audit_needs_rerun", {"audit_id": AUDIT})
    assert out["needs_rerun"] is True and out["diff_source"] == "reg-memory diff"


async def test_no_audit_in_scope_asks_for_one(fake):
    out = await _call("audit_needs_rerun")
    assert "list_audits" in out and fake.requests == []


# ---------------------------------------------------------------------------
# Releases, diffs, changes
# ---------------------------------------------------------------------------
async def test_list_kb_releases_names_the_active_one(fake):
    out = await _call("list_kb_releases")
    assert out["active"] == NEW_KB
    assert out["releases"][0] == {
        "kb_version": NEW_KB,
        "status": "active",
        "parent": OLD_KB,
        "provisions": 1720,
    }


async def test_diff_kb_defaults_to_the_active_release_and_filters(fake):
    out = await _call("diff_kb", {"from_version": OLD_KB, "provisions": ["AIA.10"]})
    assert out["to"] == NEW_KB and out["total"] == 1
    assert out["provisions"][0]["id"] == "AIA.10.2.f"
    assert out["by_change_type"] == {"substantive": 1}
    assert out["reg_changes"] == ["RC-2026.11.15-1"]


async def test_diff_kb_without_a_chain_says_so(fake):
    out = await _call("diff_kb", {"from_version": "1999.01.01-1"})
    assert out.startswith("Could not diff")


async def test_reg_changes_are_listed_and_read_with_the_judge(fake):
    listed = await _call("list_reg_changes", {"status": "accepted"})
    assert listed["total"] == 1 and listed["items"][0]["affected_systems"] == ["SYS-001"]
    none = await _call("list_reg_changes", {"status": "proposed"})
    assert none["total"] == 0
    one = await _call("get_reg_change", {"change_id": "RC-2026.11.15-1"})
    assert one["from_kb_version"] == OLD_KB and one["to_kb_version"] == NEW_KB
    assert one["affected_systems"][0]["decision"] == "rerun_tests"
    assert one["by_change_type"] == {"substantive": 1, "editorial": 1}
    assert "old_text" not in json.dumps(one)


# ---------------------------------------------------------------------------
# Findings, gates, obligations
# ---------------------------------------------------------------------------
async def test_findings_fall_back_to_the_live_finding_artifacts(fake):
    out = await _call("list_findings", {"audit_id": AUDIT})
    assert out["source"] == "finding artifacts" and out["kb_version"] == OLD_KB
    (finding,) = out["findings"]  # the superseded F-01 v1 is dropped
    assert finding["id"] == "F-01" and finding["verdict"] == "indicates_gap"
    assert finding["evidence"][0]["threshold_source"] == "system-card org_thresholds"
    assert out["summary"] == {"total": 1, "by_verdict": {"indicates_gap": 1}, "gaps": ["F-01"]}


async def test_findings_use_the_findings_route_when_deployed(fake):
    fake.findings_route = True
    out = await _call("list_findings", {"audit_id": AUDIT})
    assert out["source"] == "findings"
    assert out["findings"][0]["id"] == "G-SYS-001-01" and out["findings"][0]["sealed"] is True
    system = await _call("list_findings", {"system_id": "SYS-001"})
    assert system["current"] is True
    assert any(r.url.params.get("current") == "true" for r in fake.requests)


async def test_system_findings_fall_back_to_the_latest_audit(fake):
    out = await _call("list_findings", system_id="SYS-001")
    assert out["audit_id"] == AUDIT and out["source"].endswith("latest audit")


async def test_gate_decisions_carry_reasons_and_artifacts(fake):
    out = await _call("get_gate_decisions", {"audit_id": AUDIT})
    assert out["by_gate"] == {"scenarios": 1, "datasets": 1}
    rejected = out["rejections"][0]
    assert rejected["reason_category"] == "wrong_obligation"
    assert rejected["artifact"] == "scenarios/main art-scen"
    assert "deployer duties" in rejected["comment"]
    assert out["decisions"][1]["edits"] == ["n"]


async def test_obligations_come_from_the_audit_map_then_the_catalogue(fake):
    out = await _call("list_obligations", system_id="SYS-001")
    assert out["source"] == f"obligation_map of {AUDIT}"
    assert [o["id"] for o in out["obligations"]][:2] == ["OBL.AIA.10.2.f", "OBL.AIA.15.1"]
    fake.audit = _audit(with_map=False)
    out = await _call("list_obligations", system_id="SYS-001")
    assert out["source"] == "reg-memory requirements"
    request = next(r for r in fake.requests if r.url.path == "/v1/requirements")
    assert request.url.params["basis"] == "AIA.ANNEX_III.4.a"
    assert request.url.params["risk_class"] == "high"
    fake.obligations_route = True
    out = await _call("list_obligations", system_id="SYS-001")
    assert out["source"] == "reg-memory obligations"


# ---------------------------------------------------------------------------
# The writes: start_audit(params) and attach_upload_to_audit_draft
# ---------------------------------------------------------------------------
async def test_start_audit_sends_the_intake(fake):
    out = await _call(
        "start_audit",
        {
            "mode": "focused",
            "obligations": ["OBL.AIA.15.1"],
            "kb_version": NEW_KB,
            "dataset_ref": "datasets/uploaded/applicants.csv",
        },
        system_id="SYS-001",
    )
    assert out["id"] == "SYS-001-20261115-1200"
    request = next(r for r in fake.requests if r.url.path.endswith("/audits"))
    assert json.loads(request.content) == {
        "data": {
            "mode": "focused",
            "obligations": ["OBL.AIA.15.1"],
            "kb_version": NEW_KB,
            "dataset_ref": "datasets/uploaded/applicants.csv",
            "requested_by": "agent:mnamon",
        }
    }


async def test_a_plain_start_audit_is_still_a_full_audit(fake):
    await _call("start_audit", system_id="SYS-001")
    request = next(r for r in fake.requests if r.url.path.endswith("/audits"))
    assert json.loads(request.content)["data"]["mode"] == "full"


async def test_start_audit_refuses_a_focused_run_without_obligations_or_an_unknown_kb(fake):
    out = await _call("start_audit", {"mode": "focused"}, system_id="SYS-001")
    assert "at least one obligation" in out
    out = await _call("start_audit", {"kb_version": "1999.01.01-1"}, system_id="SYS-001")
    assert "not a known release" in out
    assert not any(r.method == "POST" for r in fake.requests)


async def test_attach_copies_the_upload_into_datasets_uploaded(fake):
    out = await _call(
        "attach_upload_to_audit_draft",
        {"attachment_id": "att-1", "file_name": "../my applicants.csv"},
        system_id="SYS-001",
    )
    assert out["dataset_ref"] == "datasets/uploaded/my_applicants.csv"
    request = fake.requests[-1]
    assert request.url.path == "/v1/systems/SYS-001/files/from-attachment"
    body = json.loads(request.content)
    assert body["attachmentId"] == "att-1" and body["path"].startswith("datasets/uploaded/")
    assert request.headers["X-Client-Id"] == CLIENT_ID


def test_both_writes_ask_first_everywhere():
    defaults = builtins.builtin_hitl_defaults()
    assert defaults["start_audit"] is True
    assert defaults["attach_upload_to_audit_draft"] is True
    reads = ("list_kb_releases", "diff_kb", "audit_needs_rerun", "list_findings")
    assert not any(defaults.get(name) for name in reads)
    spec = build_registry(SERVICE_ROOT / "definitions")[SLUG].spec
    assert spec.hitl["start_audit"] is True and spec.hitl["attach_upload_to_audit_draft"] is True


def test_the_sub_agents_get_only_their_tools():
    spec = build_registry(SERVICE_ROOT / "definitions")[SLUG].spec
    tools = {sa.name: {t.native for t in sa.tools} for sa in spec.subagents}
    assert "audit_needs_rerun" in tools["regulation-historian"]
    assert {"list_findings", "get_gate_decisions"} <= tools["audit-analyst"]
    assert {"start_audit", "attach_upload_to_audit_draft"} <= tools["test-designer"]
    assert "start_audit" not in tools["audit-analyst"] | tools["regulation-historian"]
    assert "start_audit" not in tools["evidence-analyst"]
    for name in ("audit-analyst", "regulation-historian", "test-designer"):
        prompt = (SERVICE_ROOT / "definitions" / SLUG / "subagents" / f"{name}.md").read_text(
            encoding="utf-8"
        )
        assert len(prompt.split()) <= 150 and "Return:" in prompt


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------
async def test_a_run_has_a_call_budget(fake, monkeypatch):
    monkeypatch.setattr(workspace_client, "MAX_CALLS_PER_RUN", 2)
    tool = _tool("list_kb_releases")
    assert "active" in await tool.ainvoke({})
    assert "active" in await tool.ainvoke({})
    assert "429" in await tool.ainvoke({})
