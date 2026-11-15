"""Admin routes (``/v1/admin``): import the seed cases as systems.

Reads only the configured ``SEED_CASES_DIR`` (never a caller-supplied path).
Idempotent: re-running it writes only files whose bytes changed.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from core.settings import settings
from schema.register import RebuildOut
from schema.systems import SeedImportOut
from utils.register import rebuild
from utils.seed_import import import_seed

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/import-seed",
    response_model=SeedImportOut,
    summary="Import every SYS-xxx folder of SEED_CASES_DIR (skips _answer-key/)",
)
async def post_import_seed(
    _caller: Annotated[Caller, Depends(get_caller)],
    _limited: Annotated[None, Depends(workspace_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeedImportOut:
    result = await import_seed(db, settings.workspace.seed_cases_dir)
    await db.commit()
    logger.info(
        "seed_imported",
        "Seed cases imported",
        system_count=len(result.systems),
        files_written=sum(s.filesWritten for s in result.systems),
    )
    return result


@router.post(
    "/rebuild-register",
    response_model=RebuildOut,
    summary="Fold every finished audit into the findings register, oldest first",
)
async def post_rebuild_register(
    _caller: Annotated[Caller, Depends(get_caller)],
    _limited: Annotated[None, Depends(workspace_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
    reset: bool = False,
    systemId: str | None = None,  # noqa: N803
) -> RebuildOut:
    """``reset=true`` drops the register first (human closures are lost)."""
    result = await rebuild(db, reset=reset, system_id=systemId)
    await db.commit()
    logger.info(
        "register_rebuilt",
        "Findings register rebuilt",
        reset=reset,
        system_id=systemId,
        audits=len(result.audits_applied),
        items=result.items,
    )
    return result
