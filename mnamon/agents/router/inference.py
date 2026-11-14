"""The run endpoints: ``POST /agents/{slug}/stream`` and ``/resume`` (AG-UI over SSE).

Thin: the logic is ``utils.inference``. Both answer ``text/event-stream`` with
a keepalive comment while the agent is silent, so the backend's read timeout
never fails a working run.
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from core.security.internal_trust import require_internal_caller
from harness.agui.keepalive import with_keepalive
from schema.inference import AgentResumeRequest, Request
from utils.inference import resume_run, stream_run

router = APIRouter(dependencies=[Depends(require_internal_caller)])


@router.post("/agents/{agent_slug}/stream", status_code=status.HTTP_200_OK)
async def stream_agent(agent_slug: str, req: Request) -> StreamingResponse:
    """Start a run of ``agent_slug`` and stream its AG-UI events."""
    frames = await stream_run(agent_slug, req)
    return StreamingResponse(with_keepalive(frames), media_type="text/event-stream")


@router.post("/agents/{agent_slug}/resume", status_code=status.HTTP_200_OK)
async def resume_agent(agent_slug: str, req: AgentResumeRequest) -> StreamingResponse:
    """Resume a run paused on HITL interrupt(s), framed exactly like ``/stream``."""
    frames = await resume_run(agent_slug, req)
    return StreamingResponse(with_keepalive(frames), media_type="text/event-stream")
