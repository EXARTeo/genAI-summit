"""Internal API for the agents service (``/internal``), guarded by the shared
secret (``X-Internal-Secret`` = ``AGENTS_SERVICE_SECRET``) and rate-limited by IP.

Every call is scoped to ONE audit, and through it to one system: the agent
reads that system's folder and memory (each read is a ``read`` event in the
ledger, with the run and trace ids), writes audit artifacts, moves the audit's
stage, and writes memory **proposals** only. It never writes the system folder
or active memory.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AuditTable, gen_uuid, get_db
from core.logging import get_logger
from core.security.internal import require_internal_secret
from core.security.rate_limit import internal_rate_limit
from schema.audits import (
    ArtifactIn,
    ArtifactOut,
    AuditDetail,
    AuditOut,
    AuditPatch,
    MemoryProposalIn,
)
from schema.systems import FileContentOut, FileOut, FileWriteOut, SystemOut
from utils.audits import audit_detail, create_artifact, get_audit_or_404, patch_audit
from utils.workspace import (
    MEMORY_ORG,
    MEMORY_PROPOSALS,
    file_content_out,
    get_file,
    get_system_or_404,
    list_tree,
    log_event,
    put_file,
    system_memory_namespace,
    system_namespace,
)

router = APIRouter(dependencies=[Depends(require_internal_secret), Depends(internal_rate_limit)])
logger = get_logger(__name__)

Db = Annotated[AsyncSession, Depends(get_db)]
Scope = Literal["system", "memory", "org"]
AGENT_ACTOR = "agent"


def _namespace(audit: AuditTable, scope: Scope) -> str:
    if scope == "memory":
        return system_memory_namespace(audit.system_id)
    if scope == "org":
        return MEMORY_ORG
    return system_namespace(audit.system_id)


def _actor(agent: str | None) -> str:
    return f"{AGENT_ACTOR}:{agent}" if agent else AGENT_ACTOR


class AuditContextOut(BaseModel):
    """What the agent needs to start: the audit (artifacts, approvals) and its system."""

    audit: AuditDetail
    system: SystemOut


@router.get("/audits/{audit_id}", response_model=AuditContextOut, summary="Audit + system")
async def internal_audit(audit_id: str, db: Db) -> AuditContextOut:
    detail = await audit_detail(db, audit_id)
    system = await get_system_or_404(db, detail.systemId)
    return AuditContextOut(audit=detail, system=SystemOut.model_validate(system))


@router.patch("/audits/{audit_id}", response_model=AuditOut, summary="Move the audit's stage")
async def internal_patch_audit(audit_id: str, payload: AuditPatch, db: Db) -> AuditOut:
    audit = await get_audit_or_404(db, audit_id)
    patch_audit(audit, payload)
    await db.commit()
    await db.refresh(audit)
    logger.info(
        "internal_audit_updated", "Agent updated an audit", audit_id=audit_id, stage=audit.stage
    )
    return AuditOut.model_validate(audit)


@router.get(
    "/audits/{audit_id}/files",
    response_model=list[FileOut],
    summary="File tree of the audit's system folder (scope=system), its memory or org memory",
)
async def internal_tree(
    audit_id: str, db: Db, scope: Scope = "system", prefix: str | None = None
) -> list[FileOut]:
    audit = await get_audit_or_404(db, audit_id)
    return [
        FileOut.model_validate(r) for r in await list_tree(db, _namespace(audit, scope), prefix)
    ]


@router.get(
    "/audits/{audit_id}/files/{path:path}",
    response_model=FileContentOut,
    summary="Read one file (logged as a `read` event with run and trace ids)",
)
async def internal_read(
    audit_id: str,
    path: str,
    db: Db,
    scope: Scope = "system",
    version: Annotated[int | None, Query(ge=1)] = None,
    run_id: Annotated[str | None, Header(alias="X-Run-Id")] = None,
    trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    agent: Annotated[str | None, Header(alias="X-Agent-Name")] = None,
) -> FileContentOut:
    audit = await get_audit_or_404(db, audit_id)
    namespace = _namespace(audit, scope)
    row, content = await get_file(db, namespace, path, version)
    await log_event(
        db,
        namespace=namespace,
        path=row.path,
        version=row.version,
        action="read",
        actor=_actor(agent),
        audit_id=audit_id,
        run_id=run_id,
        trace_id=trace_id,
    )
    await db.commit()
    logger.info(
        "internal_file_read",
        "Agent read a workspace file",
        audit_id=audit_id,
        namespace=namespace,
        path=row.path,
        version=row.version,
    )
    return file_content_out(row, content)


@router.post(
    "/audits/{audit_id}/artifacts",
    response_model=ArtifactOut,
    status_code=status.HTTP_201_CREATED,
    summary="Write a new artifact version for the audit",
)
async def internal_artifact(
    audit_id: str,
    payload: ArtifactIn,
    db: Db,
    agent: Annotated[str | None, Header(alias="X-Agent-Name")] = None,
) -> ArtifactOut:
    audit = await get_audit_or_404(db, audit_id)
    artifact = await create_artifact(db, audit, payload, _actor(agent))
    await db.commit()
    await db.refresh(artifact)
    logger.info(
        "internal_artifact_created",
        "Agent wrote an audit artifact",
        audit_id=audit_id,
        kind=artifact.kind,
        version=artifact.version,
    )
    return ArtifactOut.model_validate(artifact)


@router.post(
    "/audits/{audit_id}/memory-proposals",
    response_model=FileWriteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Suggest a memory entry (memory:proposals/<system>/<name>; inactive until approved)",
)
async def internal_memory_proposal(
    audit_id: str,
    payload: MemoryProposalIn,
    db: Db,
    run_id: Annotated[str | None, Header(alias="X-Run-Id")] = None,
    trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    agent: Annotated[str | None, Header(alias="X-Agent-Name")] = None,
) -> FileWriteOut:
    audit = await get_audit_or_404(db, audit_id)
    name = payload.name or f"PROP-{gen_uuid()[:8]}"
    extension = "" if "." in name else (".yaml" if "yaml" in payload.contentType else ".md")
    row, changed = await put_file(
        db,
        namespace=MEMORY_PROPOSALS,
        path=f"{audit.system_id}/{name}{extension}",
        content=payload.content.encode("utf-8"),
        content_type=payload.contentType,
        actor=_actor(agent),
        reason=payload.reason,
        meta={"system_id": audit.system_id, "status": "proposed", "audit_id": audit_id},
        audit_id=audit_id,
        run_id=run_id,
        trace_id=trace_id,
    )
    await db.commit()
    logger.info(
        "internal_memory_proposed",
        "Agent proposed a memory entry",
        audit_id=audit_id,
        path=row.path,
    )
    return FileWriteOut(file=FileOut.model_validate(row), changed=changed)
