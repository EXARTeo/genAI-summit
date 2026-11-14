"""The regulation proxy (reg-memory -> UI types), GET /v1/agents and the
Telegram HITL flow (notify on gate, approve/reject by button, allow-list,
idempotency). No network: reg-memory, the agents service and the Bot API are
``httpx.MockTransport``s."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

import utils.agents_catalog as agents_catalog
import utils.audit_pipeline as audit_pipeline
import utils.regulation as regulation
import utils.telegram as telegram
import utils.telegram_gates as gates
from core.database import RegulationChangeTable, TelegramPromptTable
from core.settings import settings
from utils.hitl_decisions import ResumeOutcome

CHAT = "4242"


class FakeBot:
    """The Telegram Bot API: records every call, answers ok with a message id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._next = 100

    def handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        self.calls.append((method, body))
        self._next += 1
        result: Any = {"message_id": self._next} if method == "sendMessage" else True
        return httpx.Response(200, json={"ok": True, "result": result})

    def sent(self, method: str) -> list[dict[str, Any]]:
        return [body for m, body in self.calls if m == method]


@pytest.fixture
def bot(monkeypatch, session_factory):
    fake = FakeBot()
    monkeypatch.setattr(telegram, "transport", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(settings.telegram, "bot_token", SecretStr("123:abc"))
    monkeypatch.setattr(settings.telegram, "chat_ids", (CHAT,))
    monkeypatch.setattr(gates, "SessionLocal", session_factory)
    fake.resumes = []

    def pipeline(request: httpx.Request) -> httpx.Response:
        fake.resumes.append((request.url.path, json.loads(request.content)))
        return httpx.Response(202, json={"status": "resumed"})

    monkeypatch.setattr(audit_pipeline, "transport", httpx.MockTransport(pipeline))
    return fake


def _callback(data: str, chat: str = CHAT, user: str = "alice") -> dict[str, Any]:
    return {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "from": {"id": 7, "username": user},
            "message": {"message_id": 101, "chat": {"id": int(chat)}},
            "data": data,
        },
    }


async def _waiting_audit(client) -> dict[str, Any]:
    assert (
        await client.post("/v1/systems", json={"id": "SYS-001", "name": "CV screener"})
    ).status_code == 201
    audit = (await client.post("/v1/systems/SYS-001/audits", json={})).json()
    await client.post(
        f"/v1/audits/{audit['id']}/artifacts",
        json={
            "kind": "dataset_analysis",
            "data": {
                "rows": 500,
                "gates": {"schema": {"status": "pass"}, "privacy": {"status": "fail"}},
            },
        },
    )
    patched = await client.patch(
        f"/v1/audits/{audit['id']}",
        json={"stage": "approve_datasets", "status": "waiting_approval"},
    )
    assert patched.status_code == 200, patched.text
    return patched.json()


async def _prompt(session_factory) -> TelegramPromptTable:
    async with session_factory() as db:
        return (await db.scalars(select(TelegramPromptTable))).one()


async def _press(session_factory, update: dict[str, Any]) -> None:
    async with session_factory() as db:
        await gates.handle_update(db, update)


# ---- audit gates ----------------------------------------------------------------


async def test_gate_creation_notifies_once_with_buttons(client, bot):
    audit = await _waiting_audit(client)
    assert audit["data"]["systemName"] == "CV screener"
    assert audit["status"] == "waiting_approval"
    [message] = bot.sent("sendMessage")
    assert message["chat_id"] == CHAT
    assert "CV screener" in message["text"] and "failed gates 1/2" in message["text"]
    assert f"/audits/{audit['id']}?step=approve_datasets" in message["text"]
    buttons = [b for row in message["reply_markup"]["inline_keyboard"] for b in row]
    assert [b["text"] for b in buttons] == ["✅ Approve", "❌ Reject"]  # localhost: link in text
    # Same gate again: no second message.
    await client.patch(f"/v1/audits/{audit['id']}", json={"data": {"x": 1}})
    await client.patch(f"/v1/audits/{audit['id']}", json={"status": "waiting_approval"})
    assert len(bot.sent("sendMessage")) == 1


