"""``GET /internal/systems/{system_id}/memory``: the agents' memory of one system.

Read-only and internal (the caller secret): for debugging and for judges, never
for end users. Agents write memory only through ``remember`` / ``forget``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from core.logging import get_logger
from core.security.internal_trust import require_internal_caller
from harness.checkpointer import get_runtime_pool
from harness.memory import SystemMemoryStore
from harness.memory.entries import is_valid_id
from schema.memory import SystemMemoryOut
from utils.memory import read_system_memory

logger = get_logger(__name__)

router = APIRouter()


def get_memory_store() -> SystemMemoryStore:
    """The store over the runtime pool (overridden in tests)."""
    return SystemMemoryStore(get_runtime_pool())


@router.get(
    "/internal/systems/{system_id}/memory",
    response_model=SystemMemoryOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_internal_caller)],
)
async def get_system_memory(
    system_id: Annotated[str, Path(max_length=128)],
    store: Annotated[SystemMemoryStore, Depends(get_memory_store)],
) -> SystemMemoryOut:
    """The derived ``MEMORY.md`` and every entry with its provenance."""
    if not is_valid_id(system_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid system id.")
    out = await read_system_memory(store, system_id)
    logger.info(
        "system_memory_read",
        "Served a system's memory (internal)",
        system_id=system_id,
        entries=len(out.entries),
    )
    return out
