"""Helpers for the run-engine tests: SSE replies of the fake agents service,
seeding a queued run, and waiting for a detached run to end."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

import utils.inference_runs as ir
from core.database import ConversationTable, MessageTable
from utils.inference_runs import inference_run_manager

STREAM_PATH = "/agents/test-agent/stream"
RESUME_PATH = "/agents/test-agent/resume"


def sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"data: {json.dumps(event)}\n\n".encode() for event in events)


def sse_reply(*events: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=sse(*events), headers={"content-type": "text/event-stream"})


def answer(text: str, checkpoint_id: str | None = "ckpt-1") -> list[dict[str, Any]]:
    """A plain answer: run start, one text message, the committed checkpoint."""
    events: list[dict[str, Any]] = [
        {"type": "RUN_STARTED"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m1", "delta": text[: len(text) // 2]},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m1", "delta": text[len(text) // 2 :]},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
    ]
    if checkpoint_id:
        events.append(
            {
                "type": "CUSTOM",
                "name": "CHECKPOINT_COMMITTED",
                "value": {"thread_id": "t", "checkpoint_id": checkpoint_id},
            }
        )
    events.append({"type": "RUN_FINISHED"})
    return events


async def until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


async def finished(run_id: str, session_factory) -> MessageTable:
    """Wait for the run's task, then read its message fresh."""
    task = inference_run_manager._tasks.get(run_id)
    if task is not None:
        await asyncio.wait_for(task, timeout=5)
    async with session_factory() as session:
        return await session.get(MessageTable, run_id)


async def seed_queued_run(session_factory, client_id: str, question: str = "Hello?") -> str:
    """A conversation with a user message and a queued AI placeholder; the run id."""
    async with session_factory() as session:
        conversation = ConversationTable(
            client_id=client_id, agent_slug="test-agent", agent_name="Test Agent", title="t"
        )
        session.add(conversation)
        await session.flush()
        user = MessageTable(conversation_id=conversation.id, sender="user", content=question)
        session.add(user)
        await session.flush()
        run = MessageTable(
            conversation_id=conversation.id,
            parent_message_id=user.id,
            sender="ai",
            content="",
            raw_events=[],
            agent_slug="test-agent",
            agent_name="Test Agent",
            streaming_status="queued",
            streaming_started_at=ir._now(),
        )
        session.add(run)
        await session.flush()
        run.streaming_message_path = [user.id, run.id]
        conversation.active_assistant_message_id = run.id
        await session.commit()
        return run.id
