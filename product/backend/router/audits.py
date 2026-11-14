"""Audit routes (``/v1/audits``): list / get / patch audits, their versioned
artifacts, and the human approvals at each gate.

Create an audit with ``POST /v1/systems/{id}/audits``. Like systems, audits are
not scoped by client id (for now); the caller is the actor of every write.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from schema.audits import (
    ApprovalIn,
    ApprovalOut,
    ApprovalResultOut,
    ArtifactIn,
    ArtifactOut,
    ArtifactPatch,
    AuditDetail,
    AuditOut,
    AuditPatch,
)
from utils.audits import (
    audit_detail,
    create_artifact,
    get_artifact_or_404,
    get_audit_or_404,
    list_approvals,
    list_artifacts,
    list_audits,
    patch_artifact,
    patch_audit,
    record_approval,
)
from utils.systems import actor_for

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[AuditOut], summary="List audits, newest first")
async def get_audits(
    _caller: CallerDep,
    _limited: Limited,
    db: Db,
    systemId: str | None = None,  # noqa: N803
) -> list[AuditOut]:
    return [AuditOut.model_validate(a) for a in await list_audits(db, systemId)]


@router.get(
    "/{audit_id}", response_model=AuditDetail, summary="An audit with its artifacts and approvals"
)
async def get_audit(audit_id: str, _caller: CallerDep, _limited: Limited, db: Db) -> AuditDetail:
    return await audit_detail(db, audit_id)


@router.patch("/{audit_id}", response_model=AuditOut, summary="Update status / stage / data")
async def update_audit(
    audit_id: str, payload: AuditPatch, _caller: CallerDep, _limited: Limited, db: Db
) -> AuditOut:
    audit = await get_audit_or_404(db, audit_id)
    patch_audit(audit, payload)
    await db.commit()
    await db.refresh(audit)
    logger.info(
        "audit_updated",
        "Audit updated",
        audit_id=audit_id,
        stage=audit.stage,
        audit_status=audit.status,
    )
    return AuditOut.model_validate(audit)


@router.get(
    "/{audit_id}/artifacts", response_model=list[ArtifactOut], summary="The audit's artifacts"
)
async def get_artifacts(
    audit_id: str,
    _caller: CallerDep,
    _limited: Limited,
    db: Db,
    kind: str | None = None,
    liveOnly: bool = False,  # noqa: N803
) -> list[ArtifactOut]:
    await get_audit_or_404(db, audit_id)
    rows = await list_artifacts(db, audit_id, kind, liveOnly)
    return [ArtifactOut.model_validate(a) for a in rows]


@router.post(
    "/{audit_id}/artifacts",
    response_model=ArtifactOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new version of an artifact (supersedes the slot's earlier versions)",
)
async def post_artifact(
    audit_id: str, payload: ArtifactIn, caller: CallerDep, _limited: Limited, db: Db
) -> ArtifactOut:
    audit = await get_audit_or_404(db, audit_id)
    artifact = await create_artifact(db, audit, payload, actor_for(caller.id))
    await db.commit()
    await db.refresh(artifact)
    logger.info(
        "audit_artifact_created",
        "Audit artifact created",
        audit_id=audit_id,
        kind=artifact.kind,
        version=artifact.version,
    )
    return ArtifactOut.model_validate(artifact)


@router.get(
    "/{audit_id}/artifacts/{artifact_id}", response_model=ArtifactOut, summary="One artifact"
)
async def get_artifact(
    audit_id: str, artifact_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> ArtifactOut:
    return ArtifactOut.model_validate(await get_artifact_or_404(db, audit_id, artifact_id))


@router.patch(
    "/{audit_id}/artifacts/{artifact_id}",
    response_model=ArtifactOut,
    summary="Set an artifact's status or merge into its data",
)
async def update_artifact(
    audit_id: str,
    artifact_id: str,
    payload: ArtifactPatch,
    _caller: CallerDep,
    _limited: Limited,
    db: Db,
) -> ArtifactOut:
    artifact = await get_artifact_or_404(db, audit_id, artifact_id)
    patch_artifact(artifact, payload)
    await db.commit()
    await db.refresh(artifact)
    logger.info(
        "audit_artifact_updated",
        "Audit artifact updated",
        audit_id=audit_id,
        artifact_id=artifact_id,
        artifact_status=artifact.status,
    )
    return ArtifactOut.model_validate(artifact)


@router.get(
    "/{audit_id}/approvals", response_model=list[ApprovalOut], summary="The audit's decisions"
)
async def get_approvals(
    audit_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> list[ApprovalOut]:
    await get_audit_or_404(db, audit_id)
    return [ApprovalOut.model_validate(a) for a in await list_approvals(db, audit_id)]


@router.post(
    "/{audit_id}/approvals",
    response_model=ApprovalResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a human decision at a gate (a rejection with a reason → memory proposal)",
)
async def post_approval(
    audit_id: str, payload: ApprovalIn, caller: CallerDep, _limited: Limited, db: Db
) -> ApprovalResultOut:
    audit = await get_audit_or_404(db, audit_id)
    approval, artifact, proposal = await record_approval(db, audit, payload, actor_for(caller.id))
    await db.commit()
    await db.refresh(approval)
    if artifact is not None:
        await db.refresh(artifact)
    logger.info(
        "audit_approval_recorded",
        "Audit approval recorded",
        audit_id=audit_id,
        gate=approval.gate,
        decision=approval.decision,
        memory_proposal=bool(proposal),
    )
    return ApprovalResultOut(
        approval=ApprovalOut.model_validate(approval),
        artifact=ArtifactOut.model_validate(artifact) if artifact else None,
        memoryProposalPath=proposal,
    )
