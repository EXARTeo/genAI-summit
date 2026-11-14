"""Audit pipeline runs started by the backend (``/audits/{id}/run`` and ``/resume``).

The backend creates an audit and calls ``run``; a human decision at a gate
becomes an approval in the backend, which calls ``resume``. Each call returns
at once (202) and the pipeline runs in a background task on this process: the
same :class:`~pipeline.agent.AuditPipelineAgent` and AG-UI frames as
``/agents/audit-pipeline/stream``, consumed here. Progress is visible through
the audit's stage, status and artifacts in the backend, and in Langfuse.

One durable thread per audit (``audit-<id>``); a run cut by a restart is
continued by calling ``run`` again. A failure marks the audit ``failed`` with a
public message and keeps the checkpoint, so ``run`` retries the failed node.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from langgraph.types import Command
from pipeline.agent import AGENT_SLUG, AuditPipelineAgent, audit_thread_id
from pipeline.clients import BackendInternal

from core.logging import get_logger
from schema.audits import AuditResumeIn, AuditRunIn, AuditRunOut, AuditStateOut

logger = get_logger(__name__)

#: audit id -> its running background task (one run per audit at a time).
_RUNS: dict[str, asyncio.Task] = {}

AgentFactory = Callable[[dict[str, Any]], AuditPipelineAgent]
_factory: AgentFactory = lambda config: AuditPipelineAgent(config=config)  # noqa: E731


def set_agent_factory(factory: AgentFactory | None) -> None:
    """Tests swap the agent (fake deps); ``None`` restores the real one."""
    global _factory
    _factory = factory or (lambda config: AuditPipelineAgent(config=config))


def run_config(
    audit_id: str, system_id: str, *, client_id: str | None, trace: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The contract ``Config`` of one pipeline segment (a run between two gates)."""
    trace_id = str((trace or {}).get("trace_id") or uuid4().hex)
    return {
        "run_config": {"configurable": {"thread_id": audit_thread_id(audit_id)}},
        "context": {
            "client_id": client_id or AGENT_SLUG,
            "conversation_id": audit_thread_id(audit_id),
            "run_id": uuid4().hex,
            "system_id": system_id,
            "audit_id": audit_id,
        },
        "trace": {**(trace or {}), "trace_id": trace_id, "session_id": audit_thread_id(audit_id)},
    }


def is_running(audit_id: str) -> bool:
    task = _RUNS.get(audit_id)
    return task is not None and not task.done()


async def _snapshot(agent: AuditPipelineAgent) -> Any:
    await agent.ensure_built()
    return await agent.compiled.aget_state(agent.run_config)


def _gate_of(interrupt: Any) -> str | None:
    value = getattr(interrupt, "value", None)
    return value.get("gate") if isinstance(value, dict) else None


async def _drive(agent: AuditPipelineAgent, command: Command | None) -> None:
    """Consume one segment's AG-UI frames; a RUN_ERROR fails the audit (public message)."""
    audit_id = str(agent.context["audit_id"])
    error: str | None = None
    frames = 0
    try:
        async for frame in agent.astream({}, command=command):
            frames += 1
            text = frame.decode("utf-8", errors="replace") if isinstance(frame, bytes) else frame
            if text.startswith("data: "):
                try:
                    event = json.loads(text[6:])
                except ValueError:
                    continue
                if event.get("type") == "RUN_ERROR":
                    error = str(event.get("message") or "The pipeline failed.")
    except Exception as exc:  # never let a background task die silently
        error = getattr(exc, "public_message", None) or "The pipeline failed."
        logger.error("audit_run_crashed", "Audit run crashed", exc_info=True, audit_id=audit_id)
    logger.info(
        "audit_run_segment_ended",
        "Audit run segment ended",
        audit_id=audit_id,
        frames=frames,
        failed=error is not None,
    )
    if error is not None:
        try:
            await BackendInternal(audit_id).patch(status="failed", data={"error": error})
        except Exception:
            logger.warning(
                "audit_fail_patch_failed", "Could not mark the audit failed", audit_id=audit_id
            )


def _launch(audit_id: str, agent: AuditPipelineAgent, command: Command | None) -> None:
    task = asyncio.create_task(_drive(agent, command), name=f"audit-{audit_id}")
    _RUNS[audit_id] = task
    task.add_done_callback(
        lambda t: _RUNS.pop(audit_id, None) if _RUNS.get(audit_id) is t else None
    )


async def start_audit_run(audit_id: str, body: AuditRunIn) -> AuditRunOut:
    """Start the pipeline, or continue a run that was cut; 409 while running or at a gate."""
    if is_running(audit_id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="The audit pipeline is running.")
    config = run_config(audit_id, body.system_id, client_id=body.client_id, trace=body.trace)
    agent = _factory(config)
    snapshot = await _snapshot(agent)
    pending = [_gate_of(i) for i in snapshot.interrupts or []]
    if pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"message": "The audit is waiting at a gate.", "pending_gates": pending},
        )
    started = "resumed" if snapshot.values else "started"
    _launch(audit_id, agent, None)
    logger.info("audit_run_started", "Audit pipeline started", audit_id=audit_id, mode=started)
    return AuditRunOut(audit_id=audit_id, thread_id=audit_thread_id(audit_id), status=started)


async def resume_audit_run(audit_id: str, body: AuditResumeIn) -> AuditRunOut:
    """Answer the pending gate ``body.gate``; 409 when the audit is not waiting there."""
    if is_running(audit_id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="The audit pipeline is running.")
    config = run_config(audit_id, body.system_id, client_id=None, trace=body.trace)
    agent = _factory(config)
    snapshot = await _snapshot(agent)
    match = next((i for i in snapshot.interrupts or [] if _gate_of(i) == body.gate), None)
    if match is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": f"The audit is not waiting at gate {body.gate!r}.",
                "pending_gates": [_gate_of(i) for i in snapshot.interrupts or []],
            },
        )
    value = body.model_dump(exclude={"trace", "system_id"})
    _launch(audit_id, agent, Command(resume={match.id: value}))
    logger.info(
        "audit_run_resumed",
        "Audit gate answered",
        audit_id=audit_id,
        gate=body.gate,
        decision=body.decision,
    )
    return AuditRunOut(audit_id=audit_id, thread_id=audit_thread_id(audit_id), status="resumed")


async def audit_state(audit_id: str, system_id: str) -> AuditStateOut:
    """Where the pipeline of an audit stands (debugging, demo)."""
    agent = _factory(run_config(audit_id, system_id, client_id=None, trace=None))
    snapshot = await _snapshot(agent)
    values = snapshot.values or {}
    gate = next(iter(snapshot.interrupts or []), None)
    return AuditStateOut(
        audit_id=audit_id,
        thread_id=audit_thread_id(audit_id),
        running=is_running(audit_id),
        next=list(snapshot.next or []),
        pending_gate=getattr(gate, "value", None) if gate is not None else None,
        status=values.get("status"),
        stage_artifacts=dict(values.get("artifacts") or {}),
    )


async def wait_for(audit_id: str) -> None:
    """Await the audit's running task (tests)."""
    task = _RUNS.get(audit_id)
    if task is not None:
        await task


__all__ = [
    "audit_state",
    "is_running",
    "resume_audit_run",
    "run_config",
    "set_agent_factory",
    "start_audit_run",
    "wait_for",
]
