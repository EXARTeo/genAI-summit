"""Waking the orchestrator when a background task's subtree settles.

The wake-up is an ordinary run started through the normal run engine, so it
streams, persists and checkpoints like any other.

1. Find the **leaf of the task's branch**: the newest answer on the task's
   ``branch_thread_id``, even if the user has since switched to another
   branch: the result belongs to the branch the task was started from.
2. Write the **notice row**: sender ``user`` (the orchestrator's input is a
   HumanMessage), ``kind = task_notification``, ``task_notice`` for the UI and
   the notification's ``additional_kwargs`` and original content blocks for
   the agents service, content = the notification's text. Then create a ``send`` run under it (a
   ``delta_resume`` on the same thread, so the orchestrator sees exactly the
   notification as its next input), launch it, and announce ``run_started``
   on the conversation channel.
3. **409** (the conversation is busy): nothing now. The active run's
   middleware pulls the result before its next model call; the run-end hook
   below re-checks once the slot is free.
4. **429** (the client's active-run cap): retried with exponential backoff, a
   bounded number of times; then the reconcile loop owns it.

The agents service is told the wake-up was handled (``POST
/tasks/{id}/notified``) only once the run exists, or once the wake-up was
deliberately skipped (the user stopped the task, the conversation is gone, no
branch to continue). Never on 409 or 429: an unnotified task is what the
safety nets look for.

**When a run ends** (:func:`on_run_finished`, a run-finished hook): the
conversation's **queued message goes first** (the user asked for it, and the
run it starts pulls any settled result before its first model call anyway).
Only when nothing was queued, or it could not be sent, is a pending wake-up
started, at most one: the run it starts pulls the others. A run the user
stopped wakes nothing: its pending results are held for its next run.

The **reconcile loop** (:func:`reconcile_once`, at startup and then every
``ASYNC_TASKS_RECONCILE_INTERVAL_SECONDS``) sends queued messages a restart
left behind, and works through ``GET /tasks/unnotified``: Redis is only the
doorbell; the agents service's ``parent_notified_at`` is the durable outbox.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    TASK_SETTLED_STATUSES,
    ConversationTable,
    ConversationTaskTable,
    MessageTable,
    SessionLocal,
)
from core.logging import get_logger
from core.settings import settings
from schema.inference import InferenceRunOut
from schema.tasks import OutboxItem
from utils.agents_tasks import (
    AgentsTaskError,
    agents_get_task,
    agents_list_unnotified,
    agents_mark_notified,
)
from utils.async_tasks import upsert_task_mirror
from utils.composer_queue import pending_queue_conversations, send_queued_message
from utils.conversation_channel import publish_run_started
from utils.inference_runs import (
    build_run_out_from_message,
    create_inference_run_record,
    inference_run_manager,
    load_run_message,
    mark_run_launch_failed,
    register_run_finished_hook,
)
from utils.validators import load_conversation_full

logger = get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]


class WakeOutcome(StrEnum):
    """What one wake-up attempt did."""

    WOKEN = "woken"  # a wake-up run was started
    SKIPPED = "skipped"  # deliberately not woken; the settle is handled
    BUSY = "busy"  # 409: the active run pulls the result
    DEFERRED = "deferred"  # 429 or the agents service unreachable: try later


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def find_branch_leaf(messages: list[MessageTable], branch_thread_id: str) -> MessageTable | None:
    """The newest answer on the branch thread ``branch_thread_id``, or None.

    Every run that continues a branch inherits its ``checkpoint_thread_id``
    (``send``), and an edit or retry mints a new one, so the newest AI message
    on the thread is the end of the branch the task was started from.
    """
    on_branch = [
        m for m in messages if m.sender == "ai" and m.checkpoint_thread_id == branch_thread_id
    ]
    if not on_branch:
        return None
    return max(on_branch, key=lambda m: (m.created_at, m.id))


def _duration_ms(row: ConversationTaskTable | None, now: datetime) -> int | None:
    """How long the task ran, for the notice row.

    The outbox entry can be consumed before the ``tasks:status`` entry that
    writes ``settled_at`` into the mirror (two independent streams), so a
    missing ``settled_at`` falls back to the wake-up time.
    """
    if row is None or row.started_at is None:
        return None
    settled = row.settled_at or now
    return max(0, int((settled - row.started_at).total_seconds() * 1000))


async def _wake_once(
    item: OutboxItem, session_factory: SessionFactory
) -> tuple[WakeOutcome, InferenceRunOut | None]:
    """One attempt at waking the orchestrator for ``item`` (see the module doc)."""
    if item.cancelled_by_user:
        # The user pressed Stop: they know already.
        return WakeOutcome.SKIPPED, None
    async with session_factory() as db:
        conversation = await db.scalar(
            select(ConversationTable).where(
                ConversationTable.id == item.conversation_id,
                ConversationTable.client_id == item.client_id,
            )
        )
        if conversation is None:
            return WakeOutcome.SKIPPED, None
        client_id, conversation_id = conversation.client_id, conversation.id

        mirror = await db.get(ConversationTaskTable, item.task_id)
        if mirror is not None and mirror.conversation_id != conversation_id:
            mirror = None  # never touch another conversation's row
        if mirror is not None and mirror.notified_at is not None:
            # Handled already; only the agents service's mark is missing.
            return WakeOutcome.SKIPPED, None
        if mirror is None:
            # The status stream has not delivered it yet: mirror it now, for
            # the notice's name and for the "handled" mark below.
            task = await agents_get_task(item.task_id, client_id)
            if task is not None:
                mirror = await upsert_task_mirror(db, task)

        full = await load_conversation_full(db, client_id, conversation_id)
        leaf = find_branch_leaf(list(full.messages), item.branch_thread_id)
        if leaf is None:
            logger.warning(
                "task_wake_no_branch",
                "No branch left to wake the orchestrator on",
                task_id=item.task_id,
                conversation_id=conversation_id,
            )
            return WakeOutcome.SKIPPED, None
        agent_slug = leaf.agent_slug or full.agent_slug
        agent_name = leaf.agent_name or full.agent_name

        now = _now()
        notice = MessageTable(
            conversation_id=conversation_id,
            parent_message_id=leaf.id,
            sender="user",
            content=item.notification_text(),
            kind="task_notification",
            task_notice={
                "task_id": item.task_id,
                "name": mirror.name if mirror is not None else (item.agent_slug or "task"),
                "status": item.status,
                "duration_ms": _duration_ms(mirror, now),
                "agent_kwargs": dict(item.notification.additional_kwargs),
                "agent_content": item.notification.content,
            },
            created_at=now,
        )
        db.add(notice)
        await db.flush()
        notice_id = notice.id
        if mirror is not None:
            mirror.notified_at = now
        db.expire(full, ["messages"])
        full = await load_conversation_full(db, client_id, conversation_id)
        try:
            run = await create_inference_run_record(
                db=db,
                client_id=client_id,
                conversation=full,
                parent_message_id=notice_id,
                message_path=None,
                agent_slug=agent_slug,
                agent_name=agent_name,
                mode="send",
            )
        except HTTPException as exc:
            await db.rollback()
            if exc.status_code == status.HTTP_409_CONFLICT:
                return WakeOutcome.BUSY, None
            if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                return WakeOutcome.DEFERRED, None
            logger.warning(
                "task_wake_refused",
                "The wake-up run was refused",
                task_id=item.task_id,
                status_code=exc.status_code,
            )
            return WakeOutcome.SKIPPED, None
        run_id = run.id
        await db.commit()
        run_message = await load_run_message(db, run_id)
        run_out = build_run_out_from_message(run_message)
    try:
        inference_run_manager.launch(run_id)
    except RuntimeError:
        logger.error("task_wake_launch_failed", "Wake-up run could not be launched", exc_info=True)
        await mark_run_launch_failed(run_id)
        return WakeOutcome.SKIPPED, None
    logger.info(
        "task_wake_started",
        "Orchestrator woken for a settled task",
        task_id=item.task_id,
        conversation_id=conversation_id,
        run_id=run_id,
    )
    await publish_run_started(run_out)
    return WakeOutcome.WOKEN, run_out


async def _mark_handled(item: OutboxItem, session_factory: SessionFactory) -> None:
    """Record the settle as handled: in the mirror, then in the agents service."""
    try:
        async with session_factory() as db:
            mirror = await db.get(ConversationTaskTable, item.task_id)
            if (
                mirror is not None
                and mirror.client_id == item.client_id
                and mirror.notified_at is None
            ):
                mirror.notified_at = _now()
                await db.commit()
    except SQLAlchemyError:
        logger.warning(
            "task_notified_mirror_failed",
            "Could not mark the mirrored task handled",
            task_id=item.task_id,
            exc_info=True,
        )
    try:
        if not await agents_mark_notified(item.task_id, item.client_id):
            logger.warning(
                "task_notified_refused",
                "The agents service did not record the notification",
                task_id=item.task_id,
            )
    except AgentsTaskError as exc:
        # The mirror's mark keeps it from waking twice; the reconcile loop
        # sends the mark again.
        logger.warning(
            "task_notified_failed",
            "Could not tell the agents service the task was handled",
            task_id=item.task_id,
            error_type=str(exc),
        )


async def handle_outbox_item(
    item: OutboxItem, session_factory: SessionFactory | None = None
) -> WakeOutcome:
    """Wake the orchestrator for one settled depth-1 task (429s retried with backoff)."""
    session_factory = session_factory or SessionLocal
    attempts = settings.async_tasks.wake_retry_attempts
    outcome = WakeOutcome.DEFERRED
    for attempt in range(attempts + 1):
        try:
            outcome, _run = await _wake_once(item, session_factory)
        except (AgentsTaskError, SQLAlchemyError) as exc:
            logger.warning(
                "task_wake_failed",
                "Wake-up deferred: a dependency failed",
                task_id=item.task_id,
                error_type=type(exc).__name__,
            )
            return WakeOutcome.DEFERRED
        if outcome is not WakeOutcome.DEFERRED or attempt == attempts:
            break
        await asyncio.sleep(settings.async_tasks.wake_retry_base_seconds * (2**attempt))
    if outcome in (WakeOutcome.WOKEN, WakeOutcome.SKIPPED):
        await _mark_handled(item, session_factory)
    elif outcome is WakeOutcome.DEFERRED:
        logger.info(
            "task_wake_deferred", "Wake-up deferred to the reconcile loop", task_id=item.task_id
        )
    return outcome


async def _unnotified_for(conversation_id: str, client_id: str) -> list[OutboxItem] | None:
    """The conversation's unhandled settles, or None when they cannot be listed."""
    try:
        return await agents_list_unnotified(
            settings.async_tasks.unnotified_limit,
            client_id=client_id,
            conversation_id=conversation_id,
        )
    except AgentsTaskError as exc:
        logger.warning(
            "task_unnotified_fetch_failed", "Could not list unnotified tasks", error_type=str(exc)
        )
        return None


