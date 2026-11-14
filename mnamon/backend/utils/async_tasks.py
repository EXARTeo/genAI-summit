"""Background sub-agent tasks: the backend's mirror and the caller's actions.

The agents service owns and runs every task. The backend keeps
``conversation_tasks``, the mirror the UI's task tree is drawn from, fed by the
``tasks:status`` stream (utils/task_consumers.py), and proxies the caller's
actions on a task (stop, answer an approval) to the agents service's internal
task API (utils/agents_tasks.py). Waking the orchestrator lives in
utils/task_wakeups.py.

**Ownership.** A task is shown or touched only through a conversation the
caller owns: the mirror row carries the owning ``client_id``, and a status
entry whose conversation does not belong to the client it names is dropped,
never stored. Every agents-service call also names the client, and the agents
service answers 404 for another client's task. Every miss here is a 404.

**Settling.** When a task settles, its event stream is read once into
``raw_events`` (coalesced exactly like a run's), so a settled node still opens
after Redis expires the stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    TASK_SETTLED_STATUSES,
    ConversationTable,
    ConversationTaskTable,
    SessionLocal,
)
from core.logging import get_logger
from core.settings import settings
from schema.tasks import ActiveConversationsOut, TaskOut, TaskResumeIn, TaskStatusEntry
from utils.agents_tasks import (
    AgentsTaskError,
    agents_get_task,
    agents_task_action,
    task_from_response,
)
from utils.conversation_channel import publish_task_frame
from utils.inference_runs import (
    append_coalesced,
    hitl_resolved_value,
    overall_hitl_decision,
    truncate_tool_result,
)
from utils.task_streams import task_streams

logger = get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]

#: Conversations the sidebar's task poll returns, at most.
_ACTIVE_CONVERSATIONS_MAX = 200
#: A page of a task's event stream read at once.
_EVENTS_PAGE = 500


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime | None) -> datetime | None:
    """A datetime as the naive UTC every column here stores."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def _task_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")


def _upstream_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail="The task service is unavailable."
    )


# ---------------------------------------------------------------------------
# The mirror
# ---------------------------------------------------------------------------
def task_out_from_row(row: ConversationTaskTable) -> TaskOut:
    """A mirror row in the ``TaskOut`` wire shape."""
    return TaskOut.model_validate(
        {
            "task_id": row.task_id,
            "conversation_id": row.conversation_id,
            "client_id": row.client_id,
            "parent_task_id": row.parent_task_id,
            "root_run_id": row.root_run_id,
            "branch_thread_id": row.branch_thread_id,
            "spawned_by_message_id": row.spawned_by_message_id,
            "depth": row.depth or 1,
            "name": row.name,
            "subagent_path": row.subagent_path,
            "description": row.description,
            "model": row.model,
            "status": row.status,
            "result_preview": row.result_preview,
            "error": row.error,
            "usage": row.usage or {},
            "started_at": row.started_at,
            "settled_at": row.settled_at,
        }
    )


async def owned_conversation(
    db: AsyncSession, client_id: str, conversation_id: str
) -> ConversationTable | None:
    """The caller's conversation, or None."""
    return await db.scalar(
        select(ConversationTable).where(
            ConversationTable.id == conversation_id, ConversationTable.client_id == client_id
        )
    )


async def get_owned_task(
    db: AsyncSession, client_id: str, task_id: str
) -> ConversationTaskTable | None:
    """The caller's mirrored task, or None (another client's task is None too)."""
    return await db.scalar(
        select(ConversationTaskTable).where(
            ConversationTaskTable.task_id == task_id,
            ConversationTaskTable.client_id == client_id,
        )
    )


