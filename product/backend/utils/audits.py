"""Audits: the HITL workflow's stored state.

context → model_profile → scenarios → scenario_analysis → [approve] →
generation_spec → dataset → dataset_analysis → [approve] → tests → findings →
critic → report. Every stage output is an ``audit_artifacts`` row, versioned
per (audit, kind, name); a new version supersedes the slot's earlier live
versions. Every human decision is an ``approvals`` row with its reason
(``reason_category`` + ``comment``). The pipeline hands a rejection's reason to
the next agent, which records the lesson in the agents service's per-system
memory; the backend writes no memory itself.
"""

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
    AuditOut,
    AuditPatch,
)
from utils.workspace import (
    dossier_version,
    plugin_ids,
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


async def impact_index(db: AsyncSession) -> list[dict]:
    """Per system, the evidence of its latest audit with findings (else its latest audit).

    What the agents' impact index matches a RegChange against: live findings
    (requirement, verdict, cited provisions), test results and the requirements
    the audit's context listed. No LLM, no scoring here.
    """
    systems = list((await db.scalars(select(SystemTable).order_by(SystemTable.id))).all())
    out = []
    for system in systems:
        audits = await list_audits(db, system.id)
        chosen, live = None, []
        for audit in audits:  # newest first
            arts = await list_artifacts(db, audit.id, live_only=True)
            if chosen is None:
                chosen, live = audit, arts
            if any(a.kind == "finding" for a in arts):
                chosen, live = audit, arts
                break
        findings = [{**(a.data or {}), "id": a.name} for a in live if a.kind == "finding"]
        tests = [
            t
            for a in live
            if a.kind == "test_result"
            for t in (a.data or {}).get("tests") or []
            if isinstance(t, dict)
        ]
        context = next((a.data or {} for a in live if a.kind == "context"), {})
        out.append(
            {
                "system_id": system.id,
                "name": system.name,
                "audit_id": chosen.id if chosen else None,
                "kb_version": (chosen.data or {}).get("kb_version") if chosen else None,
                "findings": findings,
                "tests": tests,
                "requirements": [
                    r.get("id") for r in context.get("requirements") or [] if isinstance(r, dict)
                ],
            }
        )
    return out


async def get_audit_or_404(db: AsyncSession, audit_id: str) -> AuditTable:
    audit = await db.get(AuditTable, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    return audit


#: The ``data`` fields the UI reads (frontend ``AuditData``), with their defaults.
_UI_DATA_DEFAULTS: dict[str, object] = {
    "stageTraces": {},
    "stageDurations": {},
    "trigger": "manual",
}


def ui_data(audit: AuditTable, system_name: str | None) -> dict:
    """``audits.data`` plus the UI's fields, passed through when the pipeline set
    them and derived otherwise (snake_case aliases the agents may write too)."""
    data = dict(audit.data or {})
    for camel, snake in (
        ("kbVersion", "kb_version"),
        ("cardVersion", "card_version"),
        ("traceId", "trace_id"),
        ("stageTraces", "stage_traces"),
        ("stageDurations", "stage_durations"),
    ):
        if camel not in data and snake in data:
            data[camel] = data[snake]
    data.setdefault("systemName", system_name or audit.system_id)
    data.setdefault("title", f"Audit of {system_name or audit.system_id}")
    for key, default in _UI_DATA_DEFAULTS.items():
        data.setdefault(key, default)
    return data


async def _system_names(db: AsyncSession, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = await db.execute(select(SystemTable.id, SystemTable.name).where(SystemTable.id.in_(ids)))
    return {row.id: row.name for row in rows}


async def audits_out(db: AsyncSession, audits: list[AuditTable]) -> list[AuditOut]:
    names = await _system_names(db, {a.system_id for a in audits})
    out = []
    for audit in audits:
        item = AuditOut.model_validate(audit)
        item.data = ui_data(audit, names.get(audit.system_id))
        out.append(item)
    return out


async def audit_detail(db: AsyncSession, audit_id: str) -> AuditDetail:
    """An audit with every artifact version and every approval."""
    audit = await get_audit_or_404(db, audit_id)
    detail = AuditDetail.model_validate(audit)
    detail.data = ui_data(audit, (await _system_names(db, {audit.system_id})).get(audit.system_id))
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
) -> tuple[ApprovalTable, AuditArtifactTable | None]:
    """Store the decision (with its reason) and set the artifact's status.
    Returns ``(approval, artifact)``."""
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
    await db.flush()
    return approval, artifact
