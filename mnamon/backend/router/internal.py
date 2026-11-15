"""Internal API for the agents service (``/internal``), guarded by the shared
secret (``X-Internal-Secret`` = ``AGENTS_SERVICE_SECRET``) and rate-limited by IP.

Every call is scoped to ONE audit, and through it to one system: the agent
reads that system's folder (each read is a ``read`` event in the ledger, with
the run and trace ids), writes audit artifacts and moves the audit's stage. It
never writes the system folder. Agent memory lives in the agents service.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.internal import require_internal_secret
from core.security.rate_limit import internal_rate_limit
from schema.audits import (
    ArtifactIn,
    ArtifactOut,
    AuditDetail,
    AuditIn,
    AuditOut,
    AuditPatch,
)
from schema.register import RegisterOut
from schema.systems import FileContentOut, FileOut, SystemOut
from utils.audit_pipeline import start_pipeline
from utils.audits import (
    audit_detail,
    create_artifact,
    create_audit,
    get_audit_or_404,
    impact_index,
    patch_audit,
)
from utils.register import on_audit_status, register_out
from utils.telegram_gates import on_artifact_created, on_audit_patched
from utils.workspace import (
    file_content_out,
    get_file,
    get_system_or_404,
    list_tree,
    log_event,
    system_namespace,
)

router = APIRouter(dependencies=[Depends(require_internal_secret), Depends(internal_rate_limit)])
logger = get_logger(__name__)

Db = Annotated[AsyncSession, Depends(get_db)]
AGENT_ACTOR = "agent"


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
    previous = (audit.status, audit.stage)
    patch_audit(audit, payload)
    await db.flush()
    await on_audit_patched(db, audit, previous)
    await on_audit_status(db, audit, previous[0])
    await db.commit()
    await db.refresh(audit)
    logger.info(
        "internal_audit_updated", "Agent updated an audit", audit_id=audit_id, stage=audit.stage
    )
    return AuditOut.model_validate(audit)


@router.get(
    "/audits/{audit_id}/register",
    response_model=RegisterOut,
    summary="The findings register of the audit's system (pipeline hydration)",
)
async def internal_register(audit_id: str, db: Db) -> RegisterOut:
    audit = await get_audit_or_404(db, audit_id)
    out = await register_out(db, audit.system_id)
    logger.info(
        "internal_register_read",
        "Agent read the findings register",
        audit_id=audit_id,
        system_id=audit.system_id,
        count=out.summary.total,
    )
    return out


@router.get(
    "/audits/{audit_id}/files",
    response_model=list[FileOut],
    summary="File tree of the audit's system folder",
)
async def internal_tree(audit_id: str, db: Db, prefix: str | None = None) -> list[FileOut]:
    audit = await get_audit_or_404(db, audit_id)
    rows = await list_tree(db, system_namespace(audit.system_id), prefix)
    return [FileOut.model_validate(r) for r in rows]


@router.get(
    "/audits/{audit_id}/files/{path:path}",
    response_model=FileContentOut,
    summary="Read one file (logged as a `read` event with run and trace ids)",
)
async def internal_read(
    audit_id: str,
    path: str,
    db: Db,
    version: Annotated[int | None, Query(ge=1)] = None,
    run_id: Annotated[str | None, Header(alias="X-Run-Id")] = None,
    trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    agent: Annotated[str | None, Header(alias="X-Agent-Name")] = None,
) -> FileContentOut:
    audit = await get_audit_or_404(db, audit_id)
    namespace = system_namespace(audit.system_id)
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
    await on_artifact_created(db, audit, artifact)
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


@router.get("/impact-index", summary="Per system: the latest audit's findings and tests")
async def internal_impact_index(db: Db) -> list[dict]:
    """What the agents' change judge matches a RegChange against (cross-system, read-only)."""
    return await impact_index(db)


@router.post(
    "/systems/{system_id}/audits",
    response_model=AuditOut,
    status_code=status.HTTP_201_CREATED,
    summary="A new audit started by an agent (the change judge's re-run)",
)
async def internal_start_audit(
    system_id: str,
    payload: AuditIn,
    db: Db,
    agent: Annotated[str | None, Header(alias="X-Agent-Name")] = None,
) -> AuditOut:
    system = await get_system_or_404(db, system_id)
    audit = await create_audit(db, system, payload, _actor(agent))
    await db.commit()
    await db.refresh(audit)
    logger.info("internal_audit_created", "Agent started an audit", audit_id=audit.id)
    await start_pipeline(audit)
    return AuditOut.model_validate(audit)
