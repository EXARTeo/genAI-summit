"""Audits: the HITL workflow's stored state.

context → model_profile → scenarios → scenario_analysis → [approve] →
generation_spec → dataset → dataset_analysis → [approve] → tests → findings →
critic → report. Every stage output is an ``audit_artifacts`` row, versioned
per (audit, kind, name); a new version supersedes the slot's earlier live
versions. Every human decision is an ``approvals`` row with its reason; a
rejection (or change request) with a reason also writes a memory proposal
file under ``memory:proposals`` (inactive until a human activates it).
"""

from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ApprovalTable, AuditArtifactTable, AuditTable, SystemTable
from schema.audits import (
    ApprovalIn,
    ApprovalOut,
    ArtifactIn,
    ArtifactOut,
    ArtifactPatch,
    AuditDetail,
    AuditIn,
    AuditPatch,
)
from utils.workspace import (
    MEMORY_PROPOSALS,
    dossier_version,
    plugin_ids,
    put_file,
    system_namespace,
)

#: Statuses that are still "live" (a newer version supersedes them).
_LIVE = ("proposed", "approved", "changes_requested")
_DECISION_STATUS = {
    "approved": "approved",
    "rejected": "rejected",
    "changes_requested": "changes_requested",
}


async def create_audit(
    db: AsyncSession, system: SystemTable, payload: AuditIn, actor: str
) -> AuditTable:
    """A new audit that locks the system folder's current ``dossier_version``."""
    data = {
        "dossier_version": await dossier_version(db, system_namespace(system.id)),
        "plugin_ids": await plugin_ids(db, system.id),
        **payload.data,
    }
    audit = AuditTable(
        system_id=system.id, stage=payload.stage, status="open", created_by=actor, data=data
    )
    db.add(audit)
    await db.flush()
    return audit


