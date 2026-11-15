"""Sealed findings (plan 01 §7.2), audit pins, retry and the PATCH ban on finding artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import delete, update
from sqlalchemy.exc import DatabaseError

from core.database import FindingAnnotationTable, FindingTable
from core.settings import settings

SERVICE_ROOT = Path(__file__).resolve().parents[2] / "mnamon" / "backend"


@pytest.fixture
def internal(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr("s3cret"))
    return {"X-Internal-Secret": "s3cret", "X-Agent-Name": "seal"}


async def _audit(client, sid: str = "SYS-001") -> dict:
    if (await client.get(f"/v1/systems/{sid}")).status_code == 404:
        created = await client.post("/v1/systems", json={"id": sid, "name": "CV"})
        assert created.status_code == 201
    response = await client.post(f"/v1/systems/{sid}/audits", json={"data": {"kb_version": "k1"}})
    assert response.status_code == 201, response.text
    return response.json()


def _finding(obligation: str = "OBL.AIA.10.2.f", **extra) -> dict:
    return {
        "obligation_id": obligation,
        "verdict": "gap",
        "severity": "critical",
        "gap_id": "G-01",
        "metrics_ref": {"path": "/audit/metrics.json"},
        "evidence_refs": [{"path": "/audit/predictions.parquet", "sha256": "ab" * 32}],
        "citations": [{"provision_id": "AIA.10.2.f", "kb_version": "k1"}],
        "kb_version": "k1",
        "reasoning": "Selection rate gap 0.31 above the org threshold 0.1.",
        "counter_arguments": ["Postcode may proxy commute distance."],
        "would_change_if": ["The gap closes after removing postcode."],
        "judges": {"rule": "gap", "gemini": "gap", "iris": "gap"},
        "critic": {"upheld": True, "objection": "Sample is small."},
        "article": "Art. 10(2)(f)",
        **extra,
    }


async def _seal(client, internal, audit_id: str, **extra) -> dict:
    response = await client.post(
        f"/internal/audits/{audit_id}/findings", json=_finding(**extra), headers=internal
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()


async def test_seal_is_idempotent_on_hash_and_chains(client, internal):
    audit = await _audit(client)
    url = f"/internal/audits/{audit['id']}/findings"
    assert (await client.post(url, json=_finding())).status_code == 401

    first = await client.post(url, json=_finding(), headers=internal)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["sealed"] is True and body["status"] == "current"
    assert body["data"] == {"article": "Art. 10(2)(f)"}
    assert body["created_by"] == "agent:seal" and len(body["hash"]) == 64

    again = await client.post(url, json=_finding(), headers=internal)
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]

    second = await _seal(client, internal, audit["id"], obligation="OBL.AIA.15.1", verdict="pass")
    assert second["prev_hash"] == body["hash"]

    explicit = await _seal(
        client, internal, audit["id"], obligation="OBL.AIA.12", hash="h" * 64, prev_hash="p" * 64
    )
    assert explicit["hash"] == "h" * 64
    listed = (await client.get(f"/v1/audits/{audit['id']}/findings")).json()
    assert [f["obligation_id"] for f in listed] == ["OBL.AIA.10.2.f", "OBL.AIA.15.1", "OBL.AIA.12"]

    bad = await client.post(
        url, json={**_finding(), "verdict": "supports_compliance"}, headers=internal
    )
    assert bad.status_code == 422


async def test_db_rejects_update_and_delete(client, internal, session_factory):
    audit = await _audit(client)
    sealed = await _seal(client, internal, audit["id"])
    note = await client.post(
        f"/v1/findings/{sealed['id']}/annotations", json={"kind": "contest", "body": "Not a proxy."}
    )
    assert note.status_code == 201

    for statement in (
        update(FindingTable).where(FindingTable.id == sealed["id"]).values(verdict="pass"),
        delete(FindingTable).where(FindingTable.id == sealed["id"]),
        update(FindingAnnotationTable).values(body="edited"),
        delete(FindingAnnotationTable),
    ):
        async with session_factory() as session:
            with pytest.raises(DatabaseError, match="append-only"):
                await session.execute(statement)
                await session.commit()

    again = (await client.get(f"/v1/audits/{audit['id']}/findings")).json()[0]
    assert again["verdict"] == "gap"
    assert [a["body"] for a in again["annotations"]] == ["Not a proxy."]


async def test_annotations_and_kinds(client, internal):
    audit = await _audit(client)
    sealed = await _seal(client, internal, audit["id"])
    base = f"/v1/findings/{sealed['id']}/annotations"
    for kind in ("contest", "accept_risk", "remediation_planned", "comment"):
        assert (await client.post(base, json={"kind": kind, "body": kind})).status_code == 201
    assert (await client.post(base, json={"kind": "edit", "body": "x"})).status_code == 422
    assert (await client.post(base, json={"kind": "comment", "body": ""})).status_code == 422
    notes = (await client.get(base)).json()
    kinds = ["contest", "accept_risk", "remediation_planned", "comment"]
    assert [n["kind"] for n in notes] == kinds
    assert notes[0]["actor"].startswith("client:")
    assert (await client.get("/v1/findings/nope/annotations")).status_code == 404
    # No edit routes exist for findings.
    assert (await client.patch(f"/v1/findings/{sealed['id']}", json={})).status_code in {404, 405}


async def test_status_events_supersede_and_current(client, internal):
    first = await _audit(client)
    old = await _seal(client, internal, first["id"])
    stale = await client.post(
        f"/internal/findings/{old['id']}/status-events",
        json={"status": "stale", "reason": "RC-1 changed Art. 10", "data": {"change_id": "RC-1"}},
        headers=internal,
    )
    assert stale.status_code == 201, stale.text
    current = (await client.get("/v1/systems/SYS-001/findings?current=true")).json()
    assert [(f["id"], f["status"], f["stale"]) for f in current] == [(old["id"], "stale", True)]

    second = await _audit(client)
    new = await _seal(client, internal, second["id"], verdict="pass", severity=None, gap_id=None)
    current = (await client.get("/v1/systems/SYS-001/findings?current=true")).json()
    assert [f["id"] for f in current] == [new["id"]]
    every = (await client.get("/v1/systems/SYS-001/findings")).json()
    old_out = next(f for f in every if f["id"] == old["id"])
    assert old_out["status"] == "superseded"
    assert old_out["status_events"][-1]["superseded_by"] == new["id"]
    assert (await client.get("/v1/systems/NOPE/findings")).status_code == 404


async def test_patch_on_finding_artifact_is_405(client):
    audit = await _audit(client)
    base = f"/v1/audits/{audit['id']}/artifacts"
    finding = (
        await client.post(base, json={"kind": "finding", "name": "F-01", "data": {"v": 1}})
    ).json()
    other = (await client.post(base, json={"kind": "scenarios", "data": {"v": 1}})).json()
    patched = await client.patch(f"{base}/{finding['id']}", json={"data": {"verdict": "pass"}})
    assert patched.status_code == 405
    stored = (await client.get(f"{base}/{finding['id']}")).json()
    assert stored["data"] == {"v": 1}
    ok = await client.patch(f"{base}/{other['id']}", json={"status": "approved"})
    assert ok.status_code == 200


async def test_pins_are_copied_from_data(client, internal):
    audit = await _audit(client)
    assert audit["pins"] is None
    pins = {"kb_version": "k1", "dossier_version": 3, "model_version": "4", "seeds": [7]}
    await client.patch(
        f"/internal/audits/{audit['id']}", json={"data": {"pins": pins}}, headers=internal
    )
    detail = (await client.get(f"/v1/audits/{audit['id']}")).json()
    assert detail["pins"] == pins
    listed = (await client.get("/v1/audits")).json()
    assert listed[0]["pins"] == pins


async def test_retry_forwards_to_the_agents_run(client, agents_service):
    audit = await _audit(client)
    url = f"/v1/audits/{audit['id']}/retry"
    await client.patch(f"/v1/audits/{audit['id']}", json={"status": "running"})
    assert (await client.post(url)).status_code == 409

    await client.patch(
        f"/v1/audits/{audit['id']}", json={"status": "failed", "data": {"error": "boom"}}
    )
    agents_service.on(
        "POST",
        f"/audits/{audit['id']}/run",
        httpx.Response(202, json={"audit_id": audit["id"], "thread_id": "t", "status": "resumed"}),
    )
    retried = await client.post(url)
    assert retried.status_code == 202, retried.text
    assert retried.json()["status"] == "running"
    call = agents_service.called("POST", f"/audits/{audit['id']}/run")[0]
    assert json.loads(call.content)["trigger"] == "retry"
    detail = (await client.get(f"/v1/audits/{audit['id']}")).json()
    assert detail["status"] == "running"
    assert "error" not in detail["data"]
    assert detail["data"]["retries"][0]["error"] == "boom"

    await client.patch(f"/v1/audits/{audit['id']}", json={"status": "failed"})
    agents_service.on("POST", f"/audits/{audit['id']}/run", httpx.Response(409, json={}))
    assert (await client.post(url)).status_code == 409


def test_migration_0006_is_in_the_single_chain():
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "core/database/migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0007_finding_register"]
    assert script.get_revision("0007_finding_register").down_revision == "0006_sealed_findings"
    source = Path(script.get_revision("0006_sealed_findings").path).read_text(encoding="utf-8")
    for needle in ("findings", "finding_annotations", "finding_status_events", "pins"):
        assert f'"{needle}"' in source
    assert "reject_append_only_change" in source
