"""The composer's queued message and the conversation channel: a send to a
busy conversation is held (202), replaced, cancelled, refused with files, sent
when the run ends — and announced on the channel."""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import CLIENT_ID
from run_helpers import STREAM_PATH, answer, finished, seed_queued_run, sse_reply

import router.inference as inference_router
import utils.composer_queue as composer_queue
import utils.inference_runs as ir
from core.database import ConversationTable, MessageTable
from utils.conversation_channel import channel_frames, channel_key, conversation_channel
from utils.inference_runs import inference_run_manager

START = "/v1/inference/runs/start"


@pytest.fixture
def run_sessions(session_factory, monkeypatch):
    monkeypatch.setattr(ir, "SessionLocal", session_factory)
    monkeypatch.setattr(inference_router, "SessionLocal", session_factory)
    return session_factory


async def _channel(conversation_id: str) -> list[dict]:
    client = await conversation_channel._get_client()
    entries = await client.xrange(channel_key(conversation_id))
    return [json.loads(fields["payload"]) for _id, fields in entries]


async def _busy_conversation(session_factory) -> tuple[str, str, str]:
    """(conversation id, active run id, its parent user message id)."""
    run_id = await seed_queued_run(session_factory, CLIENT_ID)
    async with session_factory() as session:
        run = await session.get(MessageTable, run_id)
        return run.conversation_id, run_id, run.parent_message_id


def _send(conversation_id: str, parent_id: str, content: str = "next question", **extra) -> dict:
    return {
        "mode": "send",
        "conversationId": conversation_id,
        "parentMessageId": parent_id,
        "queue_if_busy": True,
        "message": {"sender": "user", "content": content},
        **extra,
    }


async def test_a_busy_send_is_queued_replaced_and_cancelled(client, run_sessions):
    conversation_id, run_id, parent_id = await _busy_conversation(run_sessions)

    queued = await client.post(START, json=_send(conversation_id, parent_id))
    assert queued.status_code == 202
    assert queued.json()["queued"] is True
    assert queued.json()["queued_message"]["content"] == "next question"
    assert queued.json()["queued_message"]["agent_slug"] == "test-agent"

    replaced = await client.post(START, json=_send(conversation_id, parent_id, "v2"))
    assert replaced.status_code == 202
    async with run_sessions() as session:
        stored = (await session.get(ConversationTable, conversation_id)).queued_message
    assert stored["content"] == "v2" and stored["after_run_id"] == run_id
    assert (await _channel(conversation_id))[-1]["queued_message"]["content"] == "v2"

    cancelled = await client.delete(f"/v1/inference/conversations/{conversation_id}/queued-message")
    assert cancelled.status_code == 204
    async with run_sessions() as session:
        assert (await session.get(ConversationTable, conversation_id)).queued_message is None
    assert (await _channel(conversation_id))[-1] == {"type": "queue", "queued_message": None}


async def test_files_are_never_queued(client, run_sessions):
    conversation_id, _run_id, parent_id = await _busy_conversation(run_sessions)
    body = _send(conversation_id, parent_id)
    body["message"]["attachments"] = [
        {"name": "a.txt", "mime": "text/plain", "size": 1, "dataB64": "YQ=="}
    ]
    response = await client.post(START, json=body)
    assert response.status_code == 409
    assert "Files" in response.json()["detail"]


async def test_another_browser_cannot_queue_or_cancel(other_client, run_sessions):
    conversation_id, _run_id, parent_id = await _busy_conversation(run_sessions)
    assert (
        await other_client.post(START, json=_send(conversation_id, parent_id))
    ).status_code == 404
    deleted = await other_client.delete(
        f"/v1/inference/conversations/{conversation_id}/queued-message"
    )
    assert deleted.status_code == 404


async def test_the_run_end_sends_the_queued_message(client, agents_service, run_sessions):
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("First answer")))
    conversation_id, run_id, parent_id = await _busy_conversation(run_sessions)
    assert (await client.post(START, json=_send(conversation_id, parent_id))).status_code == 202

    inference_run_manager.launch(run_id)
    await finished(run_id, run_sessions)
    frames: list[dict] = []

    async def started() -> bool:
        frames[:] = await _channel(conversation_id)
        return any(f["type"] == "run_started" for f in frames)

    for _ in range(500):
        if await started():
            break
        await asyncio.sleep(0.01)
    run_started = next(f for f in frames if f["type"] == "run_started")
    assert run_started["from_queue"] is True
    queued_run = await finished(run_started["run"]["id"], run_sessions)
    assert queued_run.parent_message_id is not None
    async with run_sessions() as session:
        question = await session.get(MessageTable, queued_run.parent_message_id)
        conversation = await session.get(ConversationTable, conversation_id)
    assert question.content == "next question" and question.parent_message_id == run_id
    assert conversation.queued_message is None


async def test_a_transient_refusal_puts_the_message_back(run_sessions):
    conversation_id, _run_id, _parent = await _busy_conversation(run_sessions)
    value = {
        "content": "q",
        "agent_slug": "test-agent",
        "agent_name": None,
        "queued_at": "2026-01-01T00:00:00Z",
        "after_run_id": None,
    }
    async with run_sessions() as session:
        (await session.get(ConversationTable, conversation_id)).queued_message = value
        await session.commit()
    # The conversation still has its active run: the send is refused with 409.
    sent = await composer_queue.send_queued_message(conversation_id, session_factory=run_sessions)
    assert sent is False
    async with run_sessions() as session:
        assert (await session.get(ConversationTable, conversation_id)).queued_message == value


async def test_the_channel_starts_with_the_queue_then_tails_frames():
    await conversation_channel.publish("conv-1", {"type": "queue", "queued_message": None, "n": 0})
    frames = channel_frames("conv-1", None, None)
    assert await anext(frames) == {"type": "queue", "queued_message": None}
    await conversation_channel.publish("conv-1", {"type": "run_started", "n": 1})
    tailed = await anext(frames)
    assert tailed["n"] == 1 and "seq" in tailed
    await frames.aclose()
