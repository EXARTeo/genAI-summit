"""Async sub-agents, the backend half.

Pinned here:

* the ``conversation_tasks`` mirror: written from ``tasks:status`` entries,
  never across clients, settled tasks get their coalesced events;
* the consumer-group plumbing on fakeredis: handled entries are acked,
  malformed ones dropped, a database failure leaves the entry pending;
* the wake-up: notice row on the task's own branch leaf, a ``send`` run on
  the same thread whose request carries the notice's ``kind`` and
  ``additional_kwargs``, ``run_started`` on the conversation channel, the
  agents service told only once the run exists or the wake-up was skipped;
  409 leaves it unnotified, 429 retries then defers, a user's Stop never wakes;
* the run-end hook: the queued message goes first, else one wake-up; a run
  the user stopped holds its pending results;
* the reconcile loop: left-behind queued messages, then unnotified settles;
* the routes, the drill-down frames, ``hasActiveTasks``, delete and fork.

The agents service is an ``httpx.MockTransport`` (``agents_service``); Redis
is the suite's fakeredis.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from conftest import CLIENT_ID
from run_helpers import STREAM_PATH, answer, finished, sse_reply
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import utils.async_tasks as async_tasks
import utils.inference_runs as ir
import utils.task_consumers as task_consumers_module
import utils.task_wakeups as task_wakeups
from core.database import ConversationTable, ConversationTaskTable, MessageTable
from core.settings import settings
from schema.messages import MessageOut
from schema.tasks import OutboxItem, TaskStatusEntry
from utils.conversation_channel import channel_key, conversation_channel
from utils.inference import InlineBudget, serialise_message_for_agent
from utils.task_consumers import TaskConsumers, handle_status_entry
from utils.task_streams import CONSUMER_GROUP, STATUS_STREAM, task_events_key, task_streams
from utils.task_wakeups import (
    WakeOutcome,
    find_branch_leaf,
    handle_outbox_item,
    on_run_finished,
    reconcile_once,
)

pytestmark = pytest.mark.timeout(30)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _wire(monkeypatch, session_factory):
    """Point every module at the test database; no backoff, short blocks."""
    for module in (ir, async_tasks, task_wakeups):
        monkeypatch.setattr(module, "SessionLocal", session_factory)
    monkeypatch.setattr(settings.async_tasks, "wake_retry_base_seconds", 0.0)
    monkeypatch.setattr(settings.async_tasks, "task_ws_block_ms", 100)


@pytest.fixture
def launched(monkeypatch):
    """Runs the code under test launched (never actually streamed)."""
    ids: list[str] = []
    monkeypatch.setattr(ir.inference_run_manager, "launch", ids.append)
    return ids


async def _branchy_conversation(session_factory, client_id: str = CLIENT_ID) -> dict[str, Any]:
    """u1 → a1 → u2 → a2 on thread T, plus an edit branch u2b → a2b on thread T2."""
    t0 = _now() - timedelta(minutes=10)
    async with session_factory() as s:
        conv = ConversationTable(
            client_id=client_id, agent_slug="test-agent", agent_name="Test Agent", title="c"
        )
        s.add(conv)
        await s.flush()

        def msg(sender: str, parent: str | None, minutes: int, **kw: Any) -> MessageTable:
            m = MessageTable(
                conversation_id=conv.id,
                sender=sender,
                content=f"{sender}-{minutes}",
                parent_message_id=parent,
                created_at=t0 + timedelta(minutes=minutes),
                **kw,
            )
            s.add(m)
            return m

        ai = {"agent_slug": "test-agent", "agent_name": "Test Agent"}
        u1 = msg("user", None, 0)
        await s.flush()
        a1 = msg(
            "ai",
            u1.id,
            1,
            streaming_status="completed",
            checkpoint_thread_id="T",
            checkpoint_id="c1",
            **ai,
        )
        await s.flush()
        u2 = msg("user", a1.id, 2)
        await s.flush()
        a2 = msg(
            "ai",
            u2.id,
            3,
            streaming_status="completed",
            checkpoint_thread_id="T",
            checkpoint_id="c2",
            **ai,
        )
        await s.flush()
        u2b = msg("user", a1.id, 4)
        await s.flush()
        a2b = msg(
            "ai",
            u2b.id,
            5,
            streaming_status="completed",
            checkpoint_thread_id="T2",
            checkpoint_id="c3",
            **ai,
        )
        await s.commit()
        return {"conversation_id": conv.id, "a1": a1.id, "a2": a2.id, "a2b": a2b.id}


def _task(conv_id: str, client_id: str = CLIENT_ID, **over: Any) -> dict[str, Any]:
    task = {
        "task_id": "task-1",
        "conversation_id": conv_id,
        "client_id": client_id,
        "parent_task_id": None,
        "root_run_id": None,
        "branch_thread_id": "T",
        "spawned_by_message_id": None,
        "depth": 1,
        "name": "researcher",
        "subagent_path": "researcher",
        "description": "dig",
        "model": "gpt-4.1",
        "status": "running",
        "result_preview": None,
        "error": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "started_at": (_now() - timedelta(seconds=90)).isoformat() + "Z",
        "settled_at": None,
    }
    task.update(over)
    return task


def _outbox(conv_id: str, client_id: str = CLIENT_ID, **over: Any) -> OutboxItem:
    item = {
        "task_id": "task-1",
        "client_id": client_id,
        "conversation_id": conv_id,
        "branch_thread_id": "T",
        "root_run_id": None,
        "agent_slug": "test-agent",
        "interactive": True,
        "status": "success",
        "cancelled_by_user": False,
        "notification": {
            "content": [{"type": "text", "text": "researcher finished: 42"}],
            "additional_kwargs": {"lc_source": "async_subagent", "task_id": "task-1"},
        },
    }
    item.update(over)
    return OutboxItem.model_validate(item)


def _wire_item(item: OutboxItem) -> dict[str, Any]:
    """An outbox item as the agents service sends it (``client_id`` included)."""
    return {**item.model_dump(mode="json"), "client_id": item.client_id}


async def _apply(session_factory, event: str, task: dict[str, Any]) -> Any:
    entry = TaskStatusEntry.model_validate({"event": event, "task": task})
    return await async_tasks.apply_status_entry(entry, session_factory=session_factory)


async def _channel(conversation_id: str) -> list[dict[str, Any]]:
    client = await conversation_channel._get_client()
    entries = await client.xrange(channel_key(conversation_id))
    return [json.loads(fields["payload"]) for _id, fields in entries]


# ---------------------------------------------------------------------------
# The mirror
# ---------------------------------------------------------------------------
async def test_a_status_entry_is_mirrored_and_announced(session_factory):
    ids = await _branchy_conversation(session_factory)
    assert await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"]))

    async with session_factory() as s:
        row = await s.get(ConversationTaskTable, "task-1")
        assert (row.status, row.name, row.depth, row.client_id) == (
            "running",
            "researcher",
            1,
            CLIENT_ID,
        )
    frames = await _channel(ids["conversation_id"])
    assert frames[-1]["type"] == "task" and frames[-1]["event"] == "TASK_STARTED"
    assert frames[-1]["task"]["task_id"] == "task-1"
    # The client id is a capability: it never goes back out on a frame.
    assert "client_id" not in frames[-1]["task"]


async def test_a_task_naming_another_clients_conversation_is_never_mirrored(session_factory):
    ids = await _branchy_conversation(session_factory)
    other = "33333333-3333-4333-8333-333333333333"
    assert (
        await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"], other)) is None
    )
    async with session_factory() as s:
        assert await s.get(ConversationTaskTable, "task-1") is None
    assert await _channel(ids["conversation_id"]) == []


async def test_a_settle_captures_the_coalesced_events(session_factory):
    ids = await _branchy_conversation(session_factory)
    client = await task_streams._get_client()
    for delta in ("Hel", "lo"):
        event = {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": delta}
        await client.xadd(task_events_key("task-1"), {"data": json.dumps(event)})
    settled = _task(ids["conversation_id"], status="success", settled_at=_now().isoformat() + "Z")
    await _apply(session_factory, "TASK_SETTLED", settled)

    async with session_factory() as s:
        row = await s.get(ConversationTaskTable, "task-1")
        assert row.raw_events == [
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "Hello", "seq": 2}
        ]
        assert row.settled_at is not None


async def test_the_list_route_serves_the_tree_to_its_owner(client, session_factory):
    ids = await _branchy_conversation(session_factory)
    for task_id, parent, depth in (("t-root", None, 1), ("t-child", "t-root", 2)):
        await _apply(
            session_factory,
            "TASK_STARTED",
            _task(ids["conversation_id"], task_id=task_id, parent_task_id=parent, depth=depth),
        )
    resp = await client.get(f"/v1/conversations/{ids['conversation_id']}/tasks")
    assert resp.status_code == 200
    assert [(t["task_id"], t["parent_task_id"]) for t in resp.json()] == [
        ("t-root", None),
        ("t-child", "t-root"),
    ]
    assert all("client_id" not in t for t in resp.json())
    assert (await client.get("/v1/conversations/not-mine/tasks")).status_code == 404


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------
async def test_the_status_consumer_acks_handled_and_malformed_entries(session_factory):
    ids = await _branchy_conversation(session_factory)
    redis = await task_streams._get_client()
    await task_streams.ensure_group(STATUS_STREAM)
    entry = {"event": "TASK_STATUS", "task": _task(ids["conversation_id"])}
    await redis.xadd(STATUS_STREAM, {"data": json.dumps(entry)})
    await redis.xadd(STATUS_STREAM, {"data": "not json"})

    consumers = TaskConsumers()
    entries = await task_streams.read_group(
        STATUS_STREAM, "c1", pending=False, count=10, block_ms=None
    )
    assert len(entries) == 2
    assert await consumers.process(STATUS_STREAM, entries, handle_status_entry) == 2
    assert (await redis.xpending(STATUS_STREAM, CONSUMER_GROUP))["pending"] == 0
    async with session_factory() as s:
        assert (await s.get(ConversationTaskTable, "task-1")).status == "running"


async def test_a_database_failure_leaves_the_entry_pending(monkeypatch):
    async def down(_entry, **_kw):
        raise OperationalError("SELECT 1", {}, Exception("down"))

    monkeypatch.setattr(task_consumers_module, "apply_status_entry", down)
    assert await handle_status_entry("1-0", {"event": "TASK_STATUS", "task": _task("c")}) is False


async def test_an_outbox_entry_schedules_a_wake_up_and_is_acked(monkeypatch):
    woken: list[str] = []

    async def wake(item, _session_factory=None):
        woken.append(item.task_id)
        return WakeOutcome.WOKEN

    monkeypatch.setattr(task_consumers_module, "handle_outbox_item", wake)
    consumers = TaskConsumers()
    assert await consumers.handle_outbox_entry("1-0", _wire_item(_outbox("c"))) is True
    assert await consumers.handle_outbox_entry("2-0", {"nope": 1}) is True
    await asyncio.gather(*consumers._wakes)
    assert woken == ["task-1"]


# ---------------------------------------------------------------------------
# Wake-up
# ---------------------------------------------------------------------------
def test_the_branch_leaf_is_the_newest_answer_on_the_tasks_thread():
    t0 = _now()
    rows = [
        MessageTable(id="a1", sender="ai", checkpoint_thread_id="T", created_at=t0),
        MessageTable(
            id="a2", sender="ai", checkpoint_thread_id="T", created_at=t0 + timedelta(seconds=5)
        ),
        MessageTable(
            id="b", sender="ai", checkpoint_thread_id="T2", created_at=t0 + timedelta(seconds=9)
        ),
        MessageTable(id="u", sender="user", created_at=t0 + timedelta(seconds=10)),
    ]
    assert find_branch_leaf(rows, "T").id == "a2"
    assert find_branch_leaf(rows, "missing") is None


async def test_a_settled_task_wakes_the_orchestrator_on_its_own_branch(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    settled = _task(ids["conversation_id"], status="success", settled_at=_now().isoformat() + "Z")
    await _apply(session_factory, "TASK_SETTLED", settled)
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))

    outcome = await handle_outbox_item(_outbox(ids["conversation_id"]), session_factory)

    assert outcome is WakeOutcome.WOKEN
    assert len(launched) == 1
    async with session_factory() as s:
        notice = await s.scalar(
            select(MessageTable).where(MessageTable.kind == "task_notification")
        )
        # The user is on the edit branch (a2b is newer); the wake-up still goes to T.
        assert notice.parent_message_id == ids["a2"]
        assert (notice.sender, notice.content) == ("user", "researcher finished: 42")
        assert notice.task_notice["name"] == "researcher"
        assert notice.task_notice["duration_ms"] > 0
        run = await s.get(MessageTable, launched[0])
        assert run.parent_message_id == notice.id
        assert run.checkpoint_thread_id == "T"
        assert (await s.get(ConversationTaskTable, "task-1")).notified_at is not None
    marks = agents_service.called("POST", "/tasks/task-1/notified")
    assert [json.loads(m.content) for m in marks] == [{"client_id": CLIENT_ID}]
    frames = await _channel(ids["conversation_id"])
    assert frames[-1]["type"] == "run_started" and frames[-1]["run"]["id"] == launched[0]
    assert frames[-1]["from_queue"] is False


async def test_the_wake_up_run_sends_the_notice_as_the_orchestrators_next_input(
    session_factory, agents_service
):
    ids = await _branchy_conversation(session_factory)
    agents_service.on("GET", "/tasks/task-1", httpx.Response(404))
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Reported.", checkpoint_id="c9")))

    assert await handle_outbox_item(_outbox(ids["conversation_id"]), session_factory) is (
        WakeOutcome.WOKEN
    )
    async with session_factory() as s:
        run_id = await s.scalar(
            select(MessageTable.id)
            .where(MessageTable.streaming_status.is_not(None))
            .order_by(MessageTable.created_at.desc())
        )
    run = await finished(run_id, session_factory)

    assert (run.streaming_status, run.content, run.checkpoint_id) == (
        "completed",
        "Reported.",
        "c9",
    )
    body = json.loads(agents_service.called("POST", STREAM_PATH)[0].content)
    # A delta resume on the task's branch thread: only the notice goes.
    assert body["config"]["run_config"]["configurable"]["thread_id"] == "T"
    assert body["config"]["context"]["client_id"] == CLIENT_ID
    [sent] = body["messages"]
    # The notification's own content blocks go back, so the HumanMessage is exact.
    assert sent["role"] == "user"
    assert sent["content"] == [{"type": "text", "text": "researcher finished: 42"}]
    assert sent["kind"] == "task_notification"
    assert sent["additional_kwargs"] == {"lc_source": "async_subagent", "task_id": "task-1"}


async def test_a_busy_conversation_leaves_the_task_unnotified(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    async with session_factory() as s:
        s.add(
            MessageTable(
                conversation_id=ids["conversation_id"],
                sender="ai",
                parent_message_id=ids["a2b"],
                streaming_status="running",
                streaming_started_at=_now(),
            )
        )
        await s.commit()
    agents_service.on("GET", "/tasks/task-1", httpx.Response(404))

    outcome = await handle_outbox_item(_outbox(ids["conversation_id"]), session_factory)

    assert outcome is WakeOutcome.BUSY
    assert launched == []
    assert agents_service.called("POST", "/tasks/task-1/notified") == []
    async with session_factory() as s:
        notices = (
            await s.scalars(select(MessageTable).where(MessageTable.kind == "task_notification"))
        ).all()
        assert notices == []


async def test_a_run_cap_retries_then_defers(
    session_factory, agents_service, launched, monkeypatch
):
    ids = await _branchy_conversation(session_factory)
    agents_service.on("GET", "/tasks/task-1", httpx.Response(404))
    monkeypatch.setattr(settings.rate_limit, "inference_max_active_runs", 0)
    attempts: list[str] = []
    real = task_wakeups._wake_once

    async def counted(item, factory):
        attempts.append(item.task_id)
        return await real(item, factory)

    monkeypatch.setattr(task_wakeups, "_wake_once", counted)
    outcome = await handle_outbox_item(_outbox(ids["conversation_id"]), session_factory)
    assert outcome is WakeOutcome.DEFERRED
    assert len(attempts) == settings.async_tasks.wake_retry_attempts + 1
    assert agents_service.called("POST", "/tasks/task-1/notified") == []


async def test_a_user_stop_never_wakes_but_is_marked_handled(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))
    item = _outbox(ids["conversation_id"], status="cancelled", cancelled_by_user=True)
    assert await handle_outbox_item(item, session_factory) is WakeOutcome.SKIPPED
    assert launched == []
    assert len(agents_service.called("POST", "/tasks/task-1/notified")) == 1


async def test_an_outbox_item_for_another_clients_conversation_wakes_nothing(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))
    other = "33333333-3333-4333-8333-333333333333"
    item = _outbox(ids["conversation_id"], client_id=other)
    assert await handle_outbox_item(item, session_factory) is WakeOutcome.SKIPPED
    assert launched == []
    async with session_factory() as s:
        assert (
            await s.scalar(select(MessageTable).where(MessageTable.kind == "task_notification"))
        ) is None


async def test_a_task_continued_after_a_user_stop_wakes_when_it_finishes(
    session_factory, agents_service, launched
):
    # The user stops it (no wake-up, marked handled); the orchestrator continues
    # it; it finishes: that new outcome must wake the orchestrator, whether the
    # "running again" entry arrives or is missed.
    ids = await _branchy_conversation(session_factory)
    conv_id = ids["conversation_id"]
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))
    stopped_at = _now() - timedelta(seconds=60)

    await _apply(
        session_factory,
        "TASK_SETTLED",
        _task(conv_id, status="cancelled", settled_at=stopped_at.isoformat() + "Z"),
    )
    stop = _outbox(conv_id, status="cancelled", cancelled_by_user=True)
    assert await handle_outbox_item(stop, session_factory) is WakeOutcome.SKIPPED
    async with session_factory() as s:
        assert (await s.get(ConversationTaskTable, "task-1")).notified_at is not None

    # The reopen entry is missed; only the new settle arrives.
    await _apply(
        session_factory,
        "TASK_SETTLED",
        _task(conv_id, status="success", settled_at=_now().isoformat() + "Z"),
    )
    async with session_factory() as s:
        assert (await s.get(ConversationTaskTable, "task-1")).notified_at is None
    assert await handle_outbox_item(_outbox(conv_id), session_factory) is WakeOutcome.WOKEN
    assert len(launched) == 1


async def test_a_repeated_settle_announcement_stays_handled(session_factory, agents_service):
    # The agents service re-announces a stopped task's settle: same settle
    # time, so the user's Stop stays handled (no wake-up).
    ids = await _branchy_conversation(session_factory)
    conv_id = ids["conversation_id"]
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))
    settled = (_now() - timedelta(seconds=5)).isoformat() + "Z"
    for attempt in range(2):
        await _apply(
            session_factory, "TASK_SETTLED", _task(conv_id, status="cancelled", settled_at=settled)
        )
        if attempt == 0:
            await handle_outbox_item(
                _outbox(conv_id, status="cancelled", cancelled_by_user=True), session_factory
            )
    async with session_factory() as s:
        assert (await s.get(ConversationTaskTable, "task-1")).notified_at is not None


def test_the_notice_reaches_the_agent_with_its_kwargs_and_the_ui_without_them():
    notice = MessageTable(
        id="n",
        sender="user",
        content="done",
        kind="task_notification",
        task_notice={
            "task_id": "t",
            "name": "r",
            "status": "success",
            "duration_ms": 5,
            "agent_kwargs": {"lc_source": "async_subagent"},
        },
        created_at=_now(),
        updated_at=_now(),
    )
    assert serialise_message_for_agent(notice, InlineBudget()) == {
        "id": "n",
        "role": "user",
        "content": "done",
        "attachments": [],
        "kind": "task_notification",
        "additional_kwargs": {"lc_source": "async_subagent"},
    }
    out = MessageOut.model_validate(notice).model_dump(mode="json")
    assert out["kind"] == "task_notification"
    assert out["taskNotice"] == {"task_id": "t", "name": "r", "status": "success", "duration_ms": 5}


# ---------------------------------------------------------------------------
# Run end: queued message first, else one wake-up
# ---------------------------------------------------------------------------
def _queued(after_run_id: str, content: str = "and also this", age_minutes: int = 0) -> dict:
    return {
        "content": content,
        "agent_slug": "test-agent",
        "agent_name": "Test Agent",
        "queued_at": (_now() - timedelta(minutes=age_minutes)).isoformat(),
        "after_run_id": after_run_id,
    }


async def _settled_mirror_row(session_factory, conversation_id: str) -> None:
    async with session_factory() as s:
        s.add(
            ConversationTaskTable(
                task_id="task-1",
                conversation_id=conversation_id,
                client_id=CLIENT_ID,
                name="r",
                status="success",
                depth=1,
            )
        )
        await s.commit()


async def test_a_run_end_sends_the_queued_message_before_any_wake_up(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    async with session_factory() as s:
        (await s.get(ConversationTable, ids["conversation_id"])).queued_message = _queued(
            ids["a2b"]
        )
        await s.commit()
    await _settled_mirror_row(session_factory, ids["conversation_id"])

    await on_run_finished(ids["a2b"], session_factory)

    assert len(launched) == 1
    async with session_factory() as s:
        run = await s.get(MessageTable, launched[0])
        user_msg = await s.get(MessageTable, run.parent_message_id)
        assert (user_msg.content, user_msg.parent_message_id, user_msg.kind) == (
            "and also this",
            ids["a2b"],
            None,
        )
        assert (await s.get(ConversationTable, ids["conversation_id"])).queued_message is None
    # The queue went first: the agents service was not even asked.
    assert agents_service.calls == []
    frames = await _channel(ids["conversation_id"])
    assert frames[-2] == {"type": "queue", "queued_message": None}
    assert frames[-1]["type"] == "run_started" and frames[-1]["from_queue"] is True


async def test_a_run_end_wakes_once_for_an_unhandled_settle(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    await _settled_mirror_row(session_factory, ids["conversation_id"])
    unnotified = [
        _wire_item(_outbox(ids["conversation_id"])),
        _wire_item(_outbox(ids["conversation_id"], task_id="task-2")),
    ]
    agents_service.on("GET", "/tasks/unnotified", httpx.Response(200, json=unnotified))
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))

    await on_run_finished(ids["a2"], session_factory)

    assert len(launched) == 1  # once: the run it started pulls task-2
    request = agents_service.called("GET", "/tasks/unnotified")[0]
    assert request.url.params["conversation_id"] == ids["conversation_id"]
    assert request.url.params["client_id"] == CLIENT_ID


async def test_a_run_the_user_stopped_wakes_nothing_and_holds_the_pending_results(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    await _settled_mirror_row(session_factory, ids["conversation_id"])
    async with session_factory() as s:
        (await s.get(MessageTable, ids["a2"])).streaming_cancel_requested_at = _now()
        await s.commit()
    unnotified = [_wire_item(_outbox(ids["conversation_id"]))]
    agents_service.on("GET", "/tasks/unnotified", httpx.Response(200, json=unnotified))
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))

    await on_run_finished(ids["a2"], session_factory)

    assert launched == []  # stays stopped
    # Held for its next run, so the reconcile loop does not wake it either.
    assert len(agents_service.called("POST", "/tasks/task-1/notified")) == 1
    async with session_factory() as s:
        assert (await s.get(ConversationTaskTable, "task-1")).notified_at is not None


async def test_a_run_end_with_nothing_to_do_never_calls_the_agents_service(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    await on_run_finished(ids["a2"], session_factory)
    assert launched == [] and agents_service.calls == []


async def test_reconcile_sends_left_behind_queues_then_unnotified_settles(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    async with session_factory() as s:
        (await s.get(ConversationTable, ids["conversation_id"])).queued_message = _queued(
            ids["a2b"], content="hi", age_minutes=5
        )
        await s.commit()
    unnotified = [_wire_item(_outbox(ids["conversation_id"]))]
    agents_service.on("GET", "/tasks/unnotified", httpx.Response(200, json=unnotified))
    agents_service.on("GET", "/tasks/task-1", httpx.Response(404))

    await reconcile_once(session_factory)

    # The queued send started a run, so the wake-up found the conversation busy.
    assert len(launched) == 1
    assert agents_service.called("POST", "/tasks/task-1/notified") == []
    async with session_factory() as s:
        assert (await s.get(ConversationTable, ids["conversation_id"])).queued_message is None


async def test_reconcile_leaves_a_fresh_queued_message_to_its_run_end(
    session_factory, agents_service, launched
):
    ids = await _branchy_conversation(session_factory)
    async with session_factory() as s:
        (await s.get(ConversationTable, ids["conversation_id"])).queued_message = _queued(
            ids["a2b"]
        )
        await s.commit()
    agents_service.on("GET", "/tasks/unnotified", httpx.Response(200, json=[]))

    await reconcile_once(session_factory)

    assert launched == []
    async with session_factory() as s:
        assert (await s.get(ConversationTable, ids["conversation_id"])).queued_message is not None


# ---------------------------------------------------------------------------
# Routes, the busy flags and the drill-down
# ---------------------------------------------------------------------------
async def test_a_conversation_with_working_tasks_reads_busy_until_they_settle(
    client, session_factory
):
    ids = await _branchy_conversation(session_factory)
    conv_id = ids["conversation_id"]
    await _apply(
        session_factory,
        "TASK_SETTLED",
        _task(
            conv_id,
            task_id="t-old",
            spawned_by_message_id=ids["a2"],
            status="success",
            settled_at=_now().isoformat(),
        ),
    )
    await _apply(
        session_factory,
        "TASK_STARTED",
        _task(conv_id, task_id="t-live", spawned_by_message_id=ids["a2b"]),
    )

    listed = await client.get("/v1/conversations")
    summary = next(c for c in listed.json()["items"] if c["id"] == conv_id)
    assert summary["hasActiveTasks"] is True and summary["isStreaming"] is False
    detail = (await client.get(f"/v1/conversations/{conv_id}")).json()
    assert detail["hasActiveTasks"] is True
    assert detail["activeTaskMessageId"] == ids["a2b"]  # the working task's answer
    active = await client.get("/v1/tasks/active-conversations")
    assert active.status_code == 200 and active.json() == {"conversationIds": [conv_id]}

    await _apply(
        session_factory,
        "TASK_SETTLED",
        _task(
            conv_id,
            task_id="t-live",
            spawned_by_message_id=ids["a2b"],
            status="success",
            settled_at=_now().isoformat(),
        ),
    )
    detail = (await client.get(f"/v1/conversations/{conv_id}")).json()
    assert detail["hasActiveTasks"] is False and detail["activeTaskMessageId"] is None
    assert (await client.get("/v1/tasks/active-conversations")).json() == {"conversationIds": []}


async def test_stop_proxies_to_the_agents_service(client, session_factory, agents_service):
    ids = await _branchy_conversation(session_factory)
    await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"]))
    cancelled = _task(ids["conversation_id"], status="cancelled", settled_at=_now().isoformat())
    agents_service.on("POST", "/tasks/task-1/cancel", httpx.Response(200, json=cancelled))

    resp = await client.post("/v1/tasks/task-1/cancel")
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert "client_id" not in resp.json()
    sent = json.loads(agents_service.called("POST", "/tasks/task-1/cancel")[0].content)
    assert sent == {"client_id": CLIENT_ID, "reason": "user"}
    async with session_factory() as s:
        assert (await s.get(ConversationTaskTable, "task-1")).status == "cancelled"


async def test_a_task_not_yet_mirrored_is_authorised_through_the_agents_service(
    client, session_factory, agents_service
):
    ids = await _branchy_conversation(session_factory)
    upstream = _task(ids["conversation_id"], task_id="fresh")
    agents_service.on("GET", "/tasks/fresh", httpx.Response(200, json=upstream))
    agents_service.on(
        "POST", "/tasks/fresh/cancel", httpx.Response(200, json={**upstream, "status": "cancelled"})
    )
    resp = await client.post("/v1/tasks/fresh/cancel")
    assert resp.status_code == 200
    lookup = agents_service.called("GET", "/tasks/fresh")[0]
    assert lookup.url.params["client_id"] == CLIENT_ID


async def test_an_unreachable_task_service_is_a_502(client, session_factory, agents_service):
    agents_service.on("GET", "/tasks/x", httpx.Response(503))
    assert (await client.post("/v1/tasks/x/cancel")).status_code == 502


async def test_an_approval_needs_its_interrupt_and_goes_keyed_by_it(
    client, session_factory, agents_service
):
    ids = await _branchy_conversation(session_factory)
    await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"], status="waiting"))
    agents_service.on(
        "POST", "/tasks/task-1/resume", httpx.Response(200, json=_task(ids["conversation_id"]))
    )

    assert (
        await client.post("/v1/tasks/task-1/resume", json={"decision": "approve"})
    ).status_code == 422
    resp = await client.post(
        "/v1/tasks/task-1/resume", json={"decision": "approve", "interruptId": "int-1"}
    )
    assert resp.status_code == 200
    sent = json.loads(agents_service.called("POST", "/tasks/task-1/resume")[0].content)
    assert sent == {
        "client_id": CLIENT_ID,
        "decisions": {
            "int-1": {"decision": "approve", "reason": None, "value": None, "decisions": None}
        },
    }

    # The drill-down learns the approval was answered: the same resolved
    # marker a run's log gets, in the task's own event stream.
    redis = await task_streams._get_client()
    entries = await redis.xrange(task_events_key("task-1"))
    markers = [json.loads(fields["data"]) for _id, fields in entries]
    assert [m["name"] for m in markers] == ["BRIDGE_HITL_RESOLVED"]
    assert markers[0]["value"]["interrupt_id"] == "int-1"
    assert markers[0]["value"]["decision"] == "approve"


@pytest.mark.parametrize("upstream", [409, 422, 429])
async def test_an_upstream_refusal_keeps_its_status(
    client, session_factory, agents_service, upstream
):
    ids = await _branchy_conversation(session_factory)
    await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"]))
    agents_service.on("POST", "/tasks/task-1/resume", httpx.Response(upstream))
    body = {"decision": "approve", "interruptId": "int-1"}
    assert (await client.post("/v1/tasks/task-1/resume", json=body)).status_code == upstream


async def test_the_task_socket_serves_a_settled_node_from_the_mirror(session_factory):
    ids = await _branchy_conversation(session_factory)
    await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"], status="success"))
    async with session_factory() as s:
        (await s.get(ConversationTaskTable, "task-1")).raw_events = [{"type": "RUN_STARTED"}]
        await s.commit()
    frames = [
        f
        async for f in async_tasks.stream_task_events(
            CLIENT_ID, "task-1", None, session_factory=session_factory
        )
    ]
    assert [f["type"] for f in frames] == ["snapshot", "terminal"]
    assert frames[0]["events"] == [{"type": "RUN_STARTED"}]
    assert "client_id" not in frames[0]["task"]
    assert frames[1]["status"] == "success"


async def test_the_task_socket_tails_a_live_node_until_it_settles(session_factory):
    ids = await _branchy_conversation(session_factory)
    await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"]))
    redis = await task_streams._get_client()
    await redis.xadd(task_events_key("task-1"), {"data": json.dumps({"type": "STEP"})})
    frames: list[dict[str, Any]] = []

    async def read() -> None:
        async for frame in async_tasks.stream_task_events(
            CLIENT_ID, "task-1", None, session_factory=session_factory
        ):
            frames.append(frame)
            if frame["type"] == "event" and frame["event"]["type"] == "STEP":
                async with session_factory() as s:
                    (await s.get(ConversationTaskTable, "task-1")).status = "error"
                    await s.commit()
                await redis.xadd(task_events_key("task-1"), {"data": json.dumps({"type": "LAST"})})

    await asyncio.wait_for(read(), timeout=10)
    assert [f["type"] for f in frames] == ["snapshot", "event", "event", "terminal"]
    # A live snapshot carries the task but no `events`: the log follows as frames.
    assert "task" in frames[0] and "events" not in frames[0]
    assert [f["event"]["type"] for f in frames if f["type"] == "event"] == ["STEP", "LAST"]
    assert frames[-1] == {"type": "terminal", "status": "error"}


# ---------------------------------------------------------------------------
# Delete and fork
# ---------------------------------------------------------------------------
async def test_deleting_a_conversation_stops_its_tasks_and_drops_their_rows(
    client, session_factory, agents_service
):
    ids = await _branchy_conversation(session_factory)
    await _apply(session_factory, "TASK_STARTED", _task(ids["conversation_id"]))
    agents_service.on("POST", "/tasks/cancel-scope", httpx.Response(200, json={"cancelled": 1}))

    assert (await client.delete(f"/v1/conversations/{ids['conversation_id']}")).status_code == 204

    scope = json.loads(agents_service.called("POST", "/tasks/cancel-scope")[0].content)
    assert scope == {"client_id": CLIENT_ID, "conversation_id": ids["conversation_id"]}
    async with session_factory() as s:
        assert await s.get(ConversationTaskTable, "task-1") is None


async def test_deleting_a_conversation_without_tasks_never_calls_the_agents_service(
    client, session_factory, agents_service
):
    ids = await _branchy_conversation(session_factory)
    assert (await client.delete(f"/v1/conversations/{ids['conversation_id']}")).status_code == 204
    assert agents_service.calls == []


async def test_a_fork_keeps_the_notice_rows(client, session_factory, agents_service, launched):
    ids = await _branchy_conversation(session_factory)
    agents_service.on("GET", "/tasks/task-1", httpx.Response(404))
    agents_service.on("POST", "/tasks/task-1/notified", httpx.Response(204))
    await handle_outbox_item(_outbox(ids["conversation_id"]), session_factory)
    async with session_factory() as s:
        run = await s.get(MessageTable, launched[0])
        run.content, run.streaming_status = "Reported.", "completed"
        await s.commit()

    resp = await client.post(
        f"/v1/conversations/{ids['conversation_id']}/fork", json={"messageId": launched[0]}
    )
    assert resp.status_code == 201, resp.text
    forked = await client.get(f"/v1/conversations/{resp.json()['id']}")
    messages = forked.json()["messages"]
    notices = [m for m in messages if m["kind"] == "task_notification"]
    assert len(notices) == 1
    assert notices[0]["taskNotice"]["task_id"] == "task-1"
    assert "agent_kwargs" not in notices[0]["taskNotice"]
