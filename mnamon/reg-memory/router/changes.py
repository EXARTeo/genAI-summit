from typing import Any

from fastapi import APIRouter, Depends

from core.security.rate_limit import read_rate_limit
from schema.kb import ChangeList
from utils.kb import changes, get_change

router = APIRouter(dependencies=[Depends(read_rate_limit)])


@router.get("", response_model=ChangeList)
async def list_changes() -> ChangeList:
    return changes()


@router.get("/{change_id}")
async def change(change_id: str) -> dict[str, Any]:
    """One RegChange: per-node old/new text, diff, change_type + rationale, impact."""
    return get_change(change_id)
