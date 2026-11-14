"""The run endpoints' logic: build the agent, feed it the request, stream AG-UI back.

``router/inference.py`` only translates HTTP; everything a ``/stream`` or a
``/resume`` does lives here, in order:

1. resolve the agent (404 for an unknown slug) and build it for this run;
2. ``/stream`` only: write the request's inline uploads into
   ``/conversation/input/`` (:mod:`harness.conversation_files.inputs`), and hand
   the agent the messages without their attachment payloads (each message that
   brought uploads gets a line naming their paths instead);
3. open the optional MCP session and attach its tools;
4. ``/stream`` with ``fork_from``: seed the new branch thread from the parent's
   checkpoint; ``/resume``: read the pause back and build its ``Command``;
5. stream the run, then ``CHECKPOINT_COMMITTED`` with the durable head.

A client disconnect (the backend closing the stream on cancel) cancels the run.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from fastapi import HTTPException, status
from langchain_mcp_adapters.tools import load_mcp_tools

from core.error_handling import RUN_ERROR_FRAME_PREFIX
from core.logging import get_context, get_logger, set_context
from harness.async_tasks.notification import is_notification_payload, normalize_payload_messages
from harness.checkpointer import get_runtime_pool, has_checkpointer_initialized
from harness.checkpointer.fork import seed_thread_from_checkpoint
from harness.conversation_files import ConversationFileStore
from harness.conversation_files.inputs import StoredUpload, ingest_uploads
from schema.inference import AgentResumeRequest, Request
from utils.agents import resolve_agent_definition
from utils.checkpointer import emit_checkpoint_committed, release_checkpoint_unless_paused
from utils.hitl_resume import build_resume_command
from utils.mcp_tools import optional_mcp_session

logger = get_logger(__name__)

#: The keys of a contract ``Message`` the agent reads; ``attachments`` never
#: reaches the model or the checkpoint (its bytes are in the conversation files).
_MESSAGE_KEYS = ("id", "role", "content")


def _section(config: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key) if isinstance(config, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else {}


def _thread_id(config: Mapping[str, Any]) -> str:
    configurable = _section(_section(config, "run_config"), "configurable")
    return str(configurable.get("thread_id") or "")


def _bind_log_context(agent_slug: str, config: Mapping[str, Any], thread_id: str) -> None:
    """The run's identity on every log line; the client id is hashed by the formatter."""
    context = _section(config, "context")
    set_context(
        agent_slug=agent_slug,
        user_id=context.get("client_id") or "anonymous",
        conversation_id=context.get("conversation_id"),
        thread_id=thread_id,
    )


def _build_agent(agent_slug: str, config: dict[str, Any]) -> Any:
    """The agent for this run; 404 for an unknown slug, 400 when it cannot be built."""
    definition = resolve_agent_definition(agent_slug)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent.")
    if not isinstance(config.get("context"), Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="config.context is required."
        )
    try:
        return definition.build(config=config)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "agent_initialization_failed",
            "Failed to initialise the requested agent",
            exc_info=True,
            agent_slug=agent_slug,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to initialise the requested agent.",
        ) from exc


def _upload_note(uploads: Sequence[StoredUpload]) -> str:
    lines = "\n".join(f"- {upload.path} ({upload.mime_type})" for upload in uploads)
    return f"Uploaded files, readable in /conversation/input/:\n{lines}"


def agent_messages(
    messages: Sequence[Mapping[str, Any]], uploads: Sequence[StoredUpload]
) -> list[Any]:
    """The run's input for the agent: each message without its attachment payloads.

    A message that brought uploads gets a text line naming where they are now
    (``/conversation/input/<name>``), since a name may have been made unique.
    A persisted task-notification row passes through to become its
    ``HumanMessage`` again.
    """
    by_message: dict[str, list[StoredUpload]] = {}
    for upload in uploads:
        by_message.setdefault(upload.message_id, []).append(upload)
    cleaned: list[Any] = []
    for message in messages:
        if is_notification_payload(message):
            cleaned.append(message)
            continue
        item = {key: message[key] for key in _MESSAGE_KEYS if key in message}
        stored = by_message.get(str(message.get("id") or ""))
        if stored:
            note = _upload_note(stored)
            content = item.get("content")
            if isinstance(content, list):
                item["content"] = [*content, {"type": "text", "text": note}]
            else:
                text = content if isinstance(content, str) else ""
                item["content"] = f"{text}\n\n{note}" if text else note
        cleaned.append(item)
    return normalize_payload_messages(cleaned)


async def _attach_mcp_tools(agent: Any, session: Any) -> None:
    live_tools = await load_mcp_tools(session) if session is not None else []
    agent.attach_tools(live_tools)
    logger.info(
        "agent_tools_attached",
        "Agent tools attached for the run",
        live_tool_count=len(live_tools),
        mcp_available=session is not None,
        attached_tool_count=len(getattr(agent, "tools_names", [])),
    )


