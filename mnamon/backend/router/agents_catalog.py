"""``GET /v1/agents``: the agents the agents service runs (its ``GET /agents``),
so the chat can pick one."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import conversation_rate_limit
from utils.agents_catalog import list_agents

router = APIRouter()
logger = get_logger(__name__)


@router.get("", summary="Agents available for a conversation")
async def agents(
    _caller: Annotated[Caller, Depends(get_caller)],
    _limited: Annotated[None, Depends(conversation_rate_limit)],
) -> list[dict[str, Any]]:
    items = await list_agents()
    if items is None:
        raise HTTPException(status_code=502, detail="The agents service is unavailable.")
    logger.info("agents_listed", "Agents listed", count=len(items))
    return items
