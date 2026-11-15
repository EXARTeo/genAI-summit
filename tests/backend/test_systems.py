"""Systems, versioned workspace files (system folders), the seed import,
audits / artifacts / approvals, the internal API and migrations 0003 / 0004."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import AGENT_SLUG, CLIENT_ID
from pydantic import SecretStr
from sqlalchemy import select

from core.database import (
    AttachmentTable,
    AuditTable,
    BlobTable,
    ConversationTable,
    MessageTable,
    SystemTable,
    WorkspaceEventTable,
    WorkspaceFileTable,
)
from core.settings import settings
from schema.audits import AuditIn
from utils.audits import create_audit

SERVICE_ROOT = Path(__file__).resolve().parents[2] / "mnamon" / "backend"


async def _system(client, sid: str = "SYS-001", name: str = "CV screener") -> dict:
    response = await client.post("/v1/systems", json={"id": sid, "name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def _put(client, path: str, content: str, base: str = "/v1/systems/SYS-001", **extra):
    return await client.put(f"{base}/files/{path}", json={"content": content, **extra})


# --- systems ------------------------------------------------------------------


async def test_system_crud_and_not_scoped_by_client(client, other_client):
    created = await _system(client)
    assert created["status"] == "active"
    assert (
        await client.post("/v1/systems", json={"id": "SYS-001", "name": "x"})
    ).status_code == 409
    assert (await client.post("/v1/systems", json={"id": "../x", "name": "x"})).status_code == 422

    patched = await client.patch(
        "/v1/systems/SYS-001", json={"status": "draft", "data": {"risk": "high"}}
    )
    assert patched.json()["status"] == "draft"
    assert patched.json()["data"] == {"risk": "high"}
    await client.patch("/v1/systems/SYS-001", json={"data": {"sector": "hiring"}})

    # Ownership does not matter (for now): another browser sees the system.
    other = await other_client.get("/v1/systems/SYS-001")
    assert other.status_code == 200
    assert other.json()["data"] == {"risk": "high", "sector": "hiring"}
    assert [s["id"] for s in (await other_client.get("/v1/systems")).json()] == ["SYS-001"]
    assert (await client.get("/v1/systems/SYS-404")).status_code == 404


# --- files --------------------------------------------------------------------


async def test_files_are_versioned_and_idempotent(client):
    await _system(client)
    first = await _put(client, "plugins/ranker/plugin.yaml", "id: a\n", reason="initial")
    assert first.status_code == 201
    assert first.json()["file"]["version"] == 1
    assert first.json()["file"]["contentType"] == "application/yaml"

    same = await _put(client, "plugins/ranker/plugin.yaml", "id: a\n")
    assert same.status_code == 200
    assert same.json() == {**same.json(), "changed": False}
    assert same.json()["file"]["version"] == 1

    second = await _put(client, "plugins/ranker/plugin.yaml", "id: b\n")
    assert second.json()["file"]["version"] == 2
    await _put(client, "system-card.yaml", "name: CV screener\n")

    tree = (await client.get("/v1/systems/SYS-001/files")).json()
    assert [(f["path"], f["version"]) for f in tree] == [
        ("plugins/ranker/plugin.yaml", 2),
        ("system-card.yaml", 1),
    ]
    under = (await client.get("/v1/systems/SYS-001/files", params={"prefix": "plugins"})).json()
    assert [f["path"] for f in under] == ["plugins/ranker/plugin.yaml"]

    raw = await client.get("/v1/systems/SYS-001/files/plugins/ranker/plugin.yaml")
    assert raw.content == b"id: b\n"
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert raw.headers["x-file-version"] == "2"
    old = await client.get(
        "/v1/systems/SYS-001/files/plugins/ranker/plugin.yaml",
        params={"version": 1, "format": "json"},
    )
    assert old.json()["text"] == "id: a\n"
    assert old.json()["isCurrent"] is False

    versions = (
        await client.get("/v1/systems/SYS-001/files/plugins/ranker/plugin.yaml/versions")
    ).json()
    assert [v["version"] for v in versions] == [2, 1]

    events = (await client.get("/v1/systems/SYS-001/events")).json()
    assert [e["action"] for e in events] == ["create", "update", "create"]
    assert events[-1]["reason"] == "initial"
    assert events[-1]["actor"] == f"client:{CLIENT_ID}"


async def test_delete_keeps_history_and_rewrite_continues_numbering(client):
    await _system(client)
    await _put(client, "docs/a.md", "one")
    deleted = await client.delete("/v1/systems/SYS-001/files/docs/a.md", params={"reason": "old"})
    assert deleted.status_code == 204
    assert (await client.get("/v1/systems/SYS-001/files/docs/a.md")).status_code == 404
    assert (await client.get("/v1/systems/SYS-001/files")).json() == []
    assert (await client.delete("/v1/systems/SYS-001/files/docs/a.md")).status_code == 404
    again = await _put(client, "docs/a.md", "one")
    assert again.json()["file"]["version"] == 2


async def test_multipart_upload_and_path_safety(client):
    await _system(client)
    upload = await client.put(
        "/v1/systems/SYS-001/files/docs/sample.csv",
        files={"file": ("sample.csv", b"a,b\n1,2\n", "text/csv")},
        data={"reason": "sample"},
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["file"]["contentType"] == "text/csv"
    assert upload.json()["file"]["size"] == 8

    for bad in ("../etc/passwd", "a/../../b", "a//b"):
        response = await _put(client, bad, "x")
        assert response.status_code in {400, 404}, bad
    assert (await _put(client, "x.md", "x", base="/v1/systems/SYS-404")).status_code == 404


async def test_memory_routes_are_gone(client):
    """Agent memory moved to the agents service: the backend serves no memory."""
    await _system(client)
    for path in (
        "/v1/memory/org/files",
        "/v1/memory/proposals/files",
        "/v1/memory/systems/SYS-001/files",
    ):
        assert (await client.get(path)).status_code == 404, path


async def test_copy_attachment_into_a_system_folder(client, other_client, session_factory):
    await _system(client)
    async with session_factory() as session:
        conversation = ConversationTable(client_id=CLIENT_ID, agent_slug=AGENT_SLUG, title="t")
        session.add(conversation)
        await session.flush()
        message = MessageTable(conversation_id=conversation.id, sender="user", content="f")
        session.add(message)
        await session.flush()
        attachment = AttachmentTable(
            message_id=message.id,
            file_name="model card.pdf",
            mime_type="application/pdf",
            size_bytes=4,
            blob=BlobTable(data=b"%PDF"),
        )
        session.add(attachment)
        await session.commit()
        attachment_id = attachment.id

    copied = await client.post(
        "/v1/systems/SYS-001/files/from-attachment", json={"attachmentId": attachment_id}
    )
    assert copied.status_code == 201, copied.text
    assert copied.json()["file"]["path"] == "uploads/model_card.pdf"
    assert copied.json()["file"]["contentType"] == "application/pdf"
    raw = await client.get("/v1/systems/SYS-001/files/uploads/model_card.pdf")
    assert raw.content == b"%PDF"
    assert raw.headers["content-disposition"].startswith("attachment")

    # The attachment must belong to the caller.
    stolen = await other_client.post(
        "/v1/systems/SYS-001/files/from-attachment",
        json={"attachmentId": attachment_id, "path": "x.pdf"},
    )
    assert stolen.status_code == 404


# --- seed import --------------------------------------------------------------


async def test_import_seed_is_idempotent_and_skips_the_answer_key(client, tmp_path, monkeypatch):
    case = tmp_path / "SYS-007"
    (case / "docs").mkdir(parents=True)
    (case / "plugins" / "ranker").mkdir(parents=True)
    (case / "_answer-key").mkdir()
    (case / "system-card.yaml").write_text("name: Loan scorer\nrisk: high\n", encoding="utf-8")
    (case / "docs" / "spec.md").write_text("# Spec", encoding="utf-8")
    (case / "plugins" / "ranker" / "plugin.yaml").write_text("id: SYS-007.ranker\n")
    (case / "_answer-key" / "expected-findings.yaml").write_text("secret: true\n")
    (tmp_path / "_shared").mkdir()
    monkeypatch.setattr(settings.workspace, "seed_cases_dir", str(tmp_path))

    first = await client.post("/v1/admin/import-seed")
    assert first.status_code == 200, first.text
    assert first.json()["systems"] == [
        {"id": "SYS-007", "created": True, "filesWritten": 3, "filesUnchanged": 0}
    ]
    assert first.json()["skippedDirs"] == ["_shared"]
    system = (await client.get("/v1/systems/SYS-007")).json()
    assert system["name"] == "Loan scorer"
    assert system["data"]["card"]["risk"] == "high"
    paths = [f["path"] for f in (await client.get("/v1/systems/SYS-007/files")).json()]
    assert paths == ["docs/spec.md", "plugins/ranker/plugin.yaml", "system-card.yaml"]

    (case / "docs" / "spec.md").write_text("# Spec v2", encoding="utf-8")
    second = (await client.post("/v1/admin/import-seed")).json()
    assert second["systems"] == [
        {"id": "SYS-007", "created": False, "filesWritten": 1, "filesUnchanged": 2}
    ]


async def test_import_seed_missing_dir_is_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings.workspace, "seed_cases_dir", str(tmp_path / "nope"))
    assert (await client.post("/v1/admin/import-seed")).status_code == 404


# --- audits -------------------------------------------------------------------


async def _audit(client) -> dict:
    await _system(client)
    await _put(client, "plugins/ranker/plugin.yaml", "id: SYS-001.ranker\n")
    response = await client.post("/v1/systems/SYS-001/audits", json={"data": {"kb_version": "k1"}})
    assert response.status_code == 201, response.text
    return response.json()


async def test_audit_ids_are_readable_and_never_collide(client, session_factory):
    audit = await _audit(client)
    assert re.fullmatch(r"SYS-001-\d{8}-\d{4}(-\d+)?", audit["id"]), audit["id"]
    assert (await client.get(f"/v1/audits/{audit['id']}")).status_code == 200
    now = datetime(2026, 11, 15, 9, 30, tzinfo=UTC)
    async with session_factory() as db:
        system = await db.get(SystemTable, "SYS-001")
        ids = [(await create_audit(db, system, AuditIn(), "test", now=now)).id for _ in range(3)]
        await db.commit()
    assert ids == ["SYS-001-20261115-0930", "SYS-001-20261115-0930-2", "SYS-001-20261115-0930-3"]


async def test_an_old_uuid_audit_still_works(client, session_factory):
    await _system(client)
    async with session_factory() as db:
        db.add(AuditTable(id="0b9f6c1e-2d4a-4c1b-9a51-3f0e8d7c6b5a", system_id="SYS-001"))
        await db.commit()
    got = await client.get("/v1/audits/0b9f6c1e-2d4a-4c1b-9a51-3f0e8d7c6b5a")
    assert got.status_code == 200 and got.json()["systemId"] == "SYS-001"


async def test_audit_locks_the_dossier_and_lists(client):
    audit = await _audit(client)
    assert audit["stage"] == "context"
    assert audit["data"]["kb_version"] == "k1"
    assert len(audit["data"]["dossier_version"]) == 16
    assert audit["data"]["plugin_ids"] == ["SYS-001.ranker"]

    # The folder changes → a new audit locks a different dossier version.
    await _put(client, "docs/new.md", "x")
    later = (await client.post("/v1/systems/SYS-001/audits", json={})).json()
    assert later["data"]["dossier_version"] != audit["data"]["dossier_version"]

    listed = (await client.get("/v1/audits", params={"systemId": "SYS-001"})).json()
    assert {a["id"] for a in listed} == {audit["id"], later["id"]}
    patched = await client.patch(
        f"/v1/audits/{audit['id']}", json={"stage": "model_profile", "status": "running"}
    )
    assert patched.json()["stage"] == "model_profile"
    assert (await client.get("/v1/audits/nope")).status_code == 404
    assert (await client.post("/v1/systems/SYS-404/audits", json={})).status_code == 404


async def test_artifact_versions_supersede_and_approvals(client, session_factory):
    audit = await _audit(client)
    base = f"/v1/audits/{audit['id']}"
    v1 = (
        await client.post(f"{base}/artifacts", json={"kind": "scenarios", "data": {"n": 1}})
    ).json()
    v2 = (
        await client.post(
            f"{base}/artifacts",
            json={"kind": "scenarios", "data": {"n": 2}, "parentId": v1["id"]},
        )
    ).json()
    assert (v1["version"], v2["version"]) == (1, 2)
    finding = (
        await client.post(f"{base}/artifacts", json={"kind": "finding", "name": "F-1"})
    ).json()
    assert finding["version"] == 1

    assert (await client.get(f"{base}/artifacts/{v1['id']}")).json()["status"] == "superseded"
    live = (await client.get(f"{base}/artifacts", params={"liveOnly": True})).json()
    assert {a["id"] for a in live} == {v2["id"], finding["id"]}

    rejected = await client.post(
        f"{base}/approvals",
        json={
            "gate": "scenario_review",
            "decision": "rejected",
            "artifactId": v2["id"],
            "reasonCategory": "unrealistic_data",
            "comment": "Ages must be 18-67",
            "edits": {"age.range": [18, 67]},
        },
    )
    assert rejected.status_code == 201, rejected.text
    body = rejected.json()
    assert body["artifact"]["status"] == "rejected"
    assert body["approval"]["decidedBy"] == f"client:{CLIENT_ID}"
    assert body["approval"]["reasonCategory"] == "unrealistic_data"
    assert body["approval"]["comment"] == "Ages must be 18-67"
    assert "memoryProposalPath" not in body
    # A rejection only records the reason: no memory file is written.
    async with session_factory() as session:
        namespaces = set(await session.scalars(select(WorkspaceFileTable.namespace)))
    assert not any(ns.startswith("memory:") for ns in namespaces)

    approved = (
        await client.post(
            f"{base}/approvals",
            json={"gate": "finding_review", "decision": "approved", "artifactId": finding["id"]},
        )
    ).json()
    assert approved["artifact"]["status"] == "approved"

    detail = (await client.get(base)).json()
    assert len(detail["artifacts"]) == 3
    assert [a["decision"] for a in detail["approvals"]] == ["rejected", "approved"]
    assert (
        await client.post(f"{base}/approvals", json={"gate": "g", "decision": "maybe"})
    ).status_code == 422
    assert (
        await client.post(
            f"{base}/approvals", json={"gate": "g", "decision": "approved", "artifactId": "nope"}
        )
    ).status_code == 404
    # Findings are sealed: no PATCH (test_findings.py).
    patched = await client.patch(
        f"{base}/artifacts/{finding['id']}", json={"data": {"severity": "high"}}
    )
    assert patched.status_code == 405


async def test_conversation_can_name_a_system_and_audit(client):
    audit = await _audit(client)
    response = await client.post(
        "/v1/conversations",
        json={
            "agentSlug": AGENT_SLUG,
            "systemId": "SYS-001",
            "auditId": audit["id"],
            "firstMessage": {"sender": "user", "content": "hi"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["summary"]["systemId"] == "SYS-001"
    assert response.json()["summary"]["auditId"] == audit["id"]
    missing = await client.post(
        "/v1/conversations",
        json={
            "agentSlug": AGENT_SLUG,
            "systemId": "SYS-404",
            "firstMessage": {"sender": "user", "content": "hi"},
        },
    )
    assert missing.status_code == 404


# --- internal API -------------------------------------------------------------


@pytest.fixture
def internal_secret(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr("s3cret"))
    return {"X-Internal-Secret": "s3cret"}


async def test_internal_api_needs_the_secret(client, internal_secret):
    audit = await _audit(client)
    assert (await client.get(f"/internal/audits/{audit['id']}")).status_code == 401
    wrong = await client.get(f"/internal/audits/{audit['id']}", headers={"X-Internal-Secret": "x"})
    assert wrong.status_code == 401
    ok = await client.get(f"/internal/audits/{audit['id']}", headers=internal_secret)
    assert ok.status_code == 200
    assert ok.json()["system"]["id"] == "SYS-001"


async def test_internal_reads_are_logged_and_scoped(client, internal_secret, session_factory):
    audit = await _audit(client)
    await _system(client, "SYS-002", "Other")
    await _put(client, "secret.md", "other system", base="/v1/systems/SYS-002")
    base = f"/internal/audits/{audit['id']}"
    headers = {**internal_secret, "X-Run-Id": "run-1", "X-Trace-Id": "trace-1"}

    tree = (await client.get(f"{base}/files", headers=headers)).json()
    assert [f["path"] for f in tree] == ["plugins/ranker/plugin.yaml"]
    read = await client.get(f"{base}/files/plugins/ranker/plugin.yaml", headers=headers)
    assert read.json()["text"] == "id: SYS-001.ranker\n"
    # Another system's file is not reachable through this audit.
    assert (await client.get(f"{base}/files/secret.md", headers=headers)).status_code == 404

    async with session_factory() as session:
        reads = (
            await session.scalars(
                select(WorkspaceEventTable).where(WorkspaceEventTable.action == "read")
            )
        ).all()
    assert {(r.namespace, r.path, r.run_id, r.trace_id, r.audit_id) for r in reads} == {
        ("system:SYS-001", "plugins/ranker/plugin.yaml", "run-1", "trace-1", audit["id"]),
    }


async def test_internal_writes_artifacts_only(client, internal_secret):
    audit = await _audit(client)
    base = f"/internal/audits/{audit['id']}"
    headers = {**internal_secret, "X-Agent-Name": "profiler"}
    artifact = await client.post(
        f"{base}/artifacts",
        json={"kind": "model_profile", "data": {"inputs": 12}, "fileRefs": ["mlflow://x"]},
        headers=headers,
    )
    assert artifact.status_code == 201, artifact.text
    assert artifact.json()["createdBy"] == "agent:profiler"
    stage = await client.patch(base, json={"stage": "scenarios"}, headers=headers)
    assert stage.json()["stage"] == "scenarios"

    # Memory proposals are gone (memory lives in the agents service).
    proposal = await client.post(
        f"{base}/memory-proposals", json={"content": "kind: quirk"}, headers=headers
    )
    assert proposal.status_code in {404, 405}
    # No internal route writes the system folder.
    put = await client.put(f"{base}/files/x.md", json={"content": "x"}, headers=headers)
    assert put.status_code == 405


# --- migration ----------------------------------------------------------------


def test_migration_chain_up_to_0005():
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "core/database/migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision("0006_sealed_findings").down_revision == "0005_regulation_telegram"
    assert script.get_revision("0005_regulation_telegram").down_revision == (
        "0004_drop_memory_namespaces"
    )
    head = script.get_revision("0004_drop_memory_namespaces")
    assert head.down_revision == "0003_systems_audits"
    assert "memory:%" in Path(head.path).read_text(encoding="utf-8")
    revision = script.get_revision("0003_systems_audits")
    assert revision.down_revision == "0002_async_tasks"
    source = Path(revision.path).read_text(encoding="utf-8")
    for table in (
        "systems",
        "workspace_file_blobs",
        "workspace_files",
        "workspace_events",
        "audits",
        "audit_artifacts",
        "approvals",
    ):
        assert f'"{table}"' in source
