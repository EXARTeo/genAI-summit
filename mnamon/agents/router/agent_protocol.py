"""``/ap`` — the six Agent Protocol endpoints deepagents' async sub-agents call.

Internal only: ``require_internal_caller`` (the internal-service secret) and, on
every call, a task-launch token naming the caller. In practice these requests
never leave the process — ``harness.async_tasks.client`` serves them through an
in-process ASGI transport — but they pass every check an outside call would.
Paths and shapes are exactly what ``langgraph_sdk`` sends; logic lives in
``utils.async_tasks``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from core.security.internal_trust import require_internal_caller
from harness.async_tasks.token import LaunchClaims
from schema.agent_protocol import RunCreateIn, RunOut, ThreadCreateIn, ThreadOut
from utils.async_tasks import (
    ap_cancel_run,
    ap_create_run,
    ap_create_thread,
    ap_get_run,
    ap_get_thread,
    ap_list_runs,
    launch_claims,
)

router = APIRouter(prefix="/ap", dependencies=[Depends(require_internal_caller)])

#: The verified caller of every ``/ap`` call (401 without a valid launch token).
Claims = Annotated[LaunchClaims, Depends(launch_claims)]


@router.post("/threads", response_model=ThreadOut, status_code=status.HTTP_200_OK)
async def create_thread(body: ThreadCreateIn, claims: Claims) -> ThreadOut:
    """``threads.create``: a new task, child of the caller the token names."""
    return await ap_create_thread(claims, body)


@router.get("/threads/{thread_id}", response_model=ThreadOut)
async def get_thread(thread_id: str, claims: Claims) -> ThreadOut:
    """``threads.get``: the task's status, result or pending approval."""
    return await ap_get_thread(claims, thread_id)


@router.post("/threads/{thread_id}/runs", response_model=RunOut)
async def create_run(thread_id: str, body: RunCreateIn, claims: Claims) -> RunOut:
    """``runs.create``: start the task, or send it a follow-up."""
    return await ap_create_run(claims, thread_id, body)


@router.get("/threads/{thread_id}/runs", response_model=list[RunOut])
async def list_runs(
    thread_id: str,
    claims: Claims,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> list[RunOut]:
    """``runs.list``: the task's runs, newest first."""
    return await ap_list_runs(claims, thread_id, limit, offset)


@router.get("/threads/{thread_id}/runs/{run_id}", response_model=RunOut)
async def get_run(thread_id: str, run_id: str, claims: Claims) -> RunOut:
    """``runs.get``."""
    return await ap_get_run(claims, thread_id, run_id)


@router.post("/threads/{thread_id}/runs/{run_id}/cancel", response_model=RunOut | None)
async def cancel_run(thread_id: str, run_id: str, claims: Claims) -> RunOut | None:
    """``runs.cancel``: stop the task and its whole subtree."""
    return await ap_cancel_run(claims, thread_id, run_id)
