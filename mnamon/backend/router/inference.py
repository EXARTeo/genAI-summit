"""Agent runs over HTTP and WebSocket (``/v1/inference``).

No login: the caller is the anonymous browser id (``X-Client-Id``; on a
WebSocket ``?client_id=``). Every run is looked up through its conversation's
``client_id``, so another browser's run is a 404 (a WebSocket closes 4404).
Every HTTP route is rate limited per client (and globally per IP); a WebSocket
handshake checks its Origin and its own connect rate.

| Route | Purpose |
| --- | --- |
| ``POST /runs/start`` | write the turn, create and launch the run (201), or queue it (202) |
| ``GET /runs`` | the caller's runs, ``?status=active`` for hydration |
| ``WS /runs/{run_id}/ws`` | replay + live tail of one run's frames |
| ``POST /runs/{run_id}/cancel`` | stop a run |
| ``POST /runs/{run_id}/resume`` | answer a HITL interrupt |
| ``DELETE /conversations/{id}/queued-message`` | drop the queued composer message |
| ``WS /conversations/{id}/ws`` | the conversation channel (task, run_started, queue) |
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal, get_db
from core.logging import get_logger, set_context
from core.security.client import Caller, get_caller
from core.security.rate_limit import conversation_rate_limit, inference_rate_limit
from schema.inference import (
    InferenceRunOut,
    InferenceRunResumeIn,
    InferenceStartPayload,
    InferenceStartResponse,
    QueuedStartResponse,
    queued_message_from_column,
)
from utils.composer_queue import cancel_queued_message, queue_if_busy
from utils.conversation_channel import channel_frames
from utils.hitl_decisions import ResumeOutcome
from utils.inference_runs import (
    SNAPSHOT_SEQ_SENTINEL,
    build_run_event_payload,
    build_run_out_from_message,
    get_run_for_client,
    inference_run_manager,
    list_runs_for_client,
    mark_run_launch_failed,
    request_run_cancel,
    request_run_resume,
    stream_run_events,
)
from utils.inference_start import start_inference_flow
from utils.validators import load_conversation
from utils.websockets import WS_NOT_FOUND, accept_subscribe, open_socket, pump_frames

logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
InferenceLimit = Annotated[None, Depends(inference_rate_limit)]
ConversationLimit = Annotated[None, Depends(conversation_rate_limit)]

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inference run not found.")


@router.post(
    "/runs/start",
    response_model=InferenceStartResponse | QueuedStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_run(
    payload: InferenceStartPayload,
    response: Response,
    caller: CallerDep,
    _rate_limited: InferenceLimit,
    db: DbDep,
) -> InferenceStartResponse | QueuedStartResponse:
    """Write the user side of the turn, create the AI placeholder, launch the run.

    With ``queue_if_busy`` on a ``send`` to a busy conversation the message is
    queued instead (202) and sent when the active run ends.
    """
    set_context(conversation_id=payload.conversationId)
    queued = await queue_if_busy(db, caller.id, payload)
    if queued is not None:
        response.status_code = status.HTTP_202_ACCEPTED
        return queued
    started = await start_inference_flow(db=db, client_id=caller.id, payload=payload)
    try:
        inference_run_manager.launch(started.run.id)
    except RuntimeError as exc:
        await mark_run_launch_failed(started.run.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Inference run could not be launched.",
        ) from exc
    logger.info(
        "inference_run_launched",
        "Inference run launched",
        run_id=started.run.id,
        conversation_id=started.run.conversationId,
        mode=payload.mode,
    )
    return started


@router.get("/runs", response_model=list[InferenceRunOut])
async def list_runs(
    caller: CallerDep,
    _rate_limited: ConversationLimit,
    db: DbDep,
    status_filter: Annotated[str | None, Query(alias="status", max_length=20)] = None,
) -> list[InferenceRunOut]:
    """The caller's runs for hydration; ``status=active`` = queued/running/cancelling."""
    runs = await list_runs_for_client(db, caller.id, status_filter)
    return [build_run_out_from_message(run) for run in runs]


@router.post("/runs/{run_id}/cancel", response_model=InferenceRunOut)
async def cancel_run(
    run_id: str,
    caller: CallerDep,
    _rate_limited: ConversationLimit,
    db: DbDep,
) -> InferenceRunOut:
    """Stop a run; observers see ``cancelling`` then the terminal frame."""
    run = await get_run_for_client(db, caller.id, run_id)
    if run is None:
        raise _not_found()
    set_context(conversation_id=run.conversation_id)
    run = await request_run_cancel(db, run)
    await inference_run_manager.publish_run_status(run)
    logger.info("inference_run_cancel_requested", "Inference run cancel requested", run_id=run_id)
    return build_run_out_from_message(run)


