"""Memory routes (``/v1/memory``): the same file routes as a system folder,
over the memory namespaces.

* ``/v1/memory/org/...`` → ``memory:org`` (general, AI Officer approves);
* ``/v1/memory/proposals/...`` → ``memory:proposals`` (agent suggestions);
* ``/v1/memory/systems/{system_id}/...`` → ``memory:system:<id>``.

Activating a proposal is a human copying it into its scope (a PUT here), which
the ledger records with its reason.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from router.workspace_files import build_file_router
from utils.workspace import (
    MEMORY_ORG,
    MEMORY_PROPOSALS,
    get_system_or_404,
    system_memory_namespace,
)

router = APIRouter()


async def org_namespace() -> str:
    return MEMORY_ORG


async def proposals_namespace() -> str:
    return MEMORY_PROPOSALS


async def system_memory(system_id: str, db: Annotated[AsyncSession, Depends(get_db)]) -> str:
    await get_system_or_404(db, system_id)
    return system_memory_namespace(system_id)


router.include_router(build_file_router(org_namespace), prefix="/org")
router.include_router(build_file_router(proposals_namespace), prefix="/proposals")
router.include_router(build_file_router(system_memory), prefix="/systems/{system_id}")
