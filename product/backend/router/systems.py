"""System routes (``/v1/systems``): list / create / get / patch an audited
system, its folder (``system:<id>`` files), copying a conversation attachment
into it, and starting an audit of it.

Systems are NOT scoped by ``X-Client-Id`` (deliberate, for now): every caller
sees every system. The client id is still required for rate limiting, logging
and as the actor of every write; attachments copied in must be the caller's.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from router.workspace_files import build_file_router
from schema.audits import AuditIn, AuditOut
from schema.systems import (
    FileOut,
    FileWriteOut,
    FromAttachmentIn,
    SystemIn,
    SystemOut,
    SystemPatch,
)
from utils.audits import create_audit
from utils.systems import (
    actor_for,
    copy_attachment_to_system,
    create_system,
    list_systems,
    patch_system,
)
from utils.workspace import get_system_or_404, system_namespace

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]


async def system_files_namespace(system_id: str, db: Db) -> str:
    """The system folder's namespace; 404 for an unknown system."""
    await get_system_or_404(db, system_id)
    return system_namespace(system_id)


@router.get("", response_model=list[SystemOut], summary="List every system")
async def get_systems(_caller: CallerDep, _limited: Limited, db: Db) -> list[SystemOut]:
    rows = await list_systems(db)
    logger.info("systems_listed", "Systems listed", item_count=len(rows))
    return [SystemOut.model_validate(r) for r in rows]


@router.post(
    "", response_model=SystemOut, status_code=status.HTTP_201_CREATED, summary="Create a system"
)
async def post_system(
    payload: SystemIn, _caller: CallerDep, _limited: Limited, db: Db
) -> SystemOut:
    system = await create_system(db, payload)
    await db.commit()
    await db.refresh(system)
    logger.info("system_created", "System created", system_id=system.id)
    return SystemOut.model_validate(system)


@router.get("/{system_id}", response_model=SystemOut, summary="Get a system")
async def get_system(system_id: str, _caller: CallerDep, _limited: Limited, db: Db) -> SystemOut:
    return SystemOut.model_validate(await get_system_or_404(db, system_id))


@router.patch("/{system_id}", response_model=SystemOut, summary="Update a system (data is merged)")
async def update_system(
    system_id: str, payload: SystemPatch, _caller: CallerDep, _limited: Limited, db: Db
) -> SystemOut:
    system = await get_system_or_404(db, system_id)
    patch_system(system, payload)
    await db.commit()
    await db.refresh(system)
    logger.info("system_updated", "System updated", system_id=system_id)
    return SystemOut.model_validate(system)


@router.post(
    "/{system_id}/files/from-attachment",
    response_model=FileWriteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Copy one of the caller's conversation attachments into the system folder",
)
async def file_from_attachment(
    system_id: str, payload: FromAttachmentIn, caller: CallerDep, _limited: Limited, db: Db
) -> FileWriteOut:
    await get_system_or_404(db, system_id)
    row, changed = await copy_attachment_to_system(
        db,
        client_id=caller.id,
        system_id=system_id,
        attachment_id=payload.attachmentId,
        path=payload.path,
        reason=payload.reason,
    )
    await db.commit()
    logger.info(
        "system_file_from_attachment",
        "Attachment copied into a system folder",
        system_id=system_id,
        path=row.path,
        version=row.version,
        changed=changed,
    )
    return FileWriteOut(file=FileOut.model_validate(row), changed=changed)


@router.post(
    "/{system_id}/audits",
    response_model=AuditOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start an audit of the system (locks the folder's dossier_version)",
)
async def start_audit(
    system_id: str, payload: AuditIn, caller: CallerDep, _limited: Limited, db: Db
) -> AuditOut:
    system = await get_system_or_404(db, system_id)
    audit = await create_audit(db, system, payload, actor_for(caller.id))
    await db.commit()
    await db.refresh(audit)
    logger.info("audit_created", "Audit created", system_id=system_id, audit_id=audit.id)
    return AuditOut.model_validate(audit)


router.include_router(build_file_router(system_files_namespace), prefix="/{system_id}")
