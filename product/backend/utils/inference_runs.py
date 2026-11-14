"""The run engine: detached agent runs, their event log, cancel and HITL resume.

A *run* is the assistant message being produced (its id is the run id; its
lifecycle is the message's ``streaming_*`` columns: queued → running →
completed | cancelled | failed, with cancelling in between). A start request
creates the placeholder (:func:`create_inference_run_record`) and
:class:`InferenceRunManager` runs it as an asyncio task that outlives the HTTP
request and the browser:

1. it builds the agents-service request from the conversation branch
   (delta resume, fork or full cold seed against the branch's durable
   checkpoint thread) and opens the run's Langfuse trace (``utils/tracing.py``);
2. it consumes the AG-UI SSE stream (``utils/agents.py``), folds every event
   into :class:`InferenceRunRuntime` and appends one ``events`` frame per
   network chunk to the run's Redis stream (``utils/event_log.py``), which
   WebSocket subscribers replay and tail (:func:`stream_run_events`);
3. on HITL interrupts it stays paused until ``/resume`` decisions arrive
   (``utils/hitl_decisions.py``), then streams the resume legs;
4. at the end it writes the message (content, reasoning, raw events, error,
   checkpoint head, generated files), publishes the terminal frame and calls
   the run-finished hooks (the composer queue sends its queued message).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import (
    AttachmentTable,
    BlobTable,
    ConversationTable,
    MessageTable,
    SessionLocal,
)
from core.logging import get_logger
from core.settings import settings
from schema.conversations import ConversationSummary
from schema.inference import InferenceRunOut
from schema.messages import MessageOut
from utils.agents import (
    AgentsServiceError,
    agent_event_batches,
    agent_resume_url,
    agent_stream_url,
    resume_body,
)
from utils.conversations import _preview
from utils.event_log import event_log
from utils.hitl_decisions import (
    EXPIRED_DECISION,
    EXPIRED_REASON,
    HitlDecisionQueue,
    ResumeOutcome,
    StaleDecisions,
    stale_decisions_from_conflict,
)
from utils.inference import (
    InlineBudget,
    nearest_committed_ai,
    prepare_inference_history,
    resolve_inference_message_path,
    serialise_message_for_agent,
)
from utils.tracing import RunTrace, start_run_trace
from utils.validators import load_conversation_full

ACTIVE_RUN_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_RUN_STATUSES = {"completed", "cancelled", "failed"}
STALE_QUEUED_RUN_AFTER = timedelta(minutes=2)
SNAPSHOT_SEQ_SENTINEL = "__snapshot__"

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _run_query(client_id: str) -> Select[tuple[MessageTable]]:
    """Runs (assistant messages with a streaming status) of one client's conversations."""
    return (
        select(MessageTable)
        .join(ConversationTable, ConversationTable.id == MessageTable.conversation_id)
        .where(ConversationTable.client_id == client_id, MessageTable.streaming_status.is_not(None))
    )


async def get_run_for_client(db: AsyncSession, client_id: str, run_id: str) -> MessageTable | None:
    """The run ``run_id`` when it belongs to one of the client's conversations."""
    return await db.scalar(_run_query(client_id).where(MessageTable.id == run_id))


async def list_runs_for_client(
    db: AsyncSession, client_id: str, status_filter: str | None
) -> list[MessageTable]:
    """The client's runs, newest first; ``active`` = queued/running/cancelling."""
    stmt = _run_query(client_id)
    if status_filter == "active":
        stmt = stmt.where(MessageTable.streaming_status.in_(ACTIVE_RUN_STATUSES))
    elif status_filter:
        stmt = stmt.where(MessageTable.streaming_status == status_filter)
    result = await db.execute(stmt.order_by(MessageTable.streaming_started_at.desc()))
    return list(result.scalars().all())


def hitl_resolved_value(resume_payload: dict[str, Any], decision: str) -> dict[str, Any]:
    """The ``BRIDGE_HITL_RESOLVED`` marker's value for one resume.

    Persisted in the event log so a reloaded client knows the pause was
    resolved and how; an ``ask_user`` reply also carries its ``answers``.
    """
    marker: dict[str, Any] = {
        "interrupt_id": resume_payload.get("interrupt_id"),
        "decision": decision,
        "reason": resume_payload.get("reason"),
        "decisions": resume_payload.get("decisions"),
    }
    value = resume_payload.get("value")
    if isinstance(value, dict) and isinstance(value.get("answers"), list):
        marker["answers"] = value["answers"]
    return marker


def overall_hitl_decision(resume_payload: dict[str, Any]) -> str:
    """The scalar decision of one resume (approve when any action was approved)."""
    decisions = resume_payload.get("decisions")
    if decisions:
        return "approve" if any(d.get("decision") == "approve" for d in decisions) else "reject"
    return resume_payload.get("decision", "approve")


_TEXT_DELTA_TYPES = {"TEXT_MESSAGE_CHUNK", "TEXT_MESSAGE_CONTENT"}


def _coalesce_key(event: dict[str, Any]) -> tuple[Any, ...] | None:
    """Merge identity of delta-bearing events: consecutive stored events with
    the same key collapse into one with a concatenated ``delta``.

    Thinking deltas are deliberately not coalesced: each is one discrete
    thought step, and merging them would collapse steps on reload that the
    live stream showed separately.
    """
    event_type = event.get("type")
    if event_type in _TEXT_DELTA_TYPES:
        return ("text", event.get("messageId"), repr(event.get("namespace")))
    if event_type == "TOOL_CALL_ARGS":
        return ("tool_args", event.get("toolCallId"))
    return None


def _merge_delta_into(last: dict[str, Any], incoming: dict[str, Any]) -> bool:
    key = _coalesce_key(incoming)
    if key is None or key != _coalesce_key(last):
        return False
    last["delta"] = str(last.get("delta") or "") + str(incoming.get("delta") or "")
    if incoming.get("timestamp") is not None:
        last["timestampEnd"] = incoming["timestamp"]
    return True