@router.post("/runs/{run_id}/resume", response_model=InferenceRunOut)
async def resume_run(
    run_id: str,
    payload: InferenceRunResumeIn,
    caller: CallerDep,
    _rate_limited: ConversationLimit,
    db: DbDep,
) -> InferenceRunOut:
    """Answer a HITL interrupt of a paused run.

    200: the decision is queued for an interrupt the run is paused on (or is
    an identical repeat). It is applied when the run's ``BRIDGE_HITL_RESOLVED``
    marker for it appears. 409 says why otherwise: not paused, not a pending
    approval, or a different decision already received.
    """
    run = await get_run_for_client(db, caller.id, run_id)
    if run is None:
        raise _not_found()
    set_context(conversation_id=run.conversation_id)
    resume_payload = {
        "decision": payload.decision,
        "reason": payload.reason,
        "value": payload.value,
        "interrupt_id": payload.interruptId,
        "decisions": [d.model_dump() for d in payload.decisions] if payload.decisions else None,
    }
    outcome = request_run_resume(run, resume_payload)
    if not outcome.accepted:
        logger.warning(
            "inference_run_resume_refused",
            "Inference run resume refused",
            run_id=run.id,
            interrupt_id=payload.interruptId,
            failure_reason=outcome.value,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=outcome.detail)
    logger.info(
        "inference_run_resume_received",
        "Inference run resume received",
        run_id=run.id,
        interrupt_id=payload.interruptId,
        decision=payload.decision,
        repeat=outcome is not ResumeOutcome.ACCEPTED,
    )
    return build_run_out_from_message(run)


@router.delete(
    "/conversations/{conversation_id}/queued-message", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_queued_message(
    conversation_id: str,
    caller: CallerDep,
    _rate_limited: ConversationLimit,
    db: DbDep,
) -> Response:
    """Cancel the conversation's queued composer message before it is sent."""
    await cancel_queued_message(db, caller.id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# WebSockets (lifecycle: utils/websockets.py)
# ---------------------------------------------------------------------------
async def _run_frames(run_id: str, since: str | None) -> AsyncIterator[dict[str, Any]]:
    """The run socket's frames: ``snapshot`` / ``event`` frames, then one
    ``terminal`` frame built from the database — so the client gets the real
    final state even when the terminal stream entry was lost on this socket."""
    async for seq, frame in stream_run_events(run_id, since=since):
        if seq == SNAPSHOT_SEQ_SENTINEL:
            yield {"type": "snapshot", "payload": frame}
        else:
            yield {"type": "event", "seq": seq, "payload": frame}
    try:
        async with SessionLocal() as db:
            terminal = await build_run_event_payload(db, run_id, "terminal")
    except Exception:
        logger.warning(
            "ws_terminal_payload_failed",
            "Failed to build terminal payload; sending a bare terminal frame",
            exc_info=True,
            run_id=run_id,
        )
        terminal = None
    yield {"type": "terminal", "payload": terminal}


@router.websocket("/runs/{run_id}/ws")
async def run_websocket(websocket: WebSocket, run_id: str) -> None:
    """One run's frames with reconnect-and-replay.

    First client frame: ``{"type": "subscribe", "since": "<seq>" | null}``.
    Server frames: ``snapshot`` (fresh subscribe: the terminal state, or a
    live snapshot whose ``run.rawEvents`` is the full coalesced log so far),
    ``event`` (``seq`` + one ``events`` frame of new seq-stamped AG-UI events
    and run meta — resend the last ``seq`` as ``since`` on reconnect), and
    ``terminal`` (the database's final state) before the server closes.
    """
    caller = await open_socket(websocket)
    if caller is None:
        return
    async with SessionLocal() as db:
        run = await get_run_for_client(db, caller.id, run_id)
    if run is None:
        await websocket.close(code=WS_NOT_FOUND, reason="Inference run not found")
        return
    ok, since = await accept_subscribe(websocket)
    if not ok:
        return
    set_context(conversation_id=run.conversation_id)
    logger.info("ws_subscribe", "Run socket subscriber attached", run_id=run_id, replay=bool(since))
    await pump_frames(websocket, _run_frames(run_id, since), run_id=run_id)


@router.websocket("/conversations/{conversation_id}/ws")
async def conversation_websocket(websocket: WebSocket, conversation_id: str) -> None:
    """The conversation channel: ``task``, ``run_started`` and ``queue``
    frames, each with its ``seq`` (send it back as ``since`` after a
    reconnect). The first frame is always the queue's current state."""
    caller = await open_socket(websocket)
    if caller is None:
        return
    try:
        async with SessionLocal() as db:
            conversation = await load_conversation(db, caller.id, conversation_id)
    except HTTPException:
        await websocket.close(code=WS_NOT_FOUND, reason="Conversation not found")
        return
    queued = queued_message_from_column(conversation.queued_message)
    ok, since = await accept_subscribe(websocket)
    if not ok:
        return
    set_context(conversation_id=conversation_id)
    logger.info(
        "conversation_ws_subscribe", "Conversation channel subscriber attached", replay=bool(since)
    )
    await pump_frames(
        websocket, channel_frames(conversation_id, since, queued), conversation_id=conversation_id
    )