async def test_approve_by_button_records_the_approval_and_is_idempotent(
    client, bot, session_factory
):
    audit = await _waiting_audit(client)
    prompt = await _prompt(session_factory)
    await _press(session_factory, _callback(f"g:{prompt.id}:a"))
    detail = (await client.get(f"/v1/audits/{audit['id']}")).json()
    [approval] = detail["approvals"]
    assert approval["gate"] == "datasets"
    assert approval["decision"] == "approved"
    assert approval["decidedBy"] == "telegram:alice"
    assert approval["artifactId"] == detail["artifacts"][0]["id"]
    assert "Approved by @alice" in bot.sent("editMessageText")[-1]["text"]
    # ...and the waiting pipeline is resumed exactly like an approval from the UI.
    [(path, body)] = bot.resumes
    assert path == f"/audits/{audit['id']}/resume"
    assert body["gate"] == "datasets" and body["decision"] == "approved"
    assert body["system_id"] == "SYS-001" and body["decidedBy"] == "telegram:alice"
    # Pressed again (or by someone else): nothing recorded twice.
    await _press(session_factory, _callback(f"g:{prompt.id}:a", user="bob"))
    assert len((await client.get(f"/v1/audits/{audit['id']}/approvals")).json()) == 1
    assert bot.sent("answerCallbackQuery")[-1]["text"] == "Already decided by telegram:alice"


async def test_reject_asks_a_reason_then_records_it(client, bot, session_factory):
    audit = await _waiting_audit(client)
    prompt = await _prompt(session_factory)
    await _press(session_factory, _callback(f"g:{prompt.id}:r"))
    markup = bot.sent("editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"]
    assert markup[0][0] == {"text": "Wrong fact", "callback_data": f"g:{prompt.id}:c0"}
    await _press(session_factory, _callback(f"g:{prompt.id}:c4"))  # unrealistic_data
    ask = bot.sent("sendMessage")[-1]
    assert ask["reply_markup"]["force_reply"] is True
    # The ForceReply's message id is stored on the prompt.
    pending = (await _prompt(session_factory)).data["pending_reject"]
    ask_id = pending["message_id"]
    reply = {
        "update_id": 2,
        "message": {
            "message_id": 300,
            "from": {"id": 7, "username": "alice"},
            "chat": {"id": int(CHAT)},
            "text": "Income column is far too uniform",
            "reply_to_message": {"message_id": ask_id},
        },
    }
    await _press(session_factory, reply)
    [approval] = (await client.get(f"/v1/audits/{audit['id']}/approvals")).json()
    assert approval["decision"] == "rejected"
    assert approval["reasonCategory"] == "unrealistic_data"
    assert approval["comment"] == "Income column is far too uniform"
    assert "Rejected by @alice: unrealistic_data" in bot.sent("editMessageText")[-1]["text"]


async def test_unauthorized_chat_is_ignored(client, bot, session_factory):
    audit = await _waiting_audit(client)
    prompt = await _prompt(session_factory)
    await _press(session_factory, _callback(f"g:{prompt.id}:a", chat="999"))
    assert (await client.get(f"/v1/audits/{audit['id']}/approvals")).json() == []
    assert bot.sent("answerCallbackQuery")[-1]["text"] == "This chat may not decide gates."
    assert (await _prompt(session_factory)).status == "open"


async def test_decided_in_the_app_closes_the_telegram_prompt(client, bot, session_factory):
    audit = await _waiting_audit(client)
    response = await client.post(
        f"/v1/audits/{audit['id']}/approvals",
        json={"gate": "datasets", "decision": "approved", "reasonCategory": "other"},
    )
    assert response.status_code == 201
    prompt = await _prompt(session_factory)
    assert prompt.status == "decided" and prompt.decided_by.startswith("client:")
    assert "(in the app)" in bot.sent("editMessageText")[-1]["text"]
    await _press(session_factory, _callback(f"g:{prompt.id}:a"))
    assert bot.sent("answerCallbackQuery")[-1]["text"].startswith("Already decided by client:")
    assert len((await client.get(f"/v1/audits/{audit['id']}/approvals")).json()) == 1


