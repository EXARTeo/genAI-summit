import asyncio
import hashlib

from fastapi import APIRouter, Depends, HTTPException, status

from core.logging import get_logger
from core.security.rate_limit import exec_rate_limit
from core.settings import settings
from schema.exec import ExecRequest, ExecResult
from utils.runner import InvalidFiles, run_command

router = APIRouter()
logger = get_logger(__name__)
_slots = asyncio.Semaphore(settings.exec.max_concurrent)


@router.post("", response_model=ExecResult, dependencies=[Depends(exec_rate_limit)])
async def exec_command(body: ExecRequest) -> ExecResult:
    if (
        body.timeout_seconds is not None
        and body.timeout_seconds > settings.exec.max_timeout_seconds
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"timeout_seconds is above the limit ({settings.exec.max_timeout_seconds}).",
        )
    async with _slots:
        try:
            result = await asyncio.to_thread(run_command, body)
        except InvalidFiles as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Audit record: who and what, never the command text.
    logger.info(
        "sandbox_exec",
        "Command ran in the sandbox",
        user_id=body.user_id,
        agent_slug=body.agent_slug,
        conversation_id=body.conversation_id,
        command_sha256=hashlib.sha256(body.command.encode()).hexdigest(),
        command_length=len(body.command),
        files_in=len(body.files),
        files_out=len(result.files),
        exit_code=result.exit_code,
        killed_reason=result.killed_reason,
        duration_ms=result.duration_ms,
    )
    return result
