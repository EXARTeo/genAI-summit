from typing import Any

from fastapi import APIRouter, Depends

from core.security.rate_limit import read_rate_limit
from utils.watch import integrations

router = APIRouter(dependencies=[Depends(read_rate_limit)])


@router.get("")
async def list_integrations() -> dict[str, Any]:
    """Which optional integrations are active (keys set) and what falls back without them."""
    return integrations()
