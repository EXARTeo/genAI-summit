"""Search route (``/v1/search``): find the caller's conversations, messages and
files by a text query. Rate-limited per client; logic in ``utils.search``."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import search_rate_limit
from schema.search import WorkspaceSearchResult
from utils.search import clean_search_query, search_workspace_data

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    response_model=list[WorkspaceSearchResult],
    summary="Search the caller's conversations, messages and files",
)
async def search_workspace(
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(search_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[WorkspaceSearchResult]:
    """Up to ``limit`` matches, newest first. A blank query returns nothing."""
    query = clean_search_query(q)
    if not query:
        return []
    results = await search_workspace_data(db=db, client_id=caller.id, query=query, limit=limit)
    logger.info(
        "workspace_search_completed",
        "Workspace search completed",
        query_length=len(query),
        result_count=len(results),
    )
    return results