async def wake_pending_for_conversation(
    conversation_id: str, client_id: str, session_factory: SessionFactory
) -> bool:
    """The run-end safety net: wake once if a settled depth-1 task of this
    conversation is still unhandled. True when a run was started.

    Cheap when there is nothing to do: the agents service is asked only when
    the mirror holds such a task.
    """
    async with session_factory() as db:
        candidates = await db.scalar(
            select(func.count())
            .select_from(ConversationTaskTable)
            .where(
                ConversationTaskTable.conversation_id == conversation_id,
                ConversationTaskTable.depth == 1,
                ConversationTaskTable.status.in_(TASK_SETTLED_STATUSES),
                ConversationTaskTable.notified_at.is_(None),
            )
        )
    if not candidates:
        return False
    for item in await _unnotified_for(conversation_id, client_id) or ():
        outcome = await handle_outbox_item(item, session_factory)
        if outcome is WakeOutcome.WOKEN:
            return True
        if outcome in (WakeOutcome.BUSY, WakeOutcome.DEFERRED):
            return False
    return False


async def hold_pending_wakeups(
    conversation_id: str, client_id: str, session_factory: SessionFactory
) -> int:
    """The user stopped the orchestrator: keep the results waiting for its
    next run instead of waking it at once. Returns how many were held.

    Each is marked handled, so neither the run-end safety net nor the
    reconcile loop starts the orchestrator again right after the Stop. Nothing
    is lost: its next run pulls every settled task it started.
    """
    items = await _unnotified_for(conversation_id, client_id) or []
    for item in items:
        await _mark_handled(item, session_factory)
    if items:
        logger.info(
            "task_wakeups_held",
            "The user stopped the orchestrator: pending wake-ups held for its next run",
            conversation_id=conversation_id,
            count=len(items),
        )
    return len(items)


