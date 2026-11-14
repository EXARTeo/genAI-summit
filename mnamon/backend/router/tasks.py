"""Background sub-agent tasks: REST and the drill-down WebSocket.

Thin: every route resolves the anonymous caller (``X-Client-Id``; on a
WebSocket ``?client_id=``), applies its rate limit and hands the work to
``utils/async_tasks.py``. A task is reached only through a conversation the
caller owns; anything else is a 404 (a WebSocket closes 4404). Two routers,
because half the surface hangs off a conversation:

| Route | Purpose | Limit |
| --- | --- | --- |
| ``GET /v1/conversations/{id}/tasks?limit=`` | the task tree, from the mirror | task read |
| ``GET /v1/tasks/active-conversations`` | conversations with working tasks | task read |
| ``POST /v1/tasks/{task_id}/cancel`` | stop a task and its subtree | task mutate |
| ``POST /v1/tasks/{task_id}/resume`` | answer a waiting task's approval | task mutate |
| ``WS /v1/tasks/{task_id}/ws`` | one task's live events | WS connect |

Task status frames reach a watching browser on the conversation channel
(``WS /v1/inference/conversations/{id}/ws``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal, get_db
from core.logging import get_logger, set_context
from core.security.client import Caller, get_caller
from core.security.rate_limit import task_mutate_rate_limit, task_read_rate_limit
from schema.tasks import ActiveConversationsOut, TaskOut, TaskResumeIn
from utils.async_tasks import (
    active_conversation_ids,
    cancel_task_for_client,
    get_owned_task,
    list_conversation_tasks,
    resume_task_for_client,
    stream_task_events,
)
from utils.websockets import WS_NOT_FOUND, accept_subscribe, open_socket, pump_frames

logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
TaskReadLimit = Annotated[None, Depends(task_read_rate_limit)]
TaskMutateLimit = Annotated[None, Depends(task_mutate_rate_limit)]

router = APIRouter()
conversation_router = APIRouter()


@conversation_router.get("/{conversation_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    conversation_id: str,
    caller: CallerDep,
    _rate_limited: TaskReadLimit,
    db: DbDep,
    limit: Annotated[int, Query(ge=1)] = 200,
) -> list[TaskOut]:
    """The conversation's background task tree, parents before children."""
    set_context(conversation_id=conversation_id)
    return await list_conversation_tasks(db, caller.id, conversation_id, limit)


@router.get("/active-conversations", response_model=ActiveConversationsOut)
async def list_active_conversations(
    caller: CallerDep, _rate_limited: TaskReadLimit, db: DbDep
) -> ActiveConversationsOut:
    """The caller's conversations whose background tasks are still working."""
    return await active_conversation_ids(db, caller.id)


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str, caller: CallerDep, _rate_limited: TaskMutateLimit, db: DbDep
) -> TaskOut:
    """The Stop button: cancel a task and its whole subtree."""
    return await cancel_task_for_client(db, caller.id, task_id)


@router.post("/{task_id}/resume", response_model=TaskOut)
async def resume_task(
    task_id: str,
    payload: TaskResumeIn,
    caller: CallerDep,
    _rate_limited: TaskMutateLimit,
    db: DbDep,
) -> TaskOut:
    """Answer the approval a ``waiting`` task is paused on."""
    return await resume_task_for_client(db, caller.id, task_id, payload)


@router.websocket("/{task_id}/ws")
async def task_websocket(websocket: WebSocket, task_id: str) -> None:
    """One task's live events, for its drill-down: ``snapshot`` (the task, and
    its stored ``events`` once settled), then ``event`` frames (``seq`` = the
    stream entry id, resend it as ``since``), then ``terminal`` once it settles."""
    caller = await open_socket(websocket)
    if caller is None:
        return
    async with SessionLocal() as db:
        owned = await get_owned_task(db, caller.id, task_id) is not None
    if not owned:
        await websocket.close(code=WS_NOT_FOUND, reason="Task not found")
        return
    ok, since = await accept_subscribe(websocket)
    if not ok:
        return
    logger.info("task_ws_subscribe", "Task socket subscriber attached", task_id=task_id)
    await pump_frames(websocket, stream_task_events(caller.id, task_id, since), task_id=task_id)
