"""Internal API: store a human-approved public reference dataset in the audit's
system folder (``datasets/public/<slug>/``). Same guard and rate limit as
``router.internal``; the only internal route that writes a system folder, and
only these files under that prefix (``utils.public_datasets``)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.internal import require_internal_secret
from core.security.rate_limit import internal_rate_limit
from schema.systems import FileOut, FileTextIn, FileWriteOut
from utils.audits import get_audit_or_404
from utils.public_datasets import public_dataset_path
from utils.workspace import put_file, system_namespace

router = APIRouter(dependencies=[Depends(require_internal_secret), Depends(internal_rate_limit)])
logger = get_logger(__name__)

Db = Annotated[AsyncSession, Depends(get_db)]


@router.put(
    "/audits/{audit_id}/datasets/public/{slug}/{name}",
    response_model=FileWriteOut,
    summary="Store one file of an approved public reference dataset",
)
async def internal_put_public_dataset(
    audit_id: str,
    slug: str,
    name: str,
    payload: FileTextIn,
    db: Db,
    run_id: Annotated[str | None, Header(alias="X-Run-Id")] = None,
    trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    agent: Annotated[str | None, Header(alias="X-Agent-Name")] = None,
) -> FileWriteOut:
    audit = await get_audit_or_404(db, audit_id)
    path = public_dataset_path(slug, name)
    row, changed = await put_file(
        db,
        namespace=system_namespace(audit.system_id),
        path=path,
        content=payload.content.encode("utf-8"),
        actor=f"agent:{agent}" if agent else "agent",
        content_type=payload.contentType,
        reason=payload.reason or "public reference dataset (human-approved candidate)",
        meta=payload.data,
        audit_id=audit_id,
        run_id=run_id,
        trace_id=trace_id,
    )
    await db.commit()
    await db.refresh(row)
    logger.info(
        "internal_public_dataset_stored",
        "Agent stored a public reference dataset file",
        audit_id=audit_id,
        path=path,
        version=row.version,
        changed=changed,
    )
    return FileWriteOut(file=FileOut.model_validate(row), changed=changed)