async def on_run_finished(run_id: str, session_factory: SessionFactory) -> None:
    """After every run: the queued message first, else one pending wake-up;
    after a run the user stopped, the pending wake-ups are held instead."""
    async with session_factory() as db:
        run = await db.get(MessageTable, run_id)
        conversation = (
            await db.get(ConversationTable, run.conversation_id) if run is not None else None
        )
        if run is None or conversation is None:
            return
        conversation_id, client_id = conversation.id, conversation.client_id
        has_queued = conversation.queued_message is not None
        stopped_by_user = run.streaming_cancel_requested_at is not None
    if has_queued and await send_queued_message(
        conversation_id, after_run_id=run_id, session_factory=session_factory
    ):
        return
    if not settings.async_tasks.enabled:
        return
    if stopped_by_user:
        await hold_pending_wakeups(conversation_id, client_id, session_factory)
        return
    await wake_pending_for_conversation(conversation_id, client_id, session_factory)


register_run_finished_hook(on_run_finished)


async def reconcile_once(session_factory: SessionFactory | None = None) -> None:
    """One pass of the safety net: queued messages, then unnotified settles."""
    session_factory = session_factory or SessionLocal
    async with session_factory() as db:
        due = await pending_queue_conversations(
            db, older_than_seconds=settings.async_tasks.queue_sweep_after_seconds
        )
    for conversation_id in due:
        await send_queued_message(conversation_id, session_factory=session_factory)

    try:
        items = await agents_list_unnotified(settings.async_tasks.unnotified_limit)
    except AgentsTaskError as exc:
        logger.warning(
            "task_reconcile_fetch_failed", "Could not list unnotified tasks", error_type=str(exc)
        )
        return
    # One wake per conversation per pass: the run it starts pulls the rest.
    busy: set[str] = set()
    for item in items:
        if item.conversation_id in busy:
            continue
        outcome = await handle_outbox_item(item, session_factory)
        if outcome in (WakeOutcome.WOKEN, WakeOutcome.BUSY):
            busy.add(item.conversation_id)
    if items:
        logger.info("task_reconcile_done", "Reconciled unnotified tasks", count=len(items))
