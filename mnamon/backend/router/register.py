"""Findings register, public side (``/v1``): a system's state per obligation.

``GET  /v1/systems/{id}/register``                         items + summary
``GET  /v1/systems/{id}/register/{obligation_id}``         one item with its history
``POST /v1/systems/{id}/register/{obligation_id}/close``   ``{reason}`` (required)
``POST /v1/systems/{id}/register/{obligation_id}/reopen``  ``{reason?}``

Actor = ``client:<X-Client-Id>``. Audits feed the register when they finish
(utils/register.py); ``POST /v1/admin/rebuild-register`` refolds every audit.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from schema.register import CloseIn, RegisterItemDetail, RegisterOut, ReopenIn
from utils.register import close_item, get_item_or_404, item_out, register_out, reopen_item
from utils.systems import actor_for
from utils.workspace import get_system_or_404

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/systems/{system_id}/register",
    response_model=RegisterOut,
    summary="The system's findings register: state per obligation + summary",
)
async def get_register(
    system_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> RegisterOut:
    await get_system_or_404(db, system_id)
    out = await register_out(db, system_id)
    logger.info(
        "register_listed",
        "Findings register listed",
        system_id=system_id,
        count=out.summary.total,
        open_gaps=out.summary.open_gaps,
    )
    return out


@router.get(
    "/systems/{system_id}/register/{obligation_id}",
    response_model=RegisterItemDetail,
    summary="One register item with its history",
)
async def get_register_item(
    system_id: str, obligation_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> RegisterItemDetail:
    row = await get_item_or_404(db, system_id, obligation_id)
    logger.info(
        "register_item_read", "Register item read", system_id=system_id, obligation_id=obligation_id
    )
    return item_out(row)


@router.post(
    "/systems/{system_id}/register/{obligation_id}/close",
    response_model=RegisterItemDetail,
    summary="Close an item with a reason (accepted risk); 409 when already closed",
)
async def post_close(
    system_id: str,
    obligation_id: str,
    payload: CloseIn,
    caller: CallerDep,
    _limited: Limited,
    db: Db,
) -> RegisterItemDetail:
    row = await get_item_or_404(db, system_id, obligation_id)
    close_item(row, payload.reason, actor_for(caller.id))
    await db.commit()
    await db.refresh(row)
    logger.info(
        "register_item_closed",
        "Register item closed",
        system_id=system_id,
        obligation_id=obligation_id,
        verdict=row.verdict,
    )
    return item_out(row)


@router.post(
    "/systems/{system_id}/register/{obligation_id}/reopen",
    response_model=RegisterItemDetail,
    summary="Reopen an item; 409 when already open",
)
async def post_reopen(
    system_id: str,
    obligation_id: str,
    payload: ReopenIn,
    caller: CallerDep,
    _limited: Limited,
    db: Db,
) -> RegisterItemDetail:
    row = await get_item_or_404(db, system_id, obligation_id)
    reopen_item(row, payload.reason, actor_for(caller.id))
    await db.commit()
    await db.refresh(row)
    logger.info(
        "register_item_reopened",
        "Register item reopened",
        system_id=system_id,
        obligation_id=obligation_id,
    )
    return item_out(row)
