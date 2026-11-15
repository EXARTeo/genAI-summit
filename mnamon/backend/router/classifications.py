"""Risk-classification routes (``/v1/systems/{id}/classifications``, ``.../obligations``).

Start a classifier run (202, it runs in the background), list and read runs with
their event history, approve or reject a proposal, and preview the obligations
that follow from the system's card. Not scoped by client id, like systems; the
client id is the actor of every write. Logic lives in ``utils.classifications``.
"""

from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from schema.classifications import (
    ClassificationIn,
    ClassificationOut,
    DecisionIn,
    ObligationsPreviewOut,
)
from utils.classifications import (
    classifications_out,
    create_classification,
    decide,
    get_classification,
    list_classifications,
    obligations_preview,
    start_classification,
)
from utils.systems import actor_for
from utils.workspace import get_system_or_404

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]


async def _one(db: AsyncSession, system_id: str, classification_id: str) -> ClassificationOut:
    row = await get_classification(db, system_id, classification_id)
    return (await classifications_out(db, [row]))[0]


@router.post(
    "/{system_id}/classifications",
    response_model=ClassificationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a risk classification (runs in the background)",
)
async def post_classification(
    system_id: str,
    caller: CallerDep,
    _limited: Limited,
    db: Db,
    payload: ClassificationIn | None = None,
) -> ClassificationOut:
    system = await get_system_or_404(db, system_id)
    row, body = await create_classification(
        db, system, payload or ClassificationIn(), actor_for(caller.id)
    )
    await db.commit()
    logger.info(
        "classification_started",
        "Risk classification started",
        system_id=system_id,
        classification_id=row.id,
        document_count=len(body["documents"]),
    )
    start_classification(system_id, row.id, body)
    return await _one(db, system_id, row.id)


@router.get(
    "/{system_id}/classifications",
    response_model=list[ClassificationOut],
    summary="Every classification of the system, newest first, with events",
)
async def get_classifications(
    system_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> list[ClassificationOut]:
    await get_system_or_404(db, system_id)
    items = await classifications_out(db, await list_classifications(db, system_id))
    logger.info(
        "classifications_listed",
        "Classifications listed",
        system_id=system_id,
        item_count=len(items),
    )
    return items


@router.get(
    "/{system_id}/classifications/{classification_id}",
    response_model=ClassificationOut,
    summary="One classification with its events",
)
async def get_one_classification(
    system_id: str, classification_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> ClassificationOut:
    await get_system_or_404(db, system_id)
    return await _one(db, system_id, classification_id)


@router.post(
    "/{system_id}/classifications/{classification_id}/decision",
    response_model=ClassificationOut,
    summary="Approve (updates the card) or reject (with a reason) a proposed classification",
)
async def post_decision(
    system_id: str,
    classification_id: str,
    payload: DecisionIn,
    caller: CallerDep,
    _limited: Limited,
    db: Db,
) -> ClassificationOut:
    system = await get_system_or_404(db, system_id)
    await decide(db, system, classification_id, payload, actor_for(caller.id))
    await db.commit()
    logger.info(
        "classification_decided",
        "Classification decided",
        system_id=system_id,
        classification_id=classification_id,
        decision=payload.decision,
    )
    return await _one(db, system_id, classification_id)


@router.get(
    "/{system_id}/obligations",
    response_model=ObligationsPreviewOut,
    summary="Obligations that follow from the system's card (preview, no audit needed)",
)
async def get_obligations_preview(
    system_id: str,
    _caller: CallerDep,
    _limited: Limited,
    db: Db,
    date: Annotated[Date | None, Query(description="in force on this date (default today)")] = None,
) -> ObligationsPreviewOut:
    system = await get_system_or_404(db, system_id)
    out = await obligations_preview(db, system, date)
    logger.info(
        "obligations_previewed",
        "Obligations preview served",
        system_id=system_id,
        item_count=out.total,
    )
    return out
