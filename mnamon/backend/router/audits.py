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
    RetryOut,
)
from schema.findings import FindingOut
from utils.audit_pipeline import forward_gate_decision, retry_pipeline
from utils.audits import (
    audit_detail,
    audits_out,
    create_artifact,
    ensure_patchable,
    get_artifact_or_404,
    get_audit_or_404,
    list_approvals,
    list_artifacts,
    list_audits,
    patch_artifact,
    patch_audit,
    record_approval,
)
from utils.findings import audit_findings, findings_out
from utils.systems import actor_for
from utils.telegram_gates import on_approval_recorded, on_artifact_created, on_audit_patched

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
    return await audits_out(db, await list_audits(db, systemId))


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
    previous = (audit.status, audit.stage)
    patch_audit(audit, payload)
    await db.flush()
    await on_audit_patched(db, audit, previous)
    await db.commit()
    await db.refresh(audit)
    logger.info(
        "audit_updated",
        "Audit updated",
        audit_id=audit_id,
        stage=audit.stage,
        audit_status=audit.status,
    )
    return (await audits_out(db, [audit]))[0]


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
    await on_artifact_created(db, audit, artifact)
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
    summary="Set an artifact's status or merge into its data (405 for sealed findings)",
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
    ensure_patchable(artifact)
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
    summary="Record a human decision at a gate (with its reason)",
)
async def post_approval(
    audit_id: str, payload: ApprovalIn, caller: CallerDep, _limited: Limited, db: Db
) -> ApprovalResultOut:
    audit = await get_audit_or_404(db, audit_id)
    approval, artifact = await record_approval(db, audit, payload, actor_for(caller.id))
    await on_approval_recorded(db, approval)
    await db.commit()
    await db.refresh(approval)
    if artifact is not None:
        await db.refresh(artifact)
    # A pipeline gate: the waiting pipeline resumes with this decision.
    await forward_gate_decision(audit, approval)
    logger.info(
        "audit_approval_recorded",
        "Audit approval recorded",
        audit_id=audit_id,
        gate=approval.gate,
        decision=approval.decision,
    )
    return ApprovalResultOut(
        approval=ApprovalOut.model_validate(approval),
        artifact=ArtifactOut.model_validate(artifact) if artifact else None,
    )


@router.post(
    "/{audit_id}/retry",
    response_model=RetryOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed audit (the pipeline re-runs the failed step)",
)
async def retry_audit(audit_id: str, caller: CallerDep, _limited: Limited, db: Db) -> RetryOut:
    audit = await get_audit_or_404(db, audit_id)
    outcome = await retry_pipeline(audit)
    data = dict(audit.data or {})
    retries = list(data.get("retries") or [])
    retries.append({"by": actor_for(caller.id), "error": data.pop("error", None)})
    data["retries"] = retries
    audit.data = data
    audit.status = "running"
    await db.commit()
    logger.info("audit_retried", "Audit retried", audit_id=audit_id, outcome=outcome)
    return RetryOut(auditId=audit_id, outcome=outcome, status=audit.status)


@router.get(
    "/{audit_id}/findings",
    response_model=list[FindingOut],
    summary="The audit's sealed findings (with annotations and status)",
)
async def get_audit_findings(
    audit_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> list[FindingOut]:
    await get_audit_or_404(db, audit_id)
    out = await findings_out(db, await audit_findings(db, audit_id))
    logger.info("audit_findings_listed", "Audit findings listed", audit_id=audit_id, count=len(out))
    return out