def truncate_tool_result(event: dict[str, Any]) -> dict[str, Any]:
    """Cap an oversized tool result, live and stored (flagged ``truncated``).

    Image results are exempt: the agents service already bounded them, and
    cutting a base64 string mid-way only makes it undecodable.
    """
    content = event.get("content")
    if not isinstance(content, str):
        return event
    limit = settings.inference.tool_result_max_chars
    if len(content) <= limit or "preview_base64" in content:
        return event
    return {**event, "content": content[:limit], "truncated": True}


def append_coalesced(log: list[dict[str, Any]], event: dict[str, Any]) -> None:
    """Append ``event`` to a stored AG-UI log, merging consecutive deltas.

    Text and tool-argument deltas of the same message / call collapse into one
    event (``timestampEnd`` keeps the last one's time); ``SUBAGENT_EVENT``
    envelopes merge one level down, on the same ``task_id``. A copy is stored,
    never the caller's dict.
    """
    stored = deepcopy(event)
    if log:
        last = log[-1]
        if _merge_delta_into(last, stored):
            last["seq"] = stored.get("seq", last.get("seq"))
            return
        if (
            last.get("type") == "CUSTOM"
            and stored.get("type") == "CUSTOM"
            and last.get("name") == "SUBAGENT_EVENT"
            and stored.get("name") == "SUBAGENT_EVENT"
        ):
            last_value, stored_value = last.get("value"), stored.get("value")
            if (
                isinstance(last_value, dict)
                and isinstance(stored_value, dict)
                and last_value.get("task_id") == stored_value.get("task_id")
                and isinstance(last_value.get("event"), dict)
                and isinstance(stored_value.get("event"), dict)
                and _merge_delta_into(last_value["event"], stored_value["event"])
            ):
                last["seq"] = stored.get("seq", last.get("seq"))
                if stored.get("timestamp") is not None:
                    last["timestampEnd"] = stored["timestamp"]
                return
    log.append(stored)