async def active_conversation_ids(db: AsyncSession, client_id: str) -> ActiveConversationsOut:
    """The caller's conversations whose background tasks are still working.

    The sidebar polls this while a row spins for tasks, so the row stops (or
    starts) spinning without the conversation being open. A streaming answer
    is not counted: the run socket already tracks it.
    """
    rows = await db.scalars(
        select(ConversationTable.id)
        .where(ConversationTable.client_id == client_id, ConversationTable.active_tasks_flag)
        .limit(_ACTIVE_CONVERSATIONS_MAX)
    )
    return ActiveConversationsOut(conversationIds=list(rows))


async def list_conversation_tasks(
    db: AsyncSession, client_id: str, conversation_id: str, limit: int
) -> list[TaskOut]:
    """The conversation's task tree, parents before children; 404 if it is
    not the caller's. ``limit`` is capped at ``ASYNC_TASKS_LIST_LIMIT_MAX``."""
    limit = min(limit, settings.async_tasks.list_limit_max)
    if await owned_conversation(db, client_id, conversation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    rows = await db.scalars(
        select(ConversationTaskTable)
        .where(ConversationTaskTable.conversation_id == conversation_id)
        # A parent starts before its children, so this is a valid tree order.
        .order_by(
            ConversationTaskTable.started_at.asc(),
            ConversationTaskTable.created_at.asc(),
            ConversationTaskTable.task_id.asc(),
        )
        .limit(limit)
    )
    return [task_out_from_row(row) for row in rows]


async def upsert_task_mirror(db: AsyncSession, task: TaskOut) -> ConversationTaskTable | None:
    """Write a task's current state into the mirror (in the caller's transaction).

    Refuses (returns None, stores nothing) a task whose conversation does not
    exist or does not belong to the client the task names: the agents service
    is trusted, but a mirror row is what every ownership check reads, so it
    must never be written across clients. ``raw_events`` and ``notified_at``
    are bookkeeping and left alone, except that a new outcome clears
    ``notified_at``.
    """
    conversation = await db.get(ConversationTable, task.conversation_id)
    if conversation is None or conversation.client_id != task.client_id:
        logger.warning(
            "task_mirror_refused",
            "Refused to mirror a task whose conversation is not its client's",
            task_id=task.task_id,
            conversation_id=task.conversation_id,
        )
        return None
    row = await db.get(ConversationTaskTable, task.task_id)
    if row is None:
        row = ConversationTaskTable(
            task_id=task.task_id, conversation_id=task.conversation_id, client_id=task.client_id
        )
        db.add(row)
    elif row.client_id != task.client_id or row.conversation_id != task.conversation_id:
        # A task id never moves between conversations or clients.
        logger.warning(
            "task_mirror_identity_mismatch",
            "Refused a task update that changes its owner",
            task_id=task.task_id,
        )
        return None
    row.parent_task_id = task.parent_task_id
    row.root_run_id = task.root_run_id
    row.branch_thread_id = task.branch_thread_id
    row.spawned_by_message_id = task.spawned_by_message_id
    row.depth = task.depth
    row.name = task.name
    row.subagent_path = task.subagent_path
    row.description = task.description
    row.model = task.model
    row.status = task.status
    row.result_preview = task.result_preview
    row.error = task.error
    row.usage = task.usage.model_dump()
    row.started_at = _naive_utc(task.started_at)
    row.settled_at = _naive_utc(task.settled_at)
    row.updated_at = _now()
    if not task.settled:
        # Re-opened (the orchestrator continued it): its next settle needs a
        # new wake-up.
        row.notified_at = None
    elif (
        row.notified_at is not None
        and row.settled_at is not None
        and row.settled_at > row.notified_at
    ):
        # A settle newer than the last handling is a new outcome (re-opened and
        # finished again, its "running" entry missed or late): it must wake the
        # orchestrator, not be skipped as handled.
        row.notified_at = None
    return row


async def capture_task_events(task_id: str) -> list[dict[str, Any]]:
    """Read a settled task's whole event stream, coalesced like a run's log.

    Bounded by ``ASYNC_TASKS_RAW_EVENTS_MAX``: past it the oldest events are
    dropped behind one ``TASK_EVENTS_TRUNCATED`` marker. An empty list when the
    stream is gone (Redis restarted, or its TTL ran out first).
    """
    log: list[dict[str, Any]] = []
    cursor = "0"
    seq = 0
    while True:
        page = await task_streams.task_events_after(task_id, cursor, count=_EVENTS_PAGE)
        for entry_id, event in page:
            cursor = entry_id
            if isinstance(event, dict) and event.get("type"):
                if event.get("type") == "TOOL_CALL_RESULT":
                    event = truncate_tool_result(event)
                # Numbered like a run's stored log, so the drill-down dedupes
                # the same way when it hydrates from it.
                seq += 1
                append_coalesced(log, {**event, "seq": seq})
        if len(page) < _EVENTS_PAGE:
            break
    limit = settings.async_tasks.raw_events_max
    if len(log) > limit:
        dropped = len(log) - (limit - 1)
        marker = {"type": "CUSTOM", "name": "TASK_EVENTS_TRUNCATED", "value": {"dropped": dropped}}
        log = [marker, *log[dropped:]]
    return log


async def apply_status_entry(
    entry: TaskStatusEntry, *, session_factory: SessionFactory | None = None
) -> TaskOut | None:
    """Mirror one ``tasks:status`` entry and announce it on the conversation.

    On a settle the task's events are captured in the same transaction as the
    status. Returns the mirrored task, or None when it was refused (not the
    client's conversation). Database errors propagate: the consumer then
    leaves the entry pending, to be tried again.
    """
    task = entry.task
    events = await capture_task_events(task.task_id) if task.settled else None
    async with (session_factory or SessionLocal)() as db:
        row = await upsert_task_mirror(db, task)
        if row is None:
            await db.rollback()
            return None
        if events:
            row.raw_events = events
        await db.commit()
    await publish_task_frame(entry.event, task)
    return task


# ---------------------------------------------------------------------------
# The caller's actions on a task (routes)
# ---------------------------------------------------------------------------
async def _authorised_task(db: AsyncSession, client_id: str, task_id: str) -> TaskOut:
    """The caller's task: the mirror first, else the agents service (a task
    the status stream has not delivered yet). 404 for anything else."""
    row = await get_owned_task(db, client_id, task_id)
    if row is not None:
        return task_out_from_row(row)
    try:
        task = await agents_get_task(task_id, client_id)
    except AgentsTaskError as exc:
        raise _upstream_unavailable() from exc
    if task is None or await owned_conversation(db, client_id, task.conversation_id) is None:
        raise _task_not_found()
    return task


async def _task_action(
    db: AsyncSession, client_id: str, task_id: str, action: str, body: dict[str, Any]
) -> TaskOut:
    """Proxy one action to the agents service and mirror the task it returns."""
    await _authorised_task(db, client_id, task_id)
    try:
        response = await agents_task_action(task_id, client_id, action, body)
    except AgentsTaskError as exc:
        raise _upstream_unavailable() from exc
    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise _task_not_found()
    if response.status_code == status.HTTP_409_CONFLICT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The task is not in a state that allows this.",
        )
    if response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The decision does not match the task's pending approval.",
        )
    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many background tasks are running. Try again shortly.",
        )
    bad_answer = HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail="The task service refused the request."
    )
    if response.status_code != status.HTTP_200_OK:
        raise bad_answer
    try:
        task = task_from_response(response)
    except AgentsTaskError as exc:
        raise bad_answer from exc
    if task.client_id != client_id or task.task_id != task_id:
        raise bad_answer
    if await upsert_task_mirror(db, task) is not None:
        await db.commit()
    return task


