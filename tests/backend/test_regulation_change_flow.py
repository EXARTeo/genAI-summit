"""Regulation change, backend side (plan 01 §9): accept starts the agents' change judge in
the background with every system's card, the inbox ``judge`` flag follows it (also when no
system is affected), and the demo mirror proxy ("Simulate change" + "Check now")."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from test_regulation_telegram import CHANGE, FakeRegMemory, bot  # noqa: F401 - fixtures

import utils.regulation as regulation
from core.settings import settings


class FakeAgents:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path, json.loads(request.content or b"{}")))
        return httpx.Response(self.status, json={"change_id": CHANGE["id"], "judgements": []})


class MirrorRegMemory(FakeRegMemory):
    def __init__(self) -> None:
        super().__init__()
        self.html = "<main><p>postcode or career gaps.</p></main>"

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/demo/mirror":
            if request.method == "PUT":
                body = json.loads(request.content)
                if body.get("find"):
                    self.html = self.html.replace(body["find"], body.get("replace") or "")
                self.calls.append(request)
            return httpx.Response(
                200, json={"url": "u", "bytes": len(self.html), "html": self.html}
            )
        if path == "/v1/watch/check-now":
            self.calls.append(request)
            return httpx.Response(
                200,
                json={
                    "check_id": "chk-1",
                    "status": "done",
                    "changed_documents": ["demo-art6-guideline-mirror"],
                    "release": {"kb_version": "2026.11.14-2", "change_id": CHANGE["id"]},
                },
            )
        return super().handle(request)


@pytest.fixture
def reg_memory(monkeypatch):
    fake = MirrorRegMemory()
    monkeypatch.setattr(regulation, "transport", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(settings.reg_memory, "secret", SecretStr("reg-secret"))
    return fake


@pytest.fixture
def agents(monkeypatch, session_factory):
    fake = FakeAgents()
    monkeypatch.setattr(regulation, "agents_transport", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(regulation, "session_factory", session_factory)
    return fake


async def _drain() -> None:
    await asyncio.gather(*list(regulation._judge_tasks), return_exceptions=True)


async def test_accept_starts_the_judge_with_every_card(client, reg_memory, agents, bot):  # noqa: F811
    await client.post(
        "/v1/systems",
        json={
            "id": "SYS-001",
            "name": "CV screener",
            "data": {"card": {"id": "SYS-001", "role": "provider", "risk_class": "high_risk"}},
        },
    )
    accepted = await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/decision", json={"status": "accepted"}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["judge"] == "running"
    await _drain()
    ((path, body),) = agents.calls
    assert path == f"/changes/{CHANGE['id']}/judge"
    assert body["rerun"] is True
    (system,) = body["systems"]
    assert system["system_id"] == "SYS-001" and system["card"]["role"] == "provider"
    assert system["findings"] == []

    # the judge answers "no system affected": the inbox says done, not pending
    stored = await client.put(
        f"/internal/regulation/changes/{CHANGE['id']}/judgement",
        json={"affected": [], "decidedBy": "iris"},
    )
    assert stored.status_code < 300, stored.text
    change = (await client.get(f"/v1/regulation/changes/{CHANGE['id']}")).json()
    assert change["judge"] == "done" and change["affected"] == []


async def test_a_failed_judge_is_flagged(client, reg_memory, agents, bot):  # noqa: F811
    agents.status = 500
    await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/decision", json={"status": "accepted"}
    )
    await _drain()
    change = (await client.get(f"/v1/regulation/changes/{CHANGE['id']}")).json()
    assert change["judge"] == "failed"


async def test_rejecting_starts_no_judge(client, reg_memory, agents, bot):  # noqa: F811
    await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/decision", json={"status": "rejected"}
    )
    await _drain()
    assert agents.calls == []


async def test_simulate_change_edits_the_mirror_and_checks_it(client, reg_memory):
    out = await client.put(
        "/v1/regulation/demo/mirror",
        json={
            "find": "postcode or career gaps.",
            "replace": "postcode or nationality.",
            "check": True,
        },
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert "nationality" in body["html"]
    assert body["check"]["release"]["change_id"] == CHANGE["id"]
    put, check = reg_memory.calls[-2:]
    assert json.loads(put.content) == {
        "find": "postcode or career gaps.",
        "replace": "postcode or nationality.",
    }
    assert json.loads(check.content) == {
        "source_ids": ["demo-art6-guideline-mirror"],
        "wait": True,
        "discovery": False,
    }
    page = (await client.get("/v1/regulation/demo/mirror")).json()
    assert "nationality" in page["html"]