async def test_no_token_is_a_no_op(client, monkeypatch, session_factory):
    monkeypatch.setattr(settings.telegram, "bot_token", SecretStr(""))
    await _waiting_audit(client)
    async with session_factory() as db:
        assert (await db.scalars(select(TelegramPromptTable))).all() == []


# ---- chat HITL --------------------------------------------------------------------


async def test_chat_tool_approval_resumes_the_run(
    bot, session_factory, conversation_factory, monkeypatch
):
    conv = await conversation_factory(
        title="t",
        messages=[{"sender": "user", "content": "hi"}, {"sender": "ai", "content": ""}],
    )
    run_id = conv["message_ids"][-1]
    resumed: list[dict[str, Any]] = []

    def fake_resume(run, payload):
        resumed.append({"run": run.id, **payload})
        return ResumeOutcome.ACCEPTED

    monkeypatch.setattr(gates, "request_run_resume", fake_resume)
    value = {
        "interrupt": {
            "id": "int-1",
            "value": {"action_requests": [{"name": "write_file", "args": {"path": "a.txt"}}] * 2},
        }
    }
    await gates.notify_chat_interrupt(run_id, "int-1", value)
    [message] = bot.sent("sendMessage")
    assert "write_file" in message["text"] and f"/chat/{conv['conversation_id']}" in message["text"]
    prompt = await _prompt(session_factory)
    await _press(session_factory, _callback(f"g:{prompt.id}:a"))
    assert resumed == [
        {
            "run": run_id,
            "decision": "approve",
            "reason": None,
            "value": None,
            "interrupt_id": "int-1",
            "decisions": [{"decision": "approve", "reason": None}] * 2,
        }
    ]
    # ask_user (no action_requests) is never sent to Telegram.
    await gates.notify_chat_interrupt(
        run_id, "int-2", {"interrupt": {"id": "int-2", "value": {"questions": []}}}
    )
    assert len(bot.sent("sendMessage")) == 1


# ---- regulation proxy ---------------------------------------------------------------

CHANGE = {
    "id": "RC-2026.11.14-2",
    "from_kb_version": "2026.11.14-1",
    "to_kb_version": "2026.11.14-2",
    "created_at": "2026-11-14T17:59:49+00:00",
    "status": "open",
    "change_types": {"new_interpretation": 1},
    "summary": "1 interpretation(s) changed",
    "impacted_requirements": [{"requirement_id": "REQ.AIA.6.2.x", "via": ["AIA.6.2"]}],
    "provisions": [],
    "interpretations": [
        {
            "id": "INT.demo.2-employment",
            "change": "changed",
            "change_type": "new_interpretation",
            "title": "Demo mirror: 2. Employment",
            "source_id": "demo-art6-guideline-mirror",
        }
    ],
}


