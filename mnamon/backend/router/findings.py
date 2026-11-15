"""Sealed findings, public side (``/v1``): read a system's findings and add
human annotations. There is no route that edits or deletes a finding.

``GET  /v1/systems/{id}/findings?current=true``   a system's findings (current = not superseded)
``GET  /v1/findings/{id}/annotations``            a finding's annotations
``POST /v1/findings/{id}/annotations``            add one (contest | accept_risk |
                                                  remediation_planned | comment); actor = client id

An audit's findings are ``GET /v1/audits/{id}/findings`` (router/audits.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from schema.findings import AnnotationIn, AnnotationOut, FindingOut
from utils.findings import (
    add_annotation,
    findings_out,
    get_finding_or_404,
    list_annotations,
    system_findings,
)
from utils.systems import actor_for
from utils.workspace import get_system_or_404

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/systems/{system_id}/findings",
    response_model=list[FindingOut],
    summary="A system's sealed findings, newest first",
)
async def get_system_findings(
    system_id: str, _caller: CallerDep, _limited: Limited, db: Db, current: bool = False
) -> list[FindingOut]:
    await get_system_or_404(db, system_id)
    out = await findings_out(db, await system_findings(db, system_id, current))
    logger.info(
        "system_findings_listed",
        "System findings listed",
        system_id=system_id,
        current=current,
        count=len(out),
    )
    return out


@router.get(
    "/findings/{finding_id}/annotations",
    response_model=list[AnnotationOut],
    summary="A finding's annotations, oldest first",
)
async def get_annotations(
    finding_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> list[AnnotationOut]:
    await get_finding_or_404(db, finding_id)
    rows = await list_annotations(db, finding_id)
    logger.info("finding_annotations_listed", "Annotations listed", finding_id=finding_id)
    return [AnnotationOut.model_validate(r) for r in rows]


@router.post(
    "/findings/{finding_id}/annotations",
    response_model=AnnotationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Annotate a sealed finding (the verdict never changes)",
)
async def post_annotation(
    finding_id: str, payload: AnnotationIn, caller: CallerDep, _limited: Limited, db: Db
) -> AnnotationOut:
    finding = await get_finding_or_404(db, finding_id)
    note = await add_annotation(db, finding, payload, actor_for(caller.id))
    await db.commit()
    await db.refresh(note)
    logger.info(
        "finding_annotated",
        "Finding annotated",
        finding_id=finding_id,
        audit_id=finding.audit_id,
        kind=note.kind,
    )
    return AnnotationOut.model_validate(note)