async def cancel_task_for_client(db: AsyncSession, client_id: str, task_id: str) -> TaskOut:
    """The Stop button: cancel the task and its whole subtree. A stop by the
    user never wakes the orchestrator (the user knows already)."""
    task = await _task_action(db, client_id, task_id, "cancel", {"reason": "user"})
    logger.info("task_cancel_requested", "Background task stop requested", task_id=task_id)
    return task


def _resume_item(payload: TaskResumeIn) -> dict[str, Any]:
    """One decision in the agents-service resume item shape (as a run's)."""
    return {
        "decision": payload.decision,
        "reason": payload.reason,
        "value": payload.value,
        "decisions": [d.model_dump() for d in payload.decisions] if payload.decisions else None,
    }


async def resume_task_for_client(
    db: AsyncSession, client_id: str, task_id: str, payload: TaskResumeIn
) -> TaskOut:
    """An approval decision for a ``waiting`` task, keyed by its interrupt."""
    item = _resume_item(payload)
    task = await _task_action(
        db, client_id, task_id, "resume", {"decisions": {payload.interruptId: item}}
    )
    # The same resolved marker a run's log gets, written into the task's own
    # event stream: without it the drill-down keeps showing the gated tool as
    # "Needs approval" after the task resumed and even settled.
    resume_payload = {"interrupt_id": payload.interruptId, **item}
    marker = {
        "type": "CUSTOM",
        "name": "BRIDGE_HITL_RESOLVED",
        "value": hitl_resolved_value(resume_payload, overall_hitl_decision(resume_payload)),
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
    }
    try:
        await task_streams.append_task_event(task_id, marker)
    except Exception as exc:  # noqa: BLE001 - the decision is applied; the marker is display state
        logger.warning(
            "task_hitl_marker_failed",
            "Could not record the task approval marker",
            task_id=task_id,
            error_type=type(exc).__name__,
        )
    logger.info(
        "task_resume_requested",
        "Background task approval sent",
        task_id=task_id,
        decision=payload.decision,
    )
    return task


