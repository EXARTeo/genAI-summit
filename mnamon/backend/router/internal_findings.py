"""Sealed findings, internal side (``/internal``, shared secret + IP rate limit).

``POST /internal/audits/{id}/findings``          the pipeline's ``seal`` step: one
    sealed finding (201; 200 with the stored row when the hash is already sealed)
``POST /internal/findings/{id}/status-events``   a status event (``stale`` from the
    change judge, ``superseded`` ...); never an edit
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.internal import require_internal_secret
from core.security.rate_limit import internal_rate_limit
from schema.findings import FindingIn, FindingOut, StatusEventIn, StatusEventOut
from utils.audits import get_audit_or_404
from utils.findings import add_status_event, findings_out, get_finding_or_404, seal_finding

router = APIRouter(dependencies=[Depends(require_internal_secret), Depends(internal_rate_limit)])
logger = get_logger(__name__)

Db = Annotated[AsyncSession, Depends(get_db)]
AgentName = Annotated[str | None, Header(alias="X-Agent-Name")]


def _actor(agent: str | None) -> str:
    return f"agent:{agent}" if agent else "agent"


@router.post(
    "/audits/{audit_id}/findings",
    response_model=FindingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Seal one finding (append-only, idempotent on hash)",
)
async def internal_seal_finding(
    audit_id: str, payload: FindingIn, response: Response, db: Db, agent: AgentName = None
) -> FindingOut:
    audit = await get_audit_or_404(db, audit_id)
    row, created = await seal_finding(db, audit, payload, _actor(agent))
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    logger.info(
        "finding_sealed",
        "Finding sealed" if created else "Finding already sealed",
        audit_id=audit_id,
        finding_id=row.id,
        obligation_id=row.obligation_id,
        verdict=row.verdict,
        created=created,
    )
    return (await findings_out(db, [row]))[0]


@router.post(
    "/findings/{finding_id}/status-events",
    response_model=StatusEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a status event to a finding (stale, superseded, ...)",
)
async def internal_status_event(
    finding_id: str, payload: StatusEventIn, db: Db, agent: AgentName = None
) -> StatusEventOut:
    finding = await get_finding_or_404(db, finding_id)
    event = await add_status_event(db, finding, payload, _actor(agent))
    await db.commit()
    await db.refresh(event)
    logger.info(
        "finding_status_event",
        "Finding status event added",
        finding_id=finding_id,
        finding_status=event.status,
    )
    return StatusEventOut.model_validate(event)
