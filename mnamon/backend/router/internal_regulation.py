"""``POST /internal/regulation/changes``: reg-memory announces a RegChange.

Guarded like the rest of ``/internal`` (``X-Internal-Secret`` =
``AGENTS_SERVICE_SECRET``; compose gives reg-memory the same value as
``BACKEND_INTERNAL_SECRET``). The payload is stored (idempotent per change id)
and announced on Telegram with Accept / Reject / Open.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.internal import require_internal_secret
from core.security.rate_limit import internal_rate_limit
from schema.regulation import JudgementIn, RegChangeNotifyIn
from utils.regulation import store_judgement, store_notified_change
from utils.telegram_gates import notify_regulation_change, safe

router = APIRouter(dependencies=[Depends(require_internal_secret), Depends(internal_rate_limit)])
logger = get_logger(__name__)


@router.post(
    "/regulation/changes",
    status_code=status.HTTP_202_ACCEPTED,
    summary="reg-memory: a new RegChange (stored, then announced on Telegram)",
)
async def regulation_change(
    payload: RegChangeNotifyIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    body = payload.model_dump()
    row = await store_notified_change(db, body)
    await safe(notify_regulation_change(db, body))
    await db.commit()
    logger.info("regulation_change_received", "RegChange received", change_id=row.id)
    return {"id": row.id, "status": row.status}


@router.put(
    "/regulation/changes/{change_id}/judgement",
    summary="The agents' change judge: per-system decisions for a RegChange",
)
async def regulation_judgement(
    change_id: str, payload: JudgementIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    row = await store_judgement(db, change_id, payload.affected, payload.decidedBy)
    await db.commit()
    logger.info(
        "regulation_change_judged",
        "Change judge result stored",
        change_id=row.id,
        systems=len(payload.affected),
    )
    return {"id": row.id, "judge": "done", "affected": len(payload.affected)}