async def get_audit_or_404(db: AsyncSession, audit_id: str) -> AuditTable:
    audit = await db.get(AuditTable, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    return audit


async def audit_detail(db: AsyncSession, audit_id: str) -> AuditDetail:
    """An audit with every artifact version and every approval."""
    audit = await get_audit_or_404(db, audit_id)
    detail = AuditDetail.model_validate(audit)
    detail.artifacts = [ArtifactOut.model_validate(a) for a in await list_artifacts(db, audit_id)]
    detail.approvals = [ApprovalOut.model_validate(a) for a in await list_approvals(db, audit_id)]
    return detail


async def validate_conversation_subject(
    db: AsyncSession, system_id: str | None, audit_id: str | None
) -> None:
    """404 unless the system / audit a new conversation names exist (and match)."""
    if system_id is not None and await db.get(SystemTable, system_id) is None:
        raise HTTPException(status_code=404, detail="System not found.")
    if audit_id is not None:
        audit = await get_audit_or_404(db, audit_id)
        if system_id is not None and audit.system_id != system_id:
            raise HTTPException(status_code=422, detail="The audit belongs to another system.")


async def list_audits(db: AsyncSession, system_id: str | None = None) -> list[AuditTable]:
    query = select(AuditTable).order_by(AuditTable.created_at.desc(), AuditTable.id)
    if system_id:
        query = query.where(AuditTable.system_id == system_id)
    return list((await db.scalars(query)).all())


def patch_audit(audit: AuditTable, payload: AuditPatch) -> None:
    if payload.status is not None:
        audit.status = payload.status
    if payload.stage is not None:
        audit.stage = payload.stage
    if payload.data is not None:
        audit.data = {**(audit.data or {}), **payload.data}


async def list_artifacts(
    db: AsyncSession, audit_id: str, kind: str | None = None, live_only: bool = False
) -> list[AuditArtifactTable]:
    query = select(AuditArtifactTable).where(AuditArtifactTable.audit_id == audit_id)
    if kind:
        query = query.where(AuditArtifactTable.kind == kind)
    if live_only:
        query = query.where(AuditArtifactTable.status != "superseded")
    query = query.order_by(
        AuditArtifactTable.created_at, AuditArtifactTable.kind, AuditArtifactTable.version
    )
    return list((await db.scalars(query)).all())


async def list_approvals(db: AsyncSession, audit_id: str) -> list[ApprovalTable]:
    return list(
        (
            await db.scalars(
                select(ApprovalTable)
                .where(ApprovalTable.audit_id == audit_id)
                .order_by(ApprovalTable.at, ApprovalTable.id)
            )
        ).all()
    )


async def get_artifact_or_404(
    db: AsyncSession, audit_id: str, artifact_id: str
) -> AuditArtifactTable:
    artifact = await db.get(AuditArtifactTable, artifact_id)
    if artifact is None or artifact.audit_id != audit_id:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return artifact


async def create_artifact(
    db: AsyncSession, audit: AuditTable, payload: ArtifactIn, actor: str
) -> AuditArtifactTable:
    """The next version of the (kind, name) slot; earlier live versions → superseded."""
    if payload.parentId:
        await get_artifact_or_404(db, audit.id, payload.parentId)
    slot = (
        AuditArtifactTable.audit_id == audit.id,
        AuditArtifactTable.kind == payload.kind,
        AuditArtifactTable.name == payload.name,
    )
    last = await db.scalar(select(func.max(AuditArtifactTable.version)).where(*slot))
    await db.execute(
        update(AuditArtifactTable)
        .where(*slot, AuditArtifactTable.status.in_(_LIVE))
        .values(status="superseded")
    )
    artifact = AuditArtifactTable(
        audit_id=audit.id,
        kind=payload.kind,
        name=payload.name,
        version=(last or 0) + 1,
        status=payload.status,
        data=payload.data,
        file_refs=payload.fileRefs,
        parent_id=payload.parentId,
        created_by=actor,
    )
    db.add(artifact)
    await db.flush()
    return artifact


def patch_artifact(artifact: AuditArtifactTable, payload: ArtifactPatch) -> None:
    if payload.status is not None:
        artifact.status = payload.status
    if payload.data is not None:
        artifact.data = {**(artifact.data or {}), **payload.data}


async def record_approval(
    db: AsyncSession, audit: AuditTable, payload: ApprovalIn, actor: str
) -> tuple[ApprovalTable, AuditArtifactTable | None, str | None]:
    """Store the decision, set the artifact's status, and for a rejection or a
    change request with a reason write a memory proposal. Returns
    ``(approval, artifact, proposal_path)``."""
    artifact = (
        await get_artifact_or_404(db, audit.id, payload.artifactId) if payload.artifactId else None
    )
    approval = ApprovalTable(
        audit_id=audit.id,
        artifact_id=artifact.id if artifact else None,
        gate=payload.gate,
        decision=payload.decision,
        reason_category=payload.reasonCategory,
        comment=payload.comment,
        edits=payload.edits,
        decided_by=actor,
    )
    db.add(approval)
    await db.flush()
    if artifact is not None:
        artifact.status = _DECISION_STATUS[payload.decision]

    proposal_path = None
    if payload.decision != "approved" and (payload.reasonCategory or payload.comment):
        proposal_path = await _write_memory_proposal(db, audit, approval, artifact)
    await db.flush()
    return approval, artifact, proposal_path


async def _write_memory_proposal(
    db: AsyncSession,
    audit: AuditTable,
    approval: ApprovalTable,
    artifact: AuditArtifactTable | None,
) -> str:
    entry_id = f"PROP-{approval.id[:8]}"
    entry: dict[str, Any] = {
        "id": entry_id,
        "scope": f"system:{audit.system_id}",
        "kind": "correction",
        "applies_to": {
            "gate": approval.gate,
            "artifact_kind": artifact.kind if artifact else None,
            "artifact_name": artifact.name if artifact else None,
        },
        "human_decision": approval.decision,
        "reason_category": approval.reason_category,
        "rationale": approval.comment,
        "edits": approval.edits or {},
        "author": approval.decided_by,
        "status": "proposed",
        "source": {
            "audit_id": audit.id,
            "artifact_id": artifact.id if artifact else None,
            "artifact_version": artifact.version if artifact else None,
            "approval_id": approval.id,
        },
    }
    path = f"{audit.system_id}/{entry_id}.yaml"
    await put_file(
        db,
        namespace=MEMORY_PROPOSALS,
        path=path,
        content=yaml.safe_dump(entry, sort_keys=False, allow_unicode=True).encode("utf-8"),
        content_type="application/yaml",
        actor=approval.decided_by,
        reason=f"{approval.decision} at gate {approval.gate}: {approval.reason_category or ''}",
        meta={"system_id": audit.system_id, "status": "proposed"},
        audit_id=audit.id,
    )
    return path