class FakeRegMemory:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.active = "2026.11.14-1"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers.get("X-Internal-Secret") == "reg-secret"
        path = request.url.path
        if path == "/v1/sources":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "demo-art6-guideline-mirror",
                            "title": "Demo",
                            "kind": "guideline",
                            "binding": False,
                            "status": "final",
                            "publisher": "EC",
                            "url": "http://x",
                            "tags": ["demo"],
                            "documents": 1,
                            "latest": {"version": 2, "status": "changed"},
                        }
                    ]
                },
            )
        if path == "/v1/documents/demo-art6-guideline-mirror":
            return httpx.Response(
                200,
                json={
                    "doc_id": "d",
                    "source_id": "d",
                    "url": "u",
                    "versions": [
                        {
                            "version": 1,
                            "status": "new",
                            "fetched_at": "t1",
                            "sha256": "a",
                            "bytes": 10,
                        },
                        {
                            "version": 1,
                            "status": "same",
                            "fetched_at": "t2",
                            "sha256": "a",
                            "bytes": 10,
                        },
                        {
                            "version": 2,
                            "status": "changed",
                            "fetched_at": "t3",
                            "sha256": "b",
                            "bytes": 12,
                        },
                    ],
                },
            )
        if path == "/v1/documents/demo-art6-guideline-mirror/text":
            version = int(request.url.params["version"])
            text = "line one\nhigh-risk.\n" if version == 1 else "line one\nhigh-risk, even so.\n"
            return httpx.Response(
                200,
                json={
                    "doc_id": "demo-art6-guideline-mirror",
                    "version": version,
                    "sha256": "x",
                    "text": text,
                },
            )
        if path == "/v1/changes":
            return httpx.Response(200, json={"items": [{"id": CHANGE["id"]}]})
        if path == f"/v1/changes/{CHANGE['id']}":
            return httpx.Response(200, json=CHANGE)
        if path == "/v1/releases":

            def rel(v, n):
                return {
                    "kb_version": v,
                    "status": "active" if v == self.active else "candidate",
                    "inputs": {"demo-art6-guideline-mirror": {"version": n}},
                }

            return httpx.Response(
                200,
                json={
                    "active": self.active,
                    "items": [rel("2026.11.14-2", 2), rel("2026.11.14-1", 1)],
                },
            )
        if path == "/v1/releases/2026.11.14-2/activate" and request.method == "POST":
            self.active = "2026.11.14-2"
            return httpx.Response(200, json={"kb_version": "2026.11.14-2", "status": "active"})
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
def reg_memory(monkeypatch):
    fake = FakeRegMemory()
    monkeypatch.setattr(regulation, "transport", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(settings.reg_memory, "secret", SecretStr("reg-secret"))
    return fake


async def test_sources_map_to_the_ui_shape(client, reg_memory):
    response = await client.get("/v1/regulation/sources")
    assert response.status_code == 200, response.text
    [source] = response.json()
    assert source["id"] == "demo-art6-guideline-mirror"
    assert source["binding"] is False
    assert [v["version"] for v in source["versions"]] == [1, 2]
    assert source["versions"][1] == {
        "version": 2,
        "fetchedAt": "t3",
        "sha256": "b",
        "status": "changed",
        "bytes": 12,
        "diff": None,
    }


async def test_text_and_diff(client, reg_memory):
    text = (
        await client.get("/v1/regulation/documents/demo-art6-guideline-mirror/text?version=1")
    ).json()
    assert text == {
        "docId": "demo-art6-guideline-mirror",
        "version": 1,
        "text": "line one\nhigh-risk.\n",
    }
    diff = (
        await client.get("/v1/regulation/documents/demo-art6-guideline-mirror/diff?from=1&to=2")
    ).json()
    assert diff["from"] == 1 and diff["to"] == 2
    assert "-high-risk.\n+high-risk, even so." in diff["unified"]
    assert (await client.get("/v1/regulation/documents/nope/text")).status_code == 404


async def test_changes_map_and_accept_activates_the_release(client, reg_memory, bot):
    [change] = (await client.get("/v1/regulation/changes")).json()
    assert change["id"] == CHANGE["id"]
    assert change["changeType"] == "clarification"
    assert change["sourceId"] == "demo-art6-guideline-mirror"
    assert (change["fromVersion"], change["toVersion"]) == (1, 2)
    assert change["candidateKbVersion"] == "2026.11.14-2"
    assert change["status"] == "proposed"
    assert change["affected"] == [] and change["judge"] == "pending"
    assert change["provisions"] == ["INT.demo.2-employment"]

    accepted = await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/decision", json={"status": "accepted"}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert reg_memory.active == "2026.11.14-2"
    again = await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/decision", json={"status": "rejected"}
    )
    assert again.status_code == 409

    await client.post("/v1/systems", json={"id": "SYS-001", "name": "CV screener"})
    override = await client.post(
        f"/v1/regulation/changes/{CHANGE['id']}/systems/SYS-001", json={"decision": "rerun_tests"}
    )
    [affected] = override.json()["affected"]
    assert affected["systemName"] == "CV screener" and affected["humanDecision"] == "rerun_tests"