async def stream_run(agent_slug: str, req: Request) -> AsyncIterator[bytes]:
    """Start a run: the AG-UI frames of ``POST /agents/{slug}/stream``.

    Validation (unknown agent, unbuildable config) raises before the first
    frame, so the route answers it as an HTTP error rather than a stream.
    """
    config = dict(req.config)
    thread_id = _thread_id(config)
    _bind_log_context(agent_slug, config, thread_id)
    logger.info(
        "agent_stream_request_received",
        "Agent stream request received",
        input_messages=len(req.messages),
        forked=isinstance(config.get("fork_from"), Mapping),
    )
    agent = _build_agent(agent_slug, config)
    uploads = await ingest_uploads(
        ConversationFileStore(get_runtime_pool()),
        client_id=agent.client_id,
        conversation_id=str(agent.context.get("conversation_id") or ""),
        messages=req.messages,
    )
    messages = agent_messages(req.messages, uploads)
    fork_from = config.get("fork_from")
    run_id = str(agent.context.get("run_id") or thread_id)
    return _run_stream(
        agent,
        thread_id=thread_id,
        run_id=run_id,
        payload={"messages": messages},
        fork_from=fork_from if isinstance(fork_from, Mapping) else None,
    )


async def resume_run(agent_slug: str, req: AgentResumeRequest) -> AsyncIterator[bytes]:
    """Resume a paused run: the AG-UI frames of ``POST /agents/{slug}/resume``.

    The decision targets a pause read back from the durable checkpoint; a
    named interrupt that is no longer pending is a 409 listing the stale and
    the pending ids (``utils.hitl_resume``), and nothing is applied.
    """
    config = dict(req.config)
    thread_id = req.thread_id or _thread_id(config)
    _bind_log_context(agent_slug, config, thread_id)
    logger.info(
        "agent_resume_request_received",
        "Agent resume request received",
        decision=req.decision,
        has_value=req.value is not None,
        batched=len(req.resumes) if req.resumes else 1,
    )
    if not thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="thread_id is required to resume a paused run.",
        )
    if not has_checkpointer_initialized():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Checkpointer is not ready."
        )
    # The paused run's own thread, whatever the config says.
    run_config = _section(config, "run_config")
    run_config["configurable"] = {**_section(run_config, "configurable"), "thread_id": thread_id}
    config["run_config"] = run_config
    agent = _build_agent(agent_slug, config)
    try:
        await agent.ensure_built()
        snapshot = await agent.compiled.aget_state(agent.run_config)
    except Exception as exc:
        logger.warning(
            "agent_resume_state_load_failed", "Failed to load the paused checkpoint", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load the paused checkpoint.",
        ) from exc
    pending = list(snapshot.interrupts or [])
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "No pending interrupt found on the checkpoint.",
                "stale_interrupt_ids": [
                    str(item.interrupt_id) for item in (req.resumes or [req]) if item.interrupt_id
                ],
                "pending_interrupt_ids": [],
            },
        )
    # The resume stream runs through a fresh normalizer: re-teach it the `task`
    # calls still awaiting their result, so a sub-agent started once its gated
    # `task` is approved keeps that call's id and its result closes its card.
    values = getattr(snapshot, "values", None)
    if isinstance(values, dict):
        agent.agui_normalizer.seed_pending_tasks(values.get("messages"))
    command = build_resume_command(req, pending, logger)
    run_id = str(agent.context.get("run_id") or thread_id)
    return _run_stream(
        agent, thread_id=thread_id, run_id=run_id, payload={"messages": []}, command=command
    )


async def _run_stream(
    agent: Any,
    *,
    thread_id: str,
    run_id: str,
    payload: Mapping[str, Any],
    fork_from: Mapping[str, Any] | None = None,
    command: Any = None,
) -> AsyncIterator[bytes]:
    """The run itself, as one generator the route wraps in keepalives."""
    request_context = get_context()
    try:
        async with optional_mcp_session() as session:
            await _attach_mcp_tools(agent, session)
            if fork_from is not None and thread_id:
                # Build with the tools first (a deep agent compiles against
                # them), then seed the new thread from the fork-point checkpoint.
                await agent.ensure_built()
                await seed_thread_from_checkpoint(
                    graph=agent.compiled,
                    source_thread_id=str(fork_from.get("thread_id") or ""),
                    source_checkpoint_id=fork_from.get("checkpoint_id"),
                    target_thread_id=thread_id,
                )
            async for chunk in agent.astream(payload=payload, command=command):
                yield chunk
                if chunk.startswith(RUN_ERROR_FRAME_PREFIX):
                    # The contract: nothing after RUN_ERROR, not even the checkpoint.
                    return
        committed = await emit_checkpoint_committed(agent, thread_id, logger, request_context)
        if committed is not None:
            yield committed
        logger.info("agent_stream_completed", "Agent stream completed", resumed=command is not None)
    except asyncio.CancelledError:
        logger.info("agent_stream_cancelled", "Agent stream cancelled", resumed=command is not None)
        raise
    except Exception as exc:
        logger.error("agent_stream_failed", "Agent stream failed", exc_info=True)
        yield agent._encode_run_error(exc)
    finally:
        try:
            await release_checkpoint_unless_paused(agent, run_id)
        except Exception:
            logger.warning(
                "checkpoint_release_failed",
                "Failed to release the run's namespace bindings",
                exc_info=True,
            )
