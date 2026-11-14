from typing import Any

from fastapi import APIRouter, Depends, Response, status

from core.security.rate_limit import read_rate_limit, write_rate_limit
from schema.watch import CheckAccepted, CheckRecord, CheckRequest
from utils.watch import get_check, start_check, watch_status

router = APIRouter()


@router.get("", dependencies=[Depends(read_rate_limit)])
async def watch() -> dict[str, Any]:
    return watch_status()


@router.post("/check-now", dependencies=[Depends(write_rate_limit)])
async def check_now(response: Response, body: CheckRequest | None = None) -> dict[str, Any]:
    """Re-fetch -> extract -> diff -> candidate release + RegChange (all or some sources)."""
    body = body or CheckRequest()
    check_id, task = start_check(body.source_ids, trigger="manual", discovery=body.discovery)
    if body.wait:
        return CheckRecord(**(await task)).model_dump()
    response.status_code = status.HTTP_202_ACCEPTED
    return CheckAccepted(check_id=check_id, status="queued").model_dump()


@router.get("/checks/{check_id}", dependencies=[Depends(read_rate_limit)])
async def check(check_id: str) -> dict[str, Any]:
    return get_check(check_id)