class InferenceRunRuntime:
    """The in-process state of one live run, folded from its AG-UI events."""

    def __init__(self) -> None:
        self.content = ""
        self.thoughts: list[str] = []
        self.raw_events: list[dict[str, Any]] = []
        self.first_event_ts = 0.0
        self.thinking_start = 0.0
        self.thinking_end = 0.0
        self.closed_thinking_on_first_chunk = False
        self.next_seq = 0
        # Outstanding HITL interrupts, by ``interrupt.id``, never a bare
        # counter: a sub-agent's interrupt arrives twice (top-level and wrapped
        # in SUBAGENT_EVENT) while one resume resolves it once.
        self.pending_interrupt_ids: list[str] = []
        # The durable checkpoint head the agent committed (CHECKPOINT_COMMITTED),
        # stored on the message so the branch's next turn resumes from it.
        self.produced_checkpoint_id: str | None = None
        # Files the agent presented with inline bytes (PRESENT_ARTIFACT), by
        # path; persisted as generated attachments when the run ends.
        self.generated_files: dict[str, dict[str, Any]] = {}
        # The run's Langfuse root observation (a no-op when tracing is off).
        self.trace = RunTrace()

    @property
    def pending_interrupts(self) -> int:
        return len(self.pending_interrupt_ids)

    def register_interrupt(self, value: Any) -> None:
        wrapped = value.get("interrupt") if isinstance(value, dict) else None
        raw_id = wrapped.get("id") if isinstance(wrapped, dict) else None
        token = str(raw_id) if raw_id is not None else f"anon-{self.next_seq}"
        if token not in self.pending_interrupt_ids:
            self.pending_interrupt_ids.append(token)

    def resolve_interrupt(self, interrupt_id: Any) -> None:
        token = str(interrupt_id) if interrupt_id is not None else None
        if token and token in self.pending_interrupt_ids:
            self.pending_interrupt_ids.remove(token)
        elif self.pending_interrupt_ids:
            self.pending_interrupt_ids.pop(0)

    def _take_presented_file(self, event: dict[str, Any]) -> dict[str, Any]:
        """Keep a PRESENT_ARTIFACT's inline bytes for the run's end and return
        the event without them (the bytes never go to Redis or ``raw_events``).

        Bounded like uploads: per file ``ATTACHMENT_MAX_SIZE_BYTES``, per run
        ``ATTACHMENT_MAX_TOTAL_BYTES`` and ``ATTACHMENT_MAX_PER_MESSAGE`` files.
        """
        value = event.get("value")
        if not isinstance(value, dict) or "data_base64" not in value:
            return event
        stripped = {**event, "value": {k: v for k, v in value.items() if k != "data_base64"}}
        path = str(value.get("path") or value.get("filename") or value.get("artifact_id") or "")
        try:
            data = base64.b64decode(str(value["data_base64"]), validate=True)
        except (binascii.Error, ValueError):
            data = None
        others = sum(len(f["data"]) for p, f in self.generated_files.items() if p != path)
        fits = (
            data is not None
            and path
            and len(data) <= settings.attachments.max_size_bytes
            and others + len(data) <= settings.attachments.max_total_bytes
            and (
                path in self.generated_files
                or len(self.generated_files) < settings.attachments.max_per_message
            )
        )
        if not fits:
            logger.warning(
                "generated_file_dropped",
                "A presented file was invalid or over the attachment limits; not stored",
                size_bytes=len(data) if data is not None else None,
            )
            return stripped
        self.generated_files[path] = {
            "data": data,
            "file_name": str(value.get("filename") or path.rsplit("/", 1)[-1])[:255],
            "mime_type": str(value.get("mime") or "application/octet-stream")[:200],
            "title": (str(value["title"])[:300] if value.get("title") else None),
            "summary": (str(value["summary"])[:2000] if value.get("summary") else None),
        }
        return stripped

    def thinking_duration_seconds(self) -> int | None:
        if not (self.thinking_start or self.first_event_ts):
            return None
        start = self.first_event_ts or self.thinking_start
        end = self.thinking_end or time.perf_counter()
        return max(0, round(end - start))

    def apply_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Fold one upstream event into the run and return the seq-stamped
        event for the delta frame, or None for one that is captured but never
        stored or streamed (``CHECKPOINT_COMMITTED``).

        Every other event lands in ``raw_events`` (the durable log the UI
        replays into its timeline), deltas coalesced; ``content`` and
        ``thoughts`` are aggregates for previews and search.
        """
        event_type = event.get("type")
        if not self.first_event_ts:
            self.first_event_ts = time.perf_counter()
        self.next_seq += 1

        if event_type == "TOOL_CALL_RESULT":
            event = truncate_tool_result(event)
        elif event_type == "CUSTOM" and event.get("name") == "SUBAGENT_EVENT":
            value = event.get("value")
            inner = value.get("event") if isinstance(value, dict) else None
            if isinstance(inner, dict) and inner.get("type") == "TOOL_CALL_RESULT":
                truncated = truncate_tool_result(inner)
                if truncated is not inner:
                    event = {**event, "value": {**value, "event": truncated}}
        elif event_type == "CUSTOM" and event.get("name") == "PRESENT_ARTIFACT":
            event = self._take_presented_file(event)
        event = {**event, "seq": self.next_seq}

        if event_type == "CUSTOM":
            name = event.get("name")
            value = event.get("value")
            if name == "SUBAGENT_EVENT" and isinstance(value, dict):
                inner = value.get("event")
                if (
                    isinstance(inner, dict)
                    and inner.get("type") == "CUSTOM"
                    and inner.get("name") == "HITL_INTERRUPT"
                ):
                    self.register_interrupt(inner.get("value"))
            elif name == "HITL_INTERRUPT":
                self.register_interrupt(value)
            elif name == "CHECKPOINT_COMMITTED":
                # Internal backend<->agent metadata: capture the head, never
                # store or stream it (it carries internal thread ids).
                if isinstance(value, dict) and value.get("checkpoint_id"):
                    self.produced_checkpoint_id = str(value["checkpoint_id"])
                return None
        elif event_type == "THINKING_START":
            self.thinking_start = time.perf_counter()
            self.thinking_end = 0.0
        elif event_type == "THINKING_TEXT_MESSAGE_CONTENT":
            self.thoughts.append(str(event.get("delta") or ""))
        elif event_type == "TOOL_CALL_START":
            self.thoughts.append(f"[tool] {event.get('toolCallName') or 'tool'}")
        elif event_type == "THINKING_END":
            self.thinking_end = time.perf_counter()
        elif event_type in _TEXT_DELTA_TYPES:
            self.content += str(event.get("delta") or "")
            if not self.closed_thinking_on_first_chunk:
                self.closed_thinking_on_first_chunk = True
                self.thinking_end = time.perf_counter()

        append_coalesced(self.raw_events, event)
        return event


#: Called after every run's terminal frame with ``(run_id, session_factory)``.
RunFinishedHook = Callable[[str, Callable[[], AsyncSession]], Awaitable[None]]
_run_finished_hooks: list[RunFinishedHook] = []


def register_run_finished_hook(hook: RunFinishedHook) -> None:
    """Call ``hook(run_id, session_factory)`` after every run's terminal frame.

    A registry rather than an import, because the hooks' modules (the composer
    queue) start runs through this one. ``session_factory`` is this module's
    ``SessionLocal`` at call time. A hook that raises is logged; the others run.
    """
    if hook not in _run_finished_hooks:
        _run_finished_hooks.append(hook)


async def _run_finished(run_id: str) -> None:
    for hook in list(_run_finished_hooks):
        try:
            await hook(run_id, SessionLocal)
        except Exception:
            logger.error(
                "run_finished_hook_failed",
                "A run-finished hook failed",
                exc_info=True,
                run_id=run_id,
            )


def _upstream_failure(exc: Exception, *, resume: bool) -> str:
    """The user-facing error of a run the agents service refused or dropped."""
    if isinstance(exc, AgentsServiceError):
        if exc.status_code == 404:
            return "This agent is not available."
        if exc.status_code == 409 and resume:
            return "The agent has no paused checkpoint for this run. Start a new message instead."
        if resume:
            return "Inference run could not be resumed."
        return f"The agents service refused the run ({exc.status_code})."
    return "The agents service could not be reached."


class InferenceRunManager:
    """Owns the asyncio tasks of this process's live runs."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        # Live state for WebSocket subscribers: a late subscriber gets one
        # snapshot built from the runtime instead of replaying the stream.
        self._runtimes: dict[str, InferenceRunRuntime] = {}
        self._run_metas: dict[str, dict[str, Any]] = {}
        # HITL: a per-run wake-up event and the decisions queued per interrupt.
        # Both live exactly as long as the run's task.
        self._resume_events: dict[str, asyncio.Event] = {}
        self._resume_queues: dict[str, HitlDecisionQueue] = {}

    def launch(self, run_id: str) -> None:
        """Start the run's task (a no-op when it is already running)."""
        if run_id in self._tasks and not self._tasks[run_id].done():
            return
        cancel_event = asyncio.Event()
        self._cancel_events[run_id] = cancel_event
        self._resume_events[run_id] = asyncio.Event()
        self._resume_queues[run_id] = HitlDecisionQueue()
        task = asyncio.create_task(self._run(run_id, cancel_event))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._forget(run_id))

    def _forget(self, run_id: str) -> None:
        for registry in (
            self._tasks,
            self._cancel_events,
            self._runtimes,
            self._run_metas,
            self._resume_events,
            self._resume_queues,
        ):
            registry.pop(run_id, None)

    def request_cancel(self, run_id: str) -> bool:
        event = self._cancel_events.get(run_id)
        if event:
            event.set()
            return True
        return False

    def request_resume(self, run_id: str, payload: dict[str, Any]) -> ResumeOutcome:
        """Queue one HITL decision for a live run and wake its task.

        Accepted only for an interrupt the run is paused on right now (or the
        first undecided one when the payload names none); decisions arriving
        while a resume leg streams wait in the queue. See
        :class:`utils.hitl_decisions.HitlDecisionQueue` for every refusal.
        """
        event = self._resume_events.get(run_id)
        queue = self._resume_queues.get(run_id)
        runtime = self._runtimes.get(run_id)
        if event is None or queue is None or runtime is None or not self.has_live_task(run_id):
            return ResumeOutcome.NOT_PAUSED
        outcome, _token = queue.offer(payload, runtime.pending_interrupt_ids)
        if outcome is ResumeOutcome.ACCEPTED:
            event.set()
        return outcome

    def has_live_task(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return bool(task and not task.done())

    def build_live_snapshot(self, run_id: str) -> dict[str, Any] | None:
        """A snapshot frame for an in-flight run of this process (full
        coalesced log + run meta), or None (other process, or ended)."""
        runtime = self._runtimes.get(run_id)
        run_meta = self._run_metas.get(run_id)
        if runtime is None or run_meta is None or not self.has_live_task(run_id):
            return None
        return {
            "type": "snapshot",
            "run": {
                **run_meta,
                "updatedAt": _now().isoformat(),
                "pendingInterrupts": runtime.pending_interrupts,
                "rawEvents": deepcopy(runtime.raw_events),
            },
            "message": None,
            "summary": None,
        }

    async def publish_run_status(self, run: MessageTable) -> None:
        """A status-only frame for a lifecycle flip outside the stream loop
        (a cancel moving the run to cancelling/cancelled)."""
        frame = {
            "type": "events",
            "events": [],
            "run": build_run_out_from_message(run).model_dump(mode="json"),
        }
        await self.publish(run.id, frame)

    async def publish(self, run_id: str, frame: dict[str, Any]) -> None:
        """Append a frame to the run's Redis stream; a failure is logged, never
        raised — losing one live frame beats crashing the run."""
        try:
            await event_log.append(run_id, frame)
        except Exception:
            logger.error(
                "event_log_publish_failed",
                "Failed to append inference event to Redis stream",
                exc_info=True,
                run_id=run_id,
            )

    async def _prepare(
        self, run_id: str, runtime: InferenceRunRuntime
    ) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
        """Mark the run running and build ``(run_meta, agent_slug, stream body)``.

        Returns None when the run is gone or no longer active.
        """
        async with SessionLocal() as db:
            run = await _load_run(db, run_id)
            if not run or run.streaming_status not in ACTIVE_RUN_STATUSES:
                return None
            run.streaming_status = "running"
            run.updated_at = _now()
            await db.commit()

        async with SessionLocal() as db:
            run = await _load_run(db, run_id)
            conv_row = await db.get(ConversationTable, run.conversation_id) if run else None
            if run is None or conv_row is None:
                return None
            client_id = conv_row.client_id
            conversation = await load_conversation_full(db, client_id, run.conversation_id)
            agent_slug = run.agent_slug or conversation.agent_slug
            started_at = run.streaming_started_at or run.created_at
            run_meta: dict[str, Any] = {
                "id": run.id,
                "conversationId": run.conversation_id,
                "assistantMessageId": run.id,
                "parentMessageId": run.parent_message_id,
                "status": "running",
                "agentSlug": agent_slug,
                "agentName": run.agent_name or conversation.agent_name,
                "messagePath": run.streaming_message_path or [],
                "startedAt": started_at.isoformat(),
                "updatedAt": started_at.isoformat(),
                "errorMessage": None,
                "completedAt": None,
                "cancelRequestedAt": None,
            }

            # How to feed the agent against its durable checkpoint thread:
            #   delta_resume — the branch thread already has committed state
            #     (a `send` continuing the leaf): only the new message;
            #   delta_fork — a fresh branch thread (edit/retry) whose fork
            #     point is a committed ancestor: the new message + fork_from;
            #   full_seed — nothing committed to resume or fork from: the
            #     whole branch, seeding a fresh checkpoint.
            thread_id = run.checkpoint_thread_id or str(run.id)
            parent_user_message = next(
                (m for m in conversation.messages if m.id == run.parent_message_id), None
            )
            ancestor = nearest_committed_ai(conversation.messages, run.parent_message_id)
            fork_from: dict[str, str] | None = None
            if parent_user_message is not None and ancestor is not None:
                if ancestor.checkpoint_thread_id == thread_id:
                    payload_mode = "delta_resume"
                else:
                    payload_mode = "delta_fork"
                    fork_from = {
                        "thread_id": ancestor.checkpoint_thread_id,
                        "checkpoint_id": ancestor.checkpoint_id,
                    }
                history = [serialise_message_for_agent(parent_user_message, InlineBudget())]
            else:
                payload_mode = "full_seed"
                history = prepare_inference_history(
                    conversation.messages, run.streaming_message_path
                )

            runtime.trace = start_run_trace(
                run_id=run.id,
                conversation_id=run.conversation_id,
                client_id=client_id,
                agent_slug=agent_slug,
                user_text=parent_user_message.content if parent_user_message is not None else None,
            )
            logger.info(
                "inference_run_started",
                "Detached inference run started",
                run_id=run.id,
                conversation_id=run.conversation_id,
                agent_slug=agent_slug,
                thread_id=thread_id,
                payload_mode=payload_mode,
                forked=fork_from is not None,
                sent_messages=len(history),
                traced=runtime.trace.active,
            )

        # Shared by /stream and every /resume leg: thread_id keys the durable
        # checkpointer (branch-scoped); run_id is this run.
        config: dict[str, Any] = {
            "run_config": {"configurable": {"thread_id": thread_id}},
            "context": {
                "client_id": client_id,
                "conversation_id": str(run_meta["conversationId"]),
                "run_id": run_id,
            },
        }
        if fork_from is not None:
            config["fork_from"] = fork_from
        trace_context = runtime.trace.upstream_context()
        if trace_context is not None:
            config["trace"] = trace_context
        return run_meta, agent_slug, {"messages": history, "config": config}

    async def _run(self, run_id: str, cancel_event: asyncio.Event) -> None:
        runtime = InferenceRunRuntime()
        self._runtimes[run_id] = runtime
        try:
            prepared = await self._prepare(run_id, runtime)
            if prepared is None:
                return
            run_meta, agent_slug, request_payload = prepared
            self._run_metas[run_id] = run_meta
            base_config: dict[str, Any] = request_payload["config"]
            resume_url = agent_resume_url(agent_slug)

            cancel_waiter = asyncio.create_task(cancel_event.wait())
            stream_task: asyncio.Task[str] = asyncio.create_task(
                self._do_stream(
                    run_id, run_meta, runtime, agent_stream_url(agent_slug), request_payload
                )
            )
            # The decisions of the resume leg in flight, kept until it ends: a
            # stale refusal puts back the ones the agent can still take.
            inflight: list[tuple[str, dict[str, Any]]] = []
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {stream_task, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED
                    )
                    # Cancellation wins outright: kill the HTTP stream.
                    if cancel_waiter in done and stream_task not in done:
                        stream_task.cancel()
                        await asyncio.gather(stream_task, return_exceptions=True)
                        await self._end(run_id, runtime, "cancelled")
                        return

                    if not stream_task.cancelled():
                        exc = stream_task.exception()
                        if isinstance(exc, StaleDecisions):
                            if not await self._recover_from_stale(
                                run_id, run_meta, runtime, inflight, exc
                            ):
                                return
                        elif exc:
                            raise exc
                        elif stream_task.result() == "failed":
                            return  # the leg already ended the run
                    inflight = []

                    if cancel_event.is_set():
                        await self._end(run_id, runtime, "cancelled")
                        return
                    if runtime.pending_interrupts <= 0:
                        await self._end(run_id, runtime, "completed")
                        return

                    ready = await self._await_decisions(run_id, runtime, cancel_waiter)
                    if ready is None:
                        await self._end(run_id, runtime, "cancelled")
                        return
                    await self._publish_resolutions(run_id, run_meta, runtime, ready)
                    inflight = list(ready)
                    stream_task = asyncio.create_task(
                        self._do_resume(
                            run_id,
                            run_meta,
                            runtime,
                            resume_url,
                            base_config,
                            [payload for _token, payload in ready],
                        )
                    )
            finally:
                if not cancel_waiter.done():
                    cancel_waiter.cancel()
                    await asyncio.gather(cancel_waiter, return_exceptions=True)
        except asyncio.CancelledError:
            await self._end(run_id, runtime, "cancelled")
        except Exception:
            logger.error(
                "inference_run_failed",
                "Detached inference run failed",
                exc_info=True,
                run_id=run_id,
            )
            await self._end(run_id, runtime, "failed", "The agent stream ended unexpectedly.")
        finally:
            self._cancel_events.pop(run_id, None)

    async def _await_decisions(
        self, run_id: str, runtime: InferenceRunRuntime, cancel_waiter: asyncio.Task[Any]
    ) -> list[tuple[str, dict[str, Any]]] | None:
        """Hold the paused run until decisions are ready; None when cancelled.

        Decisions that arrived while the last leg streamed go out at once. The
        queue is checked right after the event is cleared, with no await in
        between, so a decision can never slip past the wait.
        """
        resume_event = self._resume_events[run_id]
        queue = self._resume_queues[run_id]
        # A pause on an interrupt already answered is a new question.
        queue.forget_answered(runtime.pending_interrupt_ids)
        logger.info(
            "inference_run_awaiting_resume",
            "Run paused on HITL interrupt; awaiting resume signal",
            run_id=run_id,
            pending_interrupts=runtime.pending_interrupts,
            queued_decisions=len(queue),
        )
        batch = settings.inference.batch_hitl_resume
        ready = queue.take_ready(runtime.pending_interrupt_ids, batch=batch)
        while not ready:
            resume_event.clear()
            resume_waiter = asyncio.create_task(resume_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {resume_waiter, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                if not resume_waiter.done():
                    resume_waiter.cancel()
                    await asyncio.gather(resume_waiter, return_exceptions=True)
            if cancel_waiter in done:
                return None
            ready = queue.take_ready(runtime.pending_interrupt_ids, batch=batch)
        return ready

    async def _publish_resolutions(
        self,
        run_id: str,
        run_meta: dict[str, Any],
        runtime: InferenceRunRuntime,
        ready: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Resolve the interrupts being answered and log a durable
        ``BRIDGE_HITL_RESOLVED`` marker for each, so a reloaded client never
        re-offers an answered approval."""
        markers: list[dict[str, Any]] = []
        for token, payload in ready:
            runtime.resolve_interrupt(token)
            marker = runtime.apply_event(
                {
                    "type": "CUSTOM",
                    "name": "BRIDGE_HITL_RESOLVED",
                    "value": hitl_resolved_value(payload, overall_hitl_decision(payload)),
                    "timestamp": int(time.time() * 1000),
                }
            )
            if marker is not None:
                markers.append(marker)
        await self._publish_delta(run_id, run_meta, runtime, markers)
        logger.info(
            "inference_run_resume_dispatched",
            "Dispatching resume to agents service",
            run_id=run_id,
            interrupt_ids=[payload.get("interrupt_id") for _token, payload in ready],
            batched=len(ready),
        )

    async def _consume(
        self,
        run_id: str,
        run_meta: dict[str, Any],
        runtime: InferenceRunRuntime,
        url: str,
        body: dict[str, Any],
        failure: str,
    ) -> str:
        """Stream one leg into the runtime and the event log.

        Returns ``"failed"`` when the agent sent ``RUN_ERROR`` (the run is then
        already ended), else ``"completed"`` — which only means the leg ended.
        """
        async with aclosing(agent_event_batches(url, body)) as batches:
            async for events in batches:
                applied: list[dict[str, Any]] = []
                for event in events:
                    stamped = runtime.apply_event(event)
                    if stamped is not None:
                        applied.append(stamped)
                    if event.get("type") == "RUN_ERROR":
                        await self._publish_delta(run_id, run_meta, runtime, applied)
                        await self._end(
                            run_id, runtime, "failed", str(event.get("message") or failure)
                        )
                        return "failed"
                if applied:
                    await self._publish_delta(run_id, run_meta, runtime, applied)
        return "completed"

    async def _do_stream(
        self,
        run_id: str,
        run_meta: dict[str, Any],
        runtime: InferenceRunRuntime,
        agent_url: str,
        request_payload: dict[str, Any],
    ) -> str:
        """The first leg: ``POST /agents/{slug}/stream``."""
        try:
            return await self._consume(
                run_id, run_meta, runtime, agent_url, request_payload, "Agent stream failed."
            )
        except (AgentsServiceError, httpx.HTTPError) as exc:
            logger.warning(
                "agents_stream_failed",
                "The agents service refused or dropped the run",
                run_id=run_id,
                status_code=getattr(exc, "status_code", None),
                error_type=type(exc).__name__,
            )
            await self._end(run_id, runtime, "failed", _upstream_failure(exc, resume=False))
            return "failed"

    async def _do_resume(
        self,
        run_id: str,
        run_meta: dict[str, Any],
        runtime: InferenceRunRuntime,
        resume_url: str,
        base_config: dict[str, Any],
        resume_payloads: list[dict[str, Any]],
    ) -> str:
        """A resume leg: ``POST /agents/{slug}/resume`` with one decision, or a
        batch keyed by interrupt id. A 409 naming stale interrupts raises
        :class:`StaleDecisions` (recoverable); any other error fails the run."""
        try:
            return await self._consume(
                run_id,
                run_meta,
                runtime,
                resume_url,
                resume_body(base_config, resume_payloads),
                "Agent resume failed.",
            )
        except AgentsServiceError as exc:
            if exc.status_code == 409:
                stale = stale_decisions_from_conflict(exc.body)
                if stale is not None:
                    raise stale from exc
            await self._end(run_id, runtime, "failed", _upstream_failure(exc, resume=True))
            return "failed"
        except httpx.HTTPError as exc:
            await self._end(run_id, runtime, "failed", _upstream_failure(exc, resume=True))
            return "failed"

    async def _recover_from_stale(
        self,
        run_id: str,
        run_meta: dict[str, Any],
        runtime: InferenceRunRuntime,
        inflight: list[tuple[str, dict[str, Any]]],
        stale: StaleDecisions,
    ) -> bool:
        """Recover from a resume refused over stale interrupts (nothing applied).

        A decision for an interrupt the agent no longer has gets an ``expired``
        marker; the others go back in the queue. An interrupt the backend waits
        on that the agent no longer lists is voided too. Returns True when the
        run stays paused; otherwise it ends here — completed when the agent has
        nothing paused, failed when it waits on approvals this run does not know.
        """
        queue = self._resume_queues.get(run_id)
        stale_ids = set(stale.stale_ids)
        agent_pending = set(stale.pending_ids)

        def gone(token: str) -> bool:
            if token in stale_ids or not agent_pending:
                return True
            return not token.startswith("anon-") and token not in agent_pending

        voided: list[str] = []
        restored: list[str] = []
        for token, payload in inflight:
            if gone(token):
                voided.append(token)
            elif queue is not None:
                queue.restore(token, payload)
                restored.append(token)
        for token in list(runtime.pending_interrupt_ids):
            if gone(token):
                runtime.resolve_interrupt(token)
                if queue is not None:
                    queue.discard(token)
                voided.append(token)
        runtime.pending_interrupt_ids = restored + [
            t for t in runtime.pending_interrupt_ids if t not in restored
        ]

        markers = [
            marker
            for token in dict.fromkeys(voided)
            if (
                marker := runtime.apply_event(
                    {
                        "type": "CUSTOM",
                        "name": "BRIDGE_HITL_RESOLVED",
                        "value": {
                            "interrupt_id": token,
                            "decision": EXPIRED_DECISION,
                            "reason": EXPIRED_REASON,
                            "decisions": None,
                        },
                        "timestamp": int(time.time() * 1000),
                    }
                )
            )
            is not None
        ]
        if markers:
            await self._publish_delta(run_id, run_meta, runtime, markers)
        logger.warning(
            "inference_run_resume_stale",
            "Agents service refused stale interrupts; voided them and queued the rest again",
            run_id=run_id,
            stale_interrupt_ids=sorted(stale_ids),
            voided_interrupt_ids=list(dict.fromkeys(voided)),
            requeued_interrupt_ids=restored,
            pending_interrupts=runtime.pending_interrupts,
        )
        if runtime.pending_interrupts > 0:
            return True
        if not agent_pending:
            await self._end(run_id, runtime, "completed")
        else:
            await self._end(
                run_id,
                runtime,
                "failed",
                "The agent's pending approvals no longer match this run. "
                "Start a new message instead.",
            )
        return False

    async def _end(
        self, run_id: str, runtime: InferenceRunRuntime, status_value: str, error: str | None = None
    ) -> None:
        """Write the run's final state and publish the terminal frame."""
        await _finish_run(run_id, runtime, status_value, error)
        await self._publish_snapshot(run_id, "terminal")

    async def _publish_delta(
        self,
        run_id: str,
        run_meta: dict[str, Any],
        runtime: InferenceRunRuntime,
        events: list[dict[str, Any]],
    ) -> None:
        """Publish the new seq-stamped events of one chunk (O(chunk), not O(run))."""
        if not events:
            return
        frame = {
            "type": "events",
            "run": {
                **run_meta,
                "updatedAt": _now().isoformat(),
                "pendingInterrupts": runtime.pending_interrupts,
            },
            "events": events,
        }
        await self.publish(run_id, frame)

    async def _publish_snapshot(self, run_id: str, event_type: str) -> None:
        async with SessionLocal() as db:
            payload = await build_run_event_payload(db, run_id, event_type)
        if payload:
            await self.publish(run_id, payload)
        if event_type == "terminal":
            # Reconnects can replay for the TTL; then the database is the record.
            try:
                await event_log.mark_terminal(run_id)
            except Exception:
                logger.warning(
                    "event_log_mark_terminal_failed",
                    "Failed to set terminal TTL on Redis stream",
                    exc_info=True,
                    run_id=run_id,
                )
            await _run_finished(run_id)


inference_run_manager = InferenceRunManager()


async def _load_run(db: AsyncSession, run_id: str) -> MessageTable | None:
    """The assistant message that is run ``run_id``."""
    return await db.scalar(select(MessageTable).where(MessageTable.id == run_id))


async def load_run_message(db: AsyncSession, message_id: str) -> MessageTable | None:
    """A message with its attachments, ready for :class:`MessageOut`."""
    return await db.scalar(
        select(MessageTable)
        .options(selectinload(MessageTable.attachments).selectinload(AttachmentTable.blob))
        .where(MessageTable.id == message_id)
        .execution_options(populate_existing=True)
    )


def _store_generated_files(
    db: AsyncSession, run: MessageTable, runtime: InferenceRunRuntime
) -> None:
    """Persist the files the agent presented with inline bytes as generated
    attachments of the answer, in the run's final transaction."""
    for item in runtime.generated_files.values():
        data: bytes = item["data"]
        db.add(
            AttachmentTable(
                message_id=run.id,
                file_name=item["file_name"],
                mime_type=item["mime_type"],
                size_bytes=len(data),
                origin="generated",
                title=item["title"],
                summary=item["summary"],
                content_sha256=hashlib.sha256(data).hexdigest(),
                blob=BlobTable(data=data),
            )
        )


async def _finish_run(
    run_id: str, runtime: InferenceRunRuntime, status_value: str, error_message: str | None = None
) -> None:
    """Write a run's terminal state onto its message (once) and close its trace."""
    async with SessionLocal() as db:
        run = await _load_run(db, run_id)
        if not run:
            return
        if run.streaming_status in TERMINAL_RUN_STATUSES:
            runtime.trace.finish(status=run.streaming_status, output=run.content)
            return
        # A cancel requested mid-flight wins over a "completed" verdict.
        if status_value == "completed" and (
            run.streaming_status == "cancelling" or run.streaming_cancel_requested_at is not None
        ):
            status_value, error_message = "cancelled", None

        is_error = status_value == "failed"
        now = _now()
        run.streaming_status = status_value
        run.streaming_completed_at = now
        run.content = runtime.content or (
            "An error occurred while generating the response." if is_error else ""
        )
        run.reasoning_steps = deepcopy(runtime.thoughts) or None
        run.reasoning_time_seconds = runtime.thinking_duration_seconds()
        run.raw_events = deepcopy(runtime.raw_events)
        run.is_error = is_error
        run.error_message = error_message
        # Advance the branch head only when the agent reported one.
        if runtime.produced_checkpoint_id:
            run.checkpoint_id = runtime.produced_checkpoint_id
        run.updated_at = now
        _store_generated_files(db, run, runtime)

        conversation = await db.get(ConversationTable, run.conversation_id)
        if conversation:
            if conversation.active_assistant_message_id == run.id:
                conversation.active_assistant_message_id = None
            preview = _preview(run.content)
            if preview:
                conversation.last_message_preview = preview
            conversation.last_message_at = now
            conversation.updated_at = now
        content = run.content
        await db.commit()
    runtime.trace.finish(status=status_value, output=content, error=error_message)


async def mark_run_launch_failed(run_id: str) -> None:
    """Fail a run whose task could not be started."""
    await _finish_run(
        run_id, InferenceRunRuntime(), "failed", "Inference run could not be launched."
    )


def build_run_out_from_message(message: MessageTable) -> InferenceRunOut:
    """The wire :class:`InferenceRunOut` of a run's message row."""
    started = message.streaming_started_at or message.created_at
    return InferenceRunOut(
        id=message.id,
        conversationId=message.conversation_id,
        assistantMessageId=message.id,
        parentMessageId=message.parent_message_id,
        status=message.streaming_status or "completed",
        agentSlug=message.agent_slug,
        agentName=message.agent_name,
        messagePath=message.streaming_message_path or [],
        content=message.content,
        thinking=message.reasoning_steps,
        rawEvents=message.raw_events or [],
        errorMessage=message.error_message,
        startedAt=started,
        completedAt=message.streaming_completed_at,
        cancelRequestedAt=message.streaming_cancel_requested_at,
        updatedAt=message.updated_at,
    )


async def build_run_event_payload(
    db: AsyncSession, run_id: str, event_type: str
) -> dict[str, Any] | None:
    """A ``snapshot`` / ``terminal`` frame built from the database: the run, its
    message (with attachments) and the conversation's sidebar summary."""
    message = await load_run_message(db, run_id)
    if not message:
        return None
    conversation = await db.get(ConversationTable, message.conversation_id)
    return {
        "type": event_type,
        "run": build_run_out_from_message(message).model_dump(mode="json"),
        "message": MessageOut.model_validate(message).model_dump(mode="json"),
        "summary": (
            ConversationSummary.model_validate(conversation).model_dump(mode="json")
            if conversation
            else None
        ),
    }


async def stream_run_events(
    run_id: str, since: str | None = None
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``(seq, frame)`` pairs of a run for a WebSocket subscriber.

    * Terminal run: one database-built snapshot, then return.
    * Fresh subscribe (``since`` None) on a run live in this process: one
      synthesized snapshot (the full coalesced log), then the live tail from
      the stream position taken *before* the snapshot — frames published in
      between appear in both; the client's per-event ``seq`` dedupes them.
    * Reconnect (``since`` given) or no live runtime here: plain replay.

    Snapshot frames carry :data:`SNAPSHOT_SEQ_SENTINEL`, never a ``since``.
    """
    async with SessionLocal() as db:
        run = await _load_run(db, run_id)
        if run and run.streaming_status in TERMINAL_RUN_STATUSES:
            snapshot = await build_run_event_payload(db, run_id, "snapshot")
            if snapshot:
                yield (SNAPSHOT_SEQ_SENTINEL, snapshot)
            return

    cursor = since
    if cursor is None:
        last_entry_id = await event_log.last_entry_id(run_id)
        live_snapshot = inference_run_manager.build_live_snapshot(run_id)
        if live_snapshot is not None:
            yield (SNAPSHOT_SEQ_SENTINEL, live_snapshot)
            cursor = last_entry_id

    async def _run_went_terminal() -> bool:
        # The escape hatch when the terminal frame never reaches this reader.
        async with SessionLocal() as idle_db:
            status_value = await idle_db.scalar(
                select(MessageTable.streaming_status).where(MessageTable.id == run_id)
            )
        return status_value is None or status_value in TERMINAL_RUN_STATUSES

    async for entry_id, frame in event_log.read_since(
        run_id,
        cursor or "0",
        terminal_statuses=TERMINAL_RUN_STATUSES,
        on_idle=_run_went_terminal,
    ):
        yield (entry_id, frame)


def _is_active_run_integrity_conflict(exc: IntegrityError) -> bool:
    text = str(exc.orig).lower()
    return any(
        marker in text
        for marker in (
            "uq_messages_one_active_stream_per_conversation",
            "messages.conversation_id",
            "messages_conversation_id",
        )
    )


async def _fail_stale_queued_runs_for_conversation(db: AsyncSession, conversation_id: str) -> None:
    """Fail runs stuck in ``queued`` longer than :data:`STALE_QUEUED_RUN_AFTER`
    that no task of this process owns."""
    cutoff = _now() - STALE_QUEUED_RUN_AFTER
    stale_runs = (
        await db.scalars(
            select(MessageTable).where(
                MessageTable.conversation_id == conversation_id,
                MessageTable.streaming_status == "queued",
                MessageTable.streaming_started_at < cutoff,
            )
        )
    ).all()
    now = _now()
    failed: set[str] = set()
    for run in stale_runs:
        if inference_run_manager.has_live_task(run.id):
            continue
        failed.add(run.id)
        run.streaming_status = "failed"
        run.streaming_completed_at = now
        run.is_error = True
        run.error_message = "Inference run was queued but never launched."
        run.updated_at = now
    if failed:
        conversation = await db.get(ConversationTable, conversation_id)
        if conversation and conversation.active_assistant_message_id in failed:
            conversation.active_assistant_message_id = None


async def create_inference_run_record(
    *,
    db: AsyncSession,
    client_id: str,
    conversation: ConversationTable,
    parent_message_id: str,
    message_path: list[str] | None,
    agent_slug: str,
    agent_name: str | None,
    mode: str,
) -> MessageTable:
    """Create the AI placeholder that is the run (flushed, not committed).

    Refuses with 429 past the client's active-run cap
    (``INFERENCE_MAX_ACTIVE_RUNS_PER_CLIENT``) and 409 when the conversation
    already has an active run. ``mode`` allocates the branch thread: ``send``
    continues the nearest committed ancestor's thread; new/edit/retry start a
    fresh one, which the run seeds by fork or cold seed.
    """
    await _fail_stale_queued_runs_for_conversation(db, conversation.id)

    cap = settings.rate_limit.inference_max_active_runs
    active = await db.scalar(
        select(func.count())
        .select_from(MessageTable)
        .join(ConversationTable, ConversationTable.id == MessageTable.conversation_id)
        .where(
            ConversationTable.client_id == client_id,
            MessageTable.streaming_status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if (active or 0) >= cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have {cap} active runs. Cancel one before starting a new one.",
        )
    busy = await db.scalar(
        select(MessageTable.id)
        .where(
            MessageTable.conversation_id == conversation.id,
            MessageTable.streaming_status.in_(ACTIVE_RUN_STATUSES),
        )
        .limit(1)
    )
    if busy is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation already has an active inference run.",
        )

    if not any(message.id == parent_message_id for message in conversation.messages):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent message does not belong to this conversation.",
        )
    parent_path = resolve_inference_message_path(
        conversation.messages, parent_message_id, message_path
    )

    if mode == "send":
        ancestor = nearest_committed_ai(conversation.messages, parent_message_id)
        checkpoint_thread_id = (
            ancestor.checkpoint_thread_id if ancestor is not None else str(uuid4())
        )
    else:
        checkpoint_thread_id = str(uuid4())

    now = _now()
    assistant_message = MessageTable(
        conversation_id=conversation.id,
        parent_message_id=parent_message_id,
        sender="ai",
        content="",
        raw_events=[],
        agent_slug=agent_slug,
        agent_name=agent_name,
        streaming_status="queued",
        streaming_started_at=now,
        created_at=now,
        checkpoint_thread_id=checkpoint_thread_id,
    )
    db.add(assistant_message)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if _is_active_run_integrity_conflict(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation already has an active inference run.",
            ) from exc
        raise
    # The path includes the placeholder itself (set after flush: needs the id).
    assistant_message.streaming_message_path = [*parent_path, assistant_message.id]
    conversation.active_assistant_message_id = assistant_message.id
    conversation.last_message_at = now
    # The conversation's agent is a last-used pointer; messages carry their own.
    conversation.agent_slug = agent_slug
    conversation.agent_name = agent_name
    return assistant_message


async def request_run_cancel(db: AsyncSession, run: MessageTable) -> MessageTable:
    """Ask a run to stop. With no live task here, it is cancelled at once
    (keeping whatever content the message already had)."""
    if run.streaming_status not in ACTIVE_RUN_STATUSES:
        return run
    now = _now()
    run.streaming_status = "cancelling"
    run.streaming_cancel_requested_at = now
    if not inference_run_manager.request_cancel(run.id):
        run.streaming_status = "cancelled"
        run.streaming_completed_at = now
        run.updated_at = now
        conversation = await db.get(ConversationTable, run.conversation_id)
        if conversation and conversation.active_assistant_message_id == run.id:
            conversation.active_assistant_message_id = None
    await db.commit()
    await db.refresh(run)
    return run


def request_run_resume(run: MessageTable, payload: dict[str, Any]) -> ResumeOutcome:
    """Hand a HITL decision to the run's live task (see
    :meth:`InferenceRunManager.request_resume`); refused for a run that is not
    active or not live in this process."""
    if run.streaming_status not in ACTIVE_RUN_STATUSES:
        return ResumeOutcome.NOT_PAUSED
    return inference_run_manager.request_resume(run.id, payload)


async def cleanup_orphaned_inference_runs() -> None:
    """At startup: fail every run that was active when the process died, then
    run the run-finished hooks for them (a queued composer message waiting on
    one of those runs is sent now)."""
    async with SessionLocal() as db:
        orphaned = list(
            (
                await db.scalars(
                    select(MessageTable.id).where(
                        MessageTable.streaming_status.in_(ACTIVE_RUN_STATUSES)
                    )
                )
            ).all()
        )
        now = _now()
        await db.execute(
            update(MessageTable)
            .where(MessageTable.streaming_status.in_(ACTIVE_RUN_STATUSES))
            .values(
                streaming_status="failed",
                streaming_completed_at=now,
                is_error=True,
                error_message="Inference run was interrupted by service restart.",
                updated_at=now,
            )
        )
        await db.execute(
            update(ConversationTable)
            .where(ConversationTable.active_assistant_message_id.is_not(None))
            .values(active_assistant_message_id=None)
        )
        await db.commit()
    if orphaned:
        logger.warning(
            "inference_runs_orphaned", "Failed runs interrupted by a restart", count=len(orphaned)
        )
    for run_id in orphaned:
        await _run_finished(run_id)
