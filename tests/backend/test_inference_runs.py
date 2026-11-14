"""Runs end to end over HTTP: start (new/send/edit/retry), the request the
agents service receives, persistence of the answer, upstream failures, the
per-client cap, cancel, replay, startup cleanup — and that one browser can
never see or touch another browser's runs."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from conftest import CLIENT_ID
from run_helpers import STREAM_PATH, answer, finished, seed_queued_run, sse_reply
from sqlalchemy import select

import router.inference as inference_router
import utils.inference_runs as ir
from core.database import AttachmentTable, MessageTable
from core.settings import settings
from utils.inference_runs import (
    SNAPSHOT_SEQ_SENTINEL,
    cleanup_orphaned_inference_runs,
    stream_run_events,
)

START = "/v1/inference/runs/start"


@pytest.fixture
def run_sessions(session_factory, monkeypatch):
    """Point the detached run task (and the sockets) at the test database."""
    monkeypatch.setattr(ir, "SessionLocal", session_factory)
    monkeypatch.setattr(inference_router, "SessionLocal", session_factory)
    return session_factory


def _bodies(agents_service, path: str = STREAM_PATH) -> list[dict]:
    return [json.loads(request.content) for request in agents_service.called("POST", path)]


async def _new(client, text: str = "Hi there") -> dict:
    response = await client.post(
        START,
        json={
            "mode": "new",
            "agentSlug": "test-agent",
            "agentName": "Test Agent",
            "message": {"sender": "user", "content": text},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_new_conversation_runs_to_completion(client, agents_service, run_sessions):
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Hello world")))
    started = await _new(client)
    run_id = started["run"]["id"]
    assert started["run"]["status"] == "queued"
    assert started["userMessage"]["content"] == "Hi there"
    assert started["message"]["id"] == run_id

    run = await finished(run_id, run_sessions)
    assert run.streaming_status == "completed"
    assert run.content == "Hello world"
    assert run.checkpoint_id == "ckpt-1"
    assert run.agent_slug == "test-agent"
    assert all(e.get("name") != "CHECKPOINT_COMMITTED" for e in run.raw_events)

    (body,) = _bodies(agents_service)
    context = body["config"]["context"]
    assert context == {
        "client_id": CLIENT_ID,
        "conversation_id": started["run"]["conversationId"],
        "run_id": run_id,
    }
    assert body["config"]["run_config"]["configurable"]["thread_id"] == run.checkpoint_thread_id
    assert "fork_from" not in body["config"] and "trace" not in body["config"]
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert body["messages"][0]["content"] == "Hi there"
    request = agents_service.called("POST", STREAM_PATH)[0]
    assert request.headers["accept"] == "text/event-stream"
    assert "x-internal-service-secret" not in request.headers


async def test_send_continues_the_branch_thread_with_only_the_new_message(
    client, agents_service, run_sessions, monkeypatch
):
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("First")))
    first = await _new(client)
    first_run = await finished(first["run"]["id"], run_sessions)

    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Second", "ckpt-2")))
    response = await client.post(
        START,
        json={
            "mode": "send",
            "conversationId": first["run"]["conversationId"],
            "parentMessageId": first_run.id,
            "message": {"sender": "user", "content": "And then?"},
        },
    )
    assert response.status_code == 201, response.text
    second_run = await finished(response.json()["run"]["id"], run_sessions)
    assert second_run.content == "Second"
    assert second_run.checkpoint_thread_id == first_run.checkpoint_thread_id

    body = _bodies(agents_service)[-1]
    assert [m["content"] for m in body["messages"]] == ["And then?"]
    assert (
        body["config"]["run_config"]["configurable"]["thread_id"] == first_run.checkpoint_thread_id
    )


async def test_edit_forks_from_the_committed_ancestor_and_retry_reuses_the_agent(
    client, agents_service, run_sessions
):
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("First")))
    first = await _new(client)
    first_run = await finished(first["run"]["id"], run_sessions)
    conversation_id = first["run"]["conversationId"]

    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Second", "ckpt-2")))
    sent = await client.post(
        START,
        json={
            "mode": "send",
            "conversationId": conversation_id,
            "parentMessageId": first_run.id,
            "message": {"sender": "user", "content": "Q2"},
        },
    )
    second_run = await finished(sent.json()["run"]["id"], run_sessions)

    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Edited", "ckpt-3")))
    edited = await client.post(
        START,
        json={
            "mode": "edit",
            "conversationId": conversation_id,
            "targetMessageId": second_run.parent_message_id,
            "message": {"sender": "user", "content": "Q2, reworded"},
        },
    )
    assert edited.status_code == 201, edited.text
    edit_run = await finished(edited.json()["run"]["id"], run_sessions)
    body = _bodies(agents_service)[-1]
    assert body["config"]["fork_from"] == {
        "thread_id": first_run.checkpoint_thread_id,
        "checkpoint_id": "ckpt-1",
    }
    assert edit_run.checkpoint_thread_id != first_run.checkpoint_thread_id
    assert edit_run.agent_slug == "test-agent"

    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Retried", "ckpt-4")))
    retried = await client.post(
        START,
        json={"mode": "retry", "conversationId": conversation_id, "targetMessageId": edit_run.id},
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["userMessage"] is None
    retry_run = await finished(retried.json()["run"]["id"], run_sessions)
    assert retry_run.parent_message_id == edit_run.parent_message_id
    assert retry_run.content == "Retried"


async def test_an_unknown_agent_fails_the_run_with_a_clear_error(
    client, agents_service, run_sessions
):
    agents_service.on("POST", STREAM_PATH, httpx.Response(404, json={"detail": "Unknown agent"}))
    started = await _new(client)
    run = await finished(started["run"]["id"], run_sessions)
    assert run.streaming_status == "failed"
    assert run.error_message == "This agent is not available."


async def test_run_error_fails_the_run_and_keeps_the_partial_answer(
    client, agents_service, run_sessions
):
    agents_service.on(
        "POST",
        STREAM_PATH,
        sse_reply(
            {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m", "delta": "Partial"},
            {"type": "RUN_ERROR", "message": "Model overloaded"},
        ),
    )
    run = await finished((await _new(client))["run"]["id"], run_sessions)
    assert (run.streaming_status, run.error_message, run.content) == (
        "failed",
        "Model overloaded",
        "Partial",
    )


async def test_a_presented_file_with_bytes_becomes_a_generated_attachment(
    client, agents_service, run_sessions
):
    data = b"col\n1\n"
    agents_service.on(
        "POST",
        STREAM_PATH,
        sse_reply(
            {
                "type": "CUSTOM",
                "name": "PRESENT_ARTIFACT",
                "value": {
                    "path": "/out/table.csv",
                    "filename": "table.csv",
                    "mime": "text/csv",
                    "title": "Table",
                    "summary": "One column",
                    "data_base64": base64.b64encode(data).decode(),
                },
            },
            *answer("Here it is"),
        ),
    )
    run_id = (await _new(client))["run"]["id"]
    run = await finished(run_id, run_sessions)
    assert "data_base64" not in json.dumps(run.raw_events)
    async with run_sessions() as session:
        query = select(AttachmentTable).where(AttachmentTable.message_id == run_id)
        (attachment,) = (await session.scalars(query)).all()
        await session.refresh(attachment, ["blob"])
        assert (attachment.origin, attachment.file_name, attachment.title) == (
            "generated",
            "table.csv",
            "Table",
        )
        assert attachment.blob.data == data


async def test_a_busy_conversation_refuses_a_second_run(client, run_sessions):
    run_id = await seed_queued_run(run_sessions, CLIENT_ID)
    async with run_sessions() as session:
        run = await session.get(MessageTable, run_id)
    response = await client.post(
        START,
        json={
            "mode": "send",
            "conversationId": run.conversation_id,
            "parentMessageId": run.parent_message_id,
            "message": {"sender": "user", "content": "again"},
        },
    )
    assert response.status_code == 409


async def test_the_active_run_cap_is_per_client(
    client, other_client, agents_service, run_sessions, monkeypatch
):
    monkeypatch.setattr(settings.rate_limit, "inference_max_active_runs", 1)
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("ok")))
    await seed_queued_run(run_sessions, CLIENT_ID)
    assert (await client.post(START, json=_new_body())).status_code == 429
    # Another browser has its own budget.
    response = await other_client.post(START, json=_new_body())
    assert response.status_code == 201
    await finished(response.json()["run"]["id"], run_sessions)


def _new_body() -> dict:
    return {"mode": "new", "agentSlug": "test-agent", "message": {"sender": "user", "content": "x"}}


async def test_an_invalid_slug_is_refused_before_anything_is_written(client):
    body = {**_new_body(), "agentSlug": "../admin"}
    assert (await client.post(START, json=body)).status_code == 422


async def test_a_new_scoped_chat_needs_an_existing_system(client):
    body = {**_new_body(), "systemId": "SYS-404"}
    assert (await client.post(START, json=body)).status_code == 404
    assert (await client.get("/v1/conversations")).json()["items"] == []


async def test_runs_are_invisible_to_another_browser(client, other_client, run_sessions):
    run_id = await seed_queued_run(run_sessions, CLIENT_ID)
    mine = await client.get("/v1/inference/runs", params={"status": "active"})
    assert [r["id"] for r in mine.json()] == [run_id]
    assert (await other_client.get("/v1/inference/runs")).json() == []
    assert (await other_client.post(f"/v1/inference/runs/{run_id}/cancel")).status_code == 404
    async with run_sessions() as session:
        run = await session.get(MessageTable, run_id)
    hijack = await other_client.post(
        START,
        json={
            "mode": "send",
            "conversationId": run.conversation_id,
            "parentMessageId": run.parent_message_id,
            "message": {"sender": "user", "content": "hi"},
        },
    )
    assert hijack.status_code == 404


async def test_cancel_without_a_live_task_cancels_at_once(client, run_sessions):
    run_id = await seed_queued_run(run_sessions, CLIENT_ID)
    response = await client.post(f"/v1/inference/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    frames = [
        frame
        async for _seq, frame in stream_run_events(run_id)  # terminal: one snapshot
    ]
    assert frames[0]["type"] == "snapshot" and frames[0]["run"]["status"] == "cancelled"


async def test_a_finished_run_replays_as_one_database_snapshot(
    client, agents_service, run_sessions
):
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Done")))
    run_id = (await _new(client))["run"]["id"]
    await finished(run_id, run_sessions)
    frames = [(seq, frame) async for seq, frame in stream_run_events(run_id)]
    assert len(frames) == 1
    seq, frame = frames[0]
    assert seq == SNAPSHOT_SEQ_SENTINEL
    assert frame["message"]["content"] == "Done"
    assert frame["summary"]["id"] == frame["run"]["conversationId"]


async def test_startup_cleanup_fails_orphaned_runs(run_sessions):
    run_id = await seed_queued_run(run_sessions, CLIENT_ID)
    await cleanup_orphaned_inference_runs()
    async with run_sessions() as session:
        run = await session.get(MessageTable, run_id)
    assert run.streaming_status == "failed"
    assert "restart" in run.error_message


async def test_a_system_scoped_conversation_sends_its_system_to_the_agent(
    client, agents_service, run_sessions
):
    """The agents service mounts that system's memory (agents contract § Config)."""
    created = await client.post("/v1/systems", json={"id": "SYS-001", "name": "x"})
    assert created.status_code == 201
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("ok")))
    response = await client.post(
        START,
        json={
            "mode": "new",
            "agentSlug": "test-agent",
            "systemId": "SYS-001",
            "message": {"sender": "user", "content": "Plan the tests"},
        },
    )
    assert response.status_code == 201, response.text
    await finished(response.json()["run"]["id"], run_sessions)
    context = _bodies(agents_service)[-1]["config"]["context"]
    assert context["system_id"] == "SYS-001"
    assert "audit_id" not in context