# ---------------------------------------------------------------------------
# One task's live events (the drill-down socket)
# ---------------------------------------------------------------------------
async def stream_task_events(
    client_id: str,
    task_id: str,
    since: str | None,
    *,
    session_factory: SessionFactory | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """The frames of ``WS /v1/tasks/{task_id}/ws``.

    ``snapshot`` first (the task, plus its stored ``events`` when it has
    settled and no ``since`` was given: the Redis stream may be gone), then
    one ``event`` frame per live event with its stream id as ``seq``, then
    ``terminal`` once the task has settled and every event is out. Yields
    nothing for a task that is not the caller's.
    """

    async def load() -> ConversationTaskTable | None:
        async with (session_factory or SessionLocal)() as db:
            return await get_owned_task(db, client_id, task_id)

    row = await load()
    if row is None:
        return
    snapshot: dict[str, Any] = {
        "type": "snapshot",
        "task": task_out_from_row(row).model_dump(mode="json"),
    }
    stored = row.raw_events if isinstance(row.raw_events, list) else None
    if row.status in TASK_SETTLED_STATUSES and since is None and stored is not None:
        yield {**snapshot, "events": stored}
        yield {"type": "terminal", "status": row.status}
        return
    yield snapshot

    cursor = since or "0"
    block_ms = settings.async_tasks.task_ws_block_ms
    while True:
        entries = await task_streams.task_events_wait(task_id, cursor, block_ms=block_ms)
        for entry_id, event in entries:
            cursor = entry_id
            if isinstance(event, dict):
                yield {"type": "event", "seq": entry_id, "event": event}
        if entries:
            continue
        # Quiet: has it settled? Then send what is left and close.
        row = await load()
        if row is None:
            return
        if row.status in TASK_SETTLED_STATUSES:
            while page := await task_streams.task_events_after(task_id, cursor):
                for entry_id, event in page:
                    cursor = entry_id
                    if isinstance(event, dict):
                        yield {"type": "event", "seq": entry_id, "event": event}
            yield {"type": "terminal", "status": row.status}
            return
