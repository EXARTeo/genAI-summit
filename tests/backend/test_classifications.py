"""Risk classification, backend side (plan 02 §7): a run goes running → proposed / failed in
the background (the agents service is a MockTransport), a human approves (card + dossier
files updated, the earlier approval superseded) or rejects with a reason (fed to the next
run), the event log is append-only, an accepted regulation change marks an approved class
stale, and the obligations preview maps the card onto reg-memory's query."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import SERVICE_ROOT
from sqlalchemy import delete, update
from sqlalchemy.exc import DatabaseError
from test_regulation_change_flow import agents, reg_memory  # noqa: F401 - fixtures
from test_regulation_telegram import CHANGE, bot  # noqa: F401 - fixtures

import utils.classifications as classifications
from core.database import ClassificationEventTable, SystemClassificationTable

SYSTEM = "SYS-T01"
CARD = {
    "id": SYSTEM,
    "name": "CV Parser",
    "intended_purpose": "Turns CVs into structured fields for recruiters; no ranking.",
    "risk_class": "unclassified",
    "profiling": "no",
    "acquisition": "in_house",
    "features": [],
    "provenance": "declared_by_pm",
}


def result(**overrides: Any) -> dict[str, Any]:
    base = {
        "risk_class": "minimal_risk",
        "route": "art6_3_exempt",
        "annex_basis": "Annex III 4(a)",
        "annex_basis_id": "AIA.ANNEX_III.4.a",
        "role": "provider",
        "role_reasoning": "Built in-house (Art. 3(3)).",
        "art5_screening": [],
        "annex_iii_considered": [
            {"provision_id": "AIA.ANNEX_III.4.a", "applies": True, "why": "recruitment"}
        ],
        "art6_3": {
            "considered": True,
            "condition": "a",
            "profiling": "no",
            "holds": True,
            "why": "narrow procedural task",
        },
        "transparency": {"features": [], "provisions": []},
        "gpai": {"is_gpai_model": False, "built_on_gpai": False, "note": ""},
        "reasoning": "Structures CVs only.",
        "counter_arguments": [{"argument": "If it ranks", "would_change_to": "high_risk"}],
        "would_change_if": ["it filters or ranks candidates"],
        "uncertainties": [],
        "next_steps": ["Document the Art. 6(4) assessment"],
        "confidence": 0.8,
        "citations": [
            {"id": "AIA.6.3", "kb_version": "2026.11.15-1", "binding": True, "status": "final"},
            {
                "id": "INT.demo.2-employment",
                "kb_version": "2026.11.15-1",
                "binding": False,
                "status": "draft",
            },
        ],
        "kb_version": "2026.11.15-1",
        "key_dates": [],
        "iris": None,
        "needs_human": False,
        "needs_human_reasons": [],
        "verifier_problems": [],
        "trace_id": "trace-1",
    }
    return {**base, **overrides}


@pytest.fixture(autouse=True)
def _sessions(monkeypatch, session_factory):
    monkeypatch.setattr(classifications, "session_factory", session_factory)


async def _drain() -> None:
    await asyncio.gather(*list(classifications._classify_tasks), return_exceptions=True)


async def _system(client, card: dict[str, Any] | None = None) -> None:
    card = card or CARD
    created = await client.post(
        "/v1/systems",
        json={"id": SYSTEM, "name": "CV Parser", "status": "draft", "data": {"card": card}},
    )
    assert created.status_code == 201, created.text
    base = f"/v1/systems/{SYSTEM}/files"
    for path, content in (
        ("system-card.yaml", yaml.safe_dump(card)),
        ("docs/system-specification.md", "# Spec\nParses CVs into fields."),
        ("README.md", "Root notes."),
        ("plugins/parser/plugin.yaml", "name: parser"),
    ):
        put = await client.put(f"{base}/{path}", json={"content": content})
        assert put.status_code < 300, put.text
    pdf = await client.put(
        f"{base}/docs/brochure.pdf",
        files={"file": ("brochure.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert pdf.status_code < 300, pdf.text


async def _file(client, path: str) -> dict:
    return (await client.get(f"/v1/systems/{SYSTEM}/files/{path}?format=json")).json()


async def _run(client, agents_service, reply: Any, previous: str | None = None) -> dict:
    agents_service.on("POST", f"/systems/{SYSTEM}/classify", reply)
    body = {"previousId": previous} if previous else {}
    started = await client.post(f"/v1/systems/{SYSTEM}/classifications", json=body)
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "running"
    await _drain()
    return (await client.get(f"/v1/systems/{SYSTEM}/classifications/{started.json()['id']}")).json()


async def _proposed(client, agents_service, **overrides: Any) -> dict:
    return await _run(client, agents_service, httpx.Response(200, json=result(**overrides)))


async def test_a_run_sends_the_dossier_and_becomes_proposed(client, agents_service):
    await _system(client)
    row = await _proposed(client, agents_service)
    assert row["status"] == "proposed"
    assert row["id"].startswith(f"CLS-{SYSTEM}-")
    assert row["kbVersion"] == "2026.11.15-1" and row["traceId"] == "trace-1"
    assert row["result"]["route"] == "art6_3_exempt"
    assert [e["action"] for e in row["events"]] == ["created", "proposed"]
    assert row["dossierVersion"] == {
        "system-card.yaml": 1,
        "docs/system-specification.md": 1,
        "README.md": 1,
    }
    assert row["input"]["not_read"] == ["docs/brochure.pdf"]

    (call,) = agents_service.called("POST", f"/systems/{SYSTEM}/classify")
    sent = json.loads(call.content)
    assert sent["classification_id"] == row["id"]
    assert sent["kb_version"] is None and sent["feedback"] is None
    assert sent["trace"] == {"name": f"classify:{row['id']}"}
    assert sent["card"]["profiling"] == "no" and sent["card"]["id"] == SYSTEM
    assert {d["path"] for d in sent["documents"]} == {"docs/system-specification.md", "README.md"}
    assert all("text" in d and d["version"] == 1 for d in sent["documents"])

    listed = (await client.get(f"/v1/systems/{SYSTEM}/classifications")).json()
    assert [c["id"] for c in listed] == [row["id"]]


async def test_only_one_run_at_a_time(client, agents_service, monkeypatch):
    await _system(client)
    monkeypatch.setattr("router.classifications.start_classification", lambda *a: None)
    first = await client.post(f"/v1/systems/{SYSTEM}/classifications")
    assert first.status_code == 202, first.text
    second = await client.post(f"/v1/systems/{SYSTEM}/classifications", json={})
    assert second.status_code == 409
    assert (await client.post("/v1/systems/NOPE/classifications")).status_code == 404
    missing = await client.get(f"/v1/systems/{SYSTEM}/classifications/CLS-x")
    assert missing.status_code == 404


async def test_agents_errors_fail_the_run(client, agents_service):
    await _system(client)
    row = await _run(
        client, agents_service, httpx.Response(502, json={"detail": "reg-memory down"})
    )
    assert row["status"] == "failed" and row["result"] is None
    assert "502" in row["error"] and "reg-memory down" in row["error"]
    assert row["events"][-1]["action"] == "failed"
    # a malformed answer fails too; a new run is allowed after a failure
    row = await _run(client, agents_service, httpx.Response(200, json={"risk_class": "weird"}))
    assert row["status"] == "failed"


async def test_approve_updates_the_card_and_supersedes(client, agents_service):
    await _system(client)
    first = await _proposed(client, agents_service)
    approved = await client.post(
        f"/v1/systems/{SYSTEM}/classifications/{first['id']}/decision",
        json={"decision": "approve"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    card_file = await _file(client, "system-card.yaml")
    assert card_file["version"] == 2
    card = yaml.safe_load(card_file["text"])
    assert card["risk_class"] == "minimal_risk"
    assert card["annex_basis"] == "Annex III 4(a)"
    assert card["role"] == "provider" and card["features"] == []
    assert card["art_6_3_claim"] == {"claimed": True, "condition": "a", "assessed_in": first["id"]}
    assert card["classification"]["id"] == first["id"]
    assert card["classification"]["kb_version"] == "2026.11.15-1"
    assert card["classification"]["approved_by"].startswith("client:")
    assert card["provenance"] == "classified_by_agent_approved_by_human"
    assert card["intended_purpose"] == CARD["intended_purpose"]  # the rest is kept
    record = yaml.safe_load((await _file(client, "classification.yaml"))["text"])
    assert record["id"] == first["id"] and record["result"]["route"] == "art6_3_exempt"
    system = (await client.get(f"/v1/systems/{SYSTEM}")).json()
    assert system["status"] == "active"
    assert system["data"]["card"]["risk_class"] == "minimal_risk"

    again = await client.post(
        f"/v1/systems/{SYSTEM}/classifications/{first['id']}/decision",
        json={"decision": "approve"},
    )
    assert again.status_code == 409

    second = await _proposed(
        client,
        agents_service,
        risk_class="high_risk",
        route="art6_2_annex_iii",
        art6_3={"considered": True, "condition": None, "profiling": "yes", "holds": False},
    )
    ok = await client.post(
        f"/v1/systems/{SYSTEM}/classifications/{second['id']}/decision",
        json={"decision": "approve", "reason": "ranks too"},
    )
    assert ok.status_code == 200, ok.text
    old = (await client.get(f"/v1/systems/{SYSTEM}/classifications/{first['id']}")).json()
    assert old["status"] == "superseded"
    assert old["events"][-1]["data"] == {"superseded_by": second["id"]}
    card = yaml.safe_load((await _file(client, "system-card.yaml"))["text"])
    assert card["risk_class"] == "high_risk" and card["art_6_3_claim"]["claimed"] is False


async def test_reject_needs_a_reason_and_feeds_the_next_run(client, agents_service):
    await _system(client)
    row = await _proposed(client, agents_service)
    url = f"/v1/systems/{SYSTEM}/classifications/{row['id']}/decision"
    assert (await client.post(url, json={"decision": "reject"})).status_code == 422
    assert (await client.post(url, json={"decision": "reject", "reason": "  "})).status_code == 422
    long = "x" * 2001
    assert (await client.post(url, json={"decision": "reject", "reason": long})).status_code == 422
    rejected = await client.post(
        url, json={"decision": "reject", "reason": "It also ranks candidates, see spec §3"}
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == "rejected"
    assert body["events"][-1]["reason"] == "It also ranks candidates, see spec §3"
    assert (await client.post(url, json={"decision": "approve"})).status_code == 409
    card = await _file(client, "system-card.yaml")
    assert card["version"] == 1  # a rejection does not touch the card

    agents_service.calls.clear()
    rerun = await _run(
        client, agents_service, httpx.Response(200, json=result()), previous=row["id"]
    )
    assert rerun["previousId"] == row["id"]
    (call,) = agents_service.called("POST", f"/systems/{SYSTEM}/classify")
    assert json.loads(call.content)["feedback"] == {
        "source": "human",
        "reason": "It also ranks candidates, see spec §3",
    }
    bad = await client.post(
        f"/v1/systems/{SYSTEM}/classifications", json={"previousId": "CLS-unknown"}
    )
    assert bad.status_code == 404


async def test_events_are_append_only(client, agents_service, session_factory):
    await _system(client)
    row = await _proposed(client, agents_service)
    for statement in (
        update(ClassificationEventTable).values(reason="edited"),
        delete(ClassificationEventTable).where(
            ClassificationEventTable.classification_id == row["id"]
        ),
    ):
        async with session_factory() as session:
            with pytest.raises(DatabaseError, match="append-only"):
                await session.execute(statement)
                await session.commit()


async def test_the_result_is_written_once(client, agents_service, session_factory):
    await _system(client)
    row = await _proposed(client, agents_service)
    async with session_factory() as session:
        stored = await session.get(SystemClassificationTable, row["id"])
        with pytest.raises(ValueError, match="already has a result"):
            classifications.store_result(stored, result())


async def test_mark_stale_touches_only_relied_on_provisions(
    client, agents_service, session_factory
):
    await _system(client)
    row = await _proposed(client, agents_service)
    await client.post(
        f"/v1/systems/{SYSTEM}/classifications/{row['id']}/decision", json={"decision": "approve"}
    )
    async with session_factory() as session:
        untouched = {"id": "RC-1", "provisions": [{"id": "AIA.10.2", "relates_to": ["AIA.10"]}]}
        assert await classifications.mark_stale_for_change(session, untouched) == []
        touched = {"id": "RC-2", "interpretations": [{"id": "INT.x", "relates_to": ["AIA.6.3"]}]}
        assert await classifications.mark_stale_for_change(session, touched, "client:x") == [
            row["id"]
        ]
        await session.commit()
    stale = (await client.get(f"/v1/systems/{SYSTEM}/classifications/{row['id']}")).json()
    assert stale["status"] == "stale"
    event = stale["events"][-1]
    assert event["action"] == "stale" and event["data"]["change_id"] == "RC-2"
    assert "AIA.6" in event["data"]["provisions"]
    # the approved card stays in force
    card = (await client.get(f"/v1/systems/{SYSTEM}")).json()["data"]["card"]
    assert card["risk_class"] == "minimal_risk"


async def test_accepting_a_change_marks_the_classification_stale(
    client,
    reg_memory,  # noqa: F811
    agents,  # noqa: F811
    bot,  # noqa: F811
    monkeypatch,
):
    await _system(client)
    replies = httpx.MockTransport(lambda request: httpx.Response(200, json=result()))
    monkeypatch.setattr(classifications, "agents_transport", replies)
    started = await client.post(f"/v1/systems/{SYSTEM}/classifications")
    await _drain()
    cid = started.json()["id"]
    await client.post(
        f"/v1/systems/{SYSTEM}/classifications/{cid}/decision", json={"decision": "approve"}
    )
    accepted = await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/decision", json={"status": "accepted"}
    )
    assert accepted.status_code == 200, accepted.text
    row = (await client.get(f"/v1/systems/{SYSTEM}/classifications/{cid}")).json()
    assert row["status"] == "stale"
    assert row["events"][-1]["data"]["provisions"] == ["INT.demo.2-employment"]


async def test_obligations_preview_maps_the_card(client, agents_service):
    await _system(client)
    preview = (await client.get(f"/v1/systems/{SYSTEM}/obligations")).json()
    assert preview["classified"] is False and preview["items"] == []

    row = await _proposed(client, agents_service)
    await client.post(
        f"/v1/systems/{SYSTEM}/classifications/{row['id']}/decision", json={"decision": "approve"}
    )
    items = [{"id": "OBL.AIA.6.4.non-high-risk-assessment", "applicable": True}]
    agents_service.on(
        "GET",
        "/v1/obligations",
        httpx.Response(200, json={"kb_version": "2026.11.15-1", "total": 1, "items": items}),
    )
    got = await client.get(f"/v1/systems/{SYSTEM}/obligations", params={"date": "2027-12-02"})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["classificationId"] == row["id"] and body["kb_version"] == "2026.11.15-1"
    assert body["items"] == items and body["total"] == 1 and body["prohibited"] is False
    (call,) = agents_service.called("GET", "/v1/obligations")
    params = call.url.params
    assert params["risk_class"] == "minimal" and params["role"] == "provider"
    assert params["basis"] == "annex_iii" and params["annex_point"] == "4.a"
    assert params["exempt_6_3"] == "true" and params["include_not_applicable"] == "true"
    assert params["kb_version"] == "2026.11.15-1" and params["date"] == "2027-12-02"


async def test_obligation_query_for_high_risk_and_prohibited(client, agents_service):
    query = classifications.obligation_query(
        {"role": "Provider", "risk_class": "high_risk", "annex_basis": "Annex III 5(b)"}
    )
    assert query == {
        "role": "provider",
        "risk_class": "high",
        "basis": "annex_iii",
        "annex_point": "5.b",
        "features": None,
        "exempt_6_3": False,
    }
    await _system(client, {**CARD, "risk_class": "prohibited"})
    agents_service.on(
        "GET",
        "/v1/obligations",
        httpx.Response(
            200,
            json={
                "kb_version": "k",
                "items": [{"id": "OBL.AIA.5.prohibited-practices-screening"}, {"id": "OBL.AIA.4"}],
            },
        ),
    )
    body = (await client.get(f"/v1/systems/{SYSTEM}/obligations")).json()
    assert body["prohibited"] is True
    assert [i["id"] for i in body["items"]] == ["OBL.AIA.5.prohibited-practices-screening"]


def test_migration_0008_follows_0007():
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "core/database/migrations"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("0008_system_classifications")
    assert revision.down_revision == "0007_finding_register"
    assert script.get_current_head() == "0008_system_classifications"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "trg_classification_events_no_" in source
