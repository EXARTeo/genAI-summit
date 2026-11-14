"""The backend side of the agents' pipelines: audit start, impact index, re-run audits,
the change judge's write-back onto ``regulation_changes``."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

import utils.audit_pipeline as audit_pipeline
from core.database import RegulationChangeTable
from core.settings import settings

HEADERS = {"X-Internal-Secret": "s3cret"}


@pytest.fixture
def agents(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr("s3cret"))
    monkeypatch.setattr(settings.upstream, "audit_pipeline_autostart", True)
    calls: list[tuple[str, dict]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(202, json={"status": "started"})

    monkeypatch.setattr(audit_pipeline, "transport", httpx.MockTransport(handle))
    return calls


async def _system(client) -> None:
    assert (
        await client.post("/v1/systems", json={"id": "SYS-001", "name": "CV"})
    ).status_code == 201


async def test_a_new_audit_starts_its_pipeline(client, agents):
    await _system(client)
    audit = (await client.post("/v1/systems/SYS-001/audits", json={})).json()
    assert agents == [(f"/audits/{audit['id']}/run", {"system_id": "SYS-001", "trigger": "manual"})]
    off = await client.post("/v1/systems/SYS-001/audits", json={"data": {"autostart": False}})
    assert off.status_code == 201 and len(agents) == 1


async def test_an_unreachable_agents_service_never_fails_the_audit(client, monkeypatch, agents):
    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(audit_pipeline, "transport", httpx.MockTransport(boom))
    await _system(client)
    assert (await client.post("/v1/systems/SYS-001/audits", json={})).status_code == 201


async def test_impact_index_and_an_agent_started_rerun(client, agents):
    await _system(client)
    audit = (
        await client.post("/v1/systems/SYS-001/audits", json={"data": {"kb_version": "k1"}})
    ).json()
    base = f"/internal/audits/{audit['id']}"
    finding = {
        "requirement": "REQ.X",
        "verdict": "indicates_gap",
        "citations": [{"provision_id": "AIA.10"}],
    }
    await client.post(
        f"{base}/artifacts",
        json={"kind": "finding", "name": "F-01", "data": finding},
        headers=HEADERS,
    )
    await client.post(
        f"{base}/artifacts",
        json={"kind": "context", "data": {"requirements": [{"id": "REQ.X"}, {"id": "REQ.Y"}]}},
        headers=HEADERS,
    )
    index = (await client.get("/internal/impact-index", headers=HEADERS)).json()
    (row,) = index
    assert row["system_id"] == "SYS-001" and row["audit_id"] == audit["id"]
    assert row["kb_version"] == "k1" and row["requirements"] == ["REQ.X", "REQ.Y"]
    assert row["findings"][0]["id"] == "F-01" and row["findings"][0]["verdict"] == "indicates_gap"

    rerun = await client.post(
        "/internal/systems/SYS-001/audits",
        json={"data": {"trigger": "regchange:RC-1"}},
        headers={**HEADERS, "X-Agent-Name": "change-judge"},
    )
    assert rerun.status_code == 201
    assert rerun.json()["createdBy"] == "agent:change-judge"
    assert agents[-1] == (
        f"/audits/{rerun.json()['id']}/run",
        {"system_id": "SYS-001", "trigger": "regchange:RC-1"},
    )


async def test_the_change_judge_writes_back_and_keeps_human_overrides(
    client, agents, session_factory
):
    async with session_factory() as session:
        session.add(
            RegulationChangeTable(
                id="RC-1",
                data={
                    "affected": [
                        {"systemId": "SYS-001", "humanDecision": "no_impact", "decidedBy": "alice"}
                    ]
                },
            )
        )
        await session.commit()
    body = {
        "decidedBy": "gemini",
        "affected": [
            {
                "systemId": "SYS-001",
                "systemName": "CV",
                "decision": "rerun_tests",
                "confidence": 0.7,
            },
            {
                "systemId": "SYS-002",
                "systemName": "Credit",
                "decision": "no_impact",
                "confidence": 0.9,
            },
        ],
    }
    res = await client.put(
        "/internal/regulation/changes/RC-1/judgement", json=body, headers=HEADERS
    )
    assert res.status_code == 200 and res.json()["judge"] == "done"
    async with session_factory() as session:
        row = await session.get(RegulationChangeTable, "RC-1")
    first = row.data["affected"][0]
    assert first["decision"] == "rerun_tests" and first["humanDecision"] == "no_impact"
    assert row.data["judge"] == "done" and row.data["judgedBy"] == "gemini"
    assert (
        await client.put("/internal/regulation/changes/RC-1/judgement", json=body)
    ).status_code == 401