async def test_reg_memory_notifies_and_telegram_accepts(client, reg_memory, bot, session_factory):
    payload = {
        k: CHANGE[k]
        for k in (
            "id",
            "from_kb_version",
            "to_kb_version",
            "summary",
            "change_types",
            "impacted_requirements",
        )
    }
    payload["items"] = [{"id": "INT.demo.2-employment", "change_type": "new_interpretation"}]
    for _ in range(2):  # idempotent
        response = await client.post("/internal/regulation/changes", json=payload)
        assert response.status_code == 202, response.text
    async with session_factory() as db:
        assert (await db.get(RegulationChangeTable, CHANGE["id"])).data["payload"]["id"] == CHANGE[
            "id"
        ]
    [message] = bot.sent("sendMessage")
    assert "Regulation change" in message["text"]
    assert message["reply_markup"]["inline_keyboard"][0][0]["text"] == "✅ Accept kb 2026.11.14-2"
    prompt = await _prompt(session_factory)
    await _press(session_factory, _callback(f"g:{prompt.id}:a", user="carol"))
    change = (await client.get(f"/v1/regulation/changes/{CHANGE['id']}")).json()
    assert change["status"] == "accepted" and change["decidedBy"] == "telegram:carol"
    assert reg_memory.active == "2026.11.14-2"


async def test_reg_memory_down_is_a_502(client, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(regulation, "transport", httpx.MockTransport(boom))
    assert (await client.get("/v1/regulation/sources")).status_code == 502


# ---- agents catalog -------------------------------------------------------------------


async def test_agents_lists_the_agents_service_catalog(client, monkeypatch):
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=[{"slug": "auditor", "name": "Auditor", "default": True}])

    monkeypatch.setattr(agents_catalog, "transport", httpx.MockTransport(handle))
    response = await client.get("/v1/agents")
    assert response.status_code == 200
    assert response.json() == [{"slug": "auditor", "name": "Auditor", "default": True}]
    assert seen == ["/agents"]


async def test_public_data_gate_picks_a_candidate(client, bot, session_factory):
    await client.post("/v1/systems", json={"id": "SYS-002", "name": "Credit scorer"})
    audit = (await client.post("/v1/systems/SYS-002/audits", json={})).json()
    candidates = [
        {"id": "openml-31", "name": "credit-g", "score": 0.75, "n_rows": 1000},
        {"id": "uci-2", "name": "adult", "score": 0.6},
    ]
    await client.post(
        f"/internal/audits/{audit['id']}/artifacts",
        json={
            "kind": "public_dataset_candidates",
            "name": "scorer",
            "data": {"candidates": candidates},
        },
    )
    await client.patch(
        f"/internal/audits/{audit['id']}",
        json={"stage": "find_public_data", "status": "waiting_approval"},
    )
    [message] = bot.sent("sendMessage")  # artifact + gate: one message
    assert "credit-g (score 0.75), 1000 rows" in message["text"]
    rows = message["reply_markup"]["inline_keyboard"]
    assert rows[0][0]["text"] == "Use #1 credit-g"
    prompt = await _prompt(session_factory)
    await _press(session_factory, _callback(f"g:{prompt.id}:p1"))
    [approval] = (await client.get(f"/v1/audits/{audit['id']}/approvals")).json()
    assert approval["gate"] == "public_data" and approval["edits"] == {"selected": "uci-2"}
    [(_path, body)] = bot.resumes
    assert body["gate"] == "public_data" and body["edits"] == {"selected": "uci-2"}


async def test_audit_status_aliases_and_validation(client):
    await client.post("/v1/systems", json={"id": "SYS-003", "name": "x"})
    audit = (await client.post("/v1/systems/SYS-003/audits", json={})).json()
    done = await client.patch(f"/v1/audits/{audit['id']}", json={"status": "completed"})
    assert done.json()["status"] == "done"
    assert done.json()["data"]["title"] == "Audit of x"
    bad = await client.patch(f"/v1/audits/{audit['id']}", json={"status": "weird"})
    assert bad.status_code == 422
