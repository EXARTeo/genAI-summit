"""Findings register: transition rules, the done hook, close / reopen, rebuild, internal read."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from core.settings import settings
from utils.register import transition

OBL = "OBL.AIA.10.2.f"


@pytest.fixture
def internal(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr("s3cret"))
    return {"X-Internal-Secret": "s3cret", "X-Agent-Name": "seal"}


@pytest.mark.parametrize(
    ("state", "verdict", "gap_id", "kw", "expected"),
    [
        (None, "gap", "G-1", {}, ("open", "opened")),
        (None, "inconclusive", None, {}, ("open", "opened")),
        (None, "pass", None, {}, ("monitoring", "first_seen")),
        (None, "not_assessable_by_testing", None, {}, ("monitoring", "first_seen")),
        (None, "not_assessable_by_testing", "G-2", {}, ("open", "opened")),
        ("open", "gap", "G-1", {"previous_verdict": "gap"}, ("open", "still_open")),
        ("open", "partial", "G-1", {"previous_verdict": "gap"}, ("open", "verdict_changed")),
        ("open", "pass", None, {"previous_verdict": "gap"}, ("resolved", "resolved")),
        ("open", "not_applicable", None, {"previous_verdict": "gap"}, ("open", "verdict_changed")),
        ("resolved", "gap", "G-1", {"ever_open": True}, ("open", "regressed")),
        ("monitoring", "gap", "G-1", {}, ("open", "opened")),
        ("monitoring", "pass", None, {}, ("monitoring", "checked")),
        ("closed", "partial", "G-1", {"closed_verdict": "partial"}, ("closed", "still_open")),
        ("closed", "inconclusive", None, {"closed_verdict": "partial"}, ("closed", "still_open")),
        ("closed", "gap", "G-1", {"closed_verdict": "partial"}, ("open", "reopened")),
        ("closed", "pass", None, {"closed_verdict": "gap"}, ("resolved", "resolved")),
    ],
)
def test_transition_rules(state, verdict, gap_id, kw, expected):
    assert transition(state, verdict, gap_id, **kw) == expected


async def _system(client, sid: str = "SYS-001") -> None:
    if (await client.get(f"/v1/systems/{sid}")).status_code == 404:
        assert (await client.post("/v1/systems", json={"id": sid, "name": "CV"})).status_code == 201


async def _audit_with(client, internal, verdicts: dict[str, str], *, finish: bool = True) -> str:
    """An audit that seals one finding per obligation, then (optionally) finishes."""
    await _system(client)
    created = await client.post("/v1/systems/SYS-001/audits", json={"data": {"autostart": False}})
    assert created.status_code == 201, created.text
    audit_id = created.json()["id"]
    for obligation, verdict in verdicts.items():
        body = {
            "obligation_id": obligation,
            "verdict": verdict,
            "severity": "high" if verdict in {"gap", "partial"} else None,
            "gap_id": "G-1" if verdict in {"gap", "partial"} else None,
            "reasoning": f"{verdict} in {audit_id}",
            "article": "Art. 10(2)(f)",
            "title": "Bias examination",
        }
        r = await client.post(f"/internal/audits/{audit_id}/findings", json=body, headers=internal)
        assert r.status_code == 201, r.text
    if finish:
        r = await client.patch(
            f"/internal/audits/{audit_id}", json={"status": "done"}, headers=internal
        )
        assert r.status_code == 200, r.text
    return audit_id


async def _item(client, obligation: str = OBL) -> dict:
    r = await client.get(f"/v1/systems/SYS-001/register/{obligation}")
    assert r.status_code == 200, r.text
    return r.json()


async def test_done_audit_opens_then_resolves(client, internal):
    first = await _audit_with(client, internal, {OBL: "gap", "OBL.AIA.15.1": "pass"})
    reg = (await client.get("/v1/systems/SYS-001/register")).json()
    assert reg["summary"]["open_gaps"] == 1 and reg["summary"]["monitoring"] == 1
    item = next(i for i in reg["items"] if i["obligation_id"] == OBL)
    assert item["state"] == "open" and item["first_seen_audit_id"] == first
    assert item["article"] == "Art. 10(2)(f)" and item["last_status"] == "new"

    # Finishing again (a second PATCH to done) changes nothing.
    await client.patch(f"/internal/audits/{first}", json={"status": "done"}, headers=internal)
    assert len((await _item(client))["history"]) == 1

    second = await _audit_with(client, internal, {OBL: "gap"})
    item = await _item(client)
    assert item["state"] == "open" and item["last_status"] == "still_open"
    assert [e["kind"] for e in item["history"]] == ["opened", "still_open"]

    third = await _audit_with(client, internal, {OBL: "pass"})
    item = await _item(client)
    assert item["state"] == "resolved" and item["closed_by"] == f"audit:{third}"
    assert item["last_seen_audit_id"] == third and item["first_seen_audit_id"] == first
    assert second != third


async def test_running_audit_does_not_touch_register(client, internal):
    await _audit_with(client, internal, {OBL: "gap"}, finish=False)
    reg = (await client.get("/v1/systems/SYS-001/register")).json()
    assert reg["items"] == []


async def test_close_needs_reason_and_survives_same_verdict(client, internal):
    await _audit_with(client, internal, {OBL: "partial"})
    url = f"/v1/systems/SYS-001/register/{OBL}"
    assert (await client.post(f"{url}/close", json={"reason": ""})).status_code == 422
    assert (await client.post(f"{url}/close", json={"reason": "   "})).status_code == 422
    closed = await client.post(f"{url}/close", json={"reason": "Accepted by the DPO."})
    assert closed.status_code == 200, closed.text
    assert (
        closed.json()["state"] == "closed"
        and closed.json()["close_reason"] == "Accepted by the DPO."
    )
    assert closed.json()["closed_by"].startswith("client:")
    assert (await client.post(f"{url}/close", json={"reason": "again"})).status_code == 409

    await _audit_with(client, internal, {OBL: "partial"})
    item = await _item(client)
    assert item["state"] == "closed" and item["last_status"] == "accepted_risk"

    await _audit_with(client, internal, {OBL: "gap"})
    item = await _item(client)
    assert item["state"] == "open" and item["last_status"] == "regressed"
    assert item["history"][-1]["kind"] == "reopened"


async def test_reopen_and_unknown(client, internal):
    await _audit_with(client, internal, {OBL: "gap"})
    url = f"/v1/systems/SYS-001/register/{OBL}"
    assert (await client.post(f"{url}/reopen", json={})).status_code == 409
    await client.post(f"{url}/close", json={"reason": "Mitigated by a human review step."})
    reopened = await client.post(f"{url}/reopen", json={"reason": "Review step removed."})
    assert reopened.status_code == 200 and reopened.json()["state"] == "open"
    assert reopened.json()["history"][-1]["note"] == "Review step removed."
    assert (await client.get("/v1/systems/SYS-001/register/NOPE")).status_code == 404
    assert (await client.get("/v1/systems/SYS-404/register")).status_code == 404


async def test_rebuild_replays_oldest_first(client, internal):
    await _audit_with(client, internal, {OBL: "gap"})
    await _audit_with(client, internal, {OBL: "pass"})
    reset = await client.post("/v1/admin/rebuild-register?reset=true")
    assert reset.status_code == 200, reset.text
    assert len(reset.json()["audits_applied"]) == 2 and reset.json()["items"] == 1
    item = await _item(client)
    assert item["state"] == "resolved"
    assert [e["kind"] for e in item["history"]] == ["opened", "resolved"]
    again = await client.post("/v1/admin/rebuild-register")
    assert again.json()["audits_applied"] == []


async def test_internal_register_read(client, internal):
    audit_id = await _audit_with(client, internal, {OBL: "gap"})
    url = f"/internal/audits/{audit_id}/register"
    assert (await client.get(url)).status_code == 401
    body = (await client.get(url, headers=internal)).json()
    assert body["system_id"] == "SYS-001" and body["items"][0]["obligation_id"] == OBL
