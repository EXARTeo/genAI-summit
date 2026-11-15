from fastapi import APIRouter, Depends, Query

from core.security.rate_limit import read_rate_limit
from schema.kb import (
    Interpretation,
    InterpretationList,
    Provision,
    ProvisionList,
    SearchResult,
)
from utils.kb import (
    get_interpretation,
    get_provision,
    search_interpretations,
    search_provisions,
    search_regulation,
)

router = APIRouter(dependencies=[Depends(read_rate_limit)])
interpretations_router = APIRouter(dependencies=[Depends(read_rate_limit)])


@router.get("", response_model=ProvisionList)
async def provisions(
    kb_version: str | None = None,
    prefix: str | None = Query(None, max_length=80, description="e.g. AIA.10 or AIA.ANNEX_III"),
    q: str | None = Query(None, min_length=2, max_length=200, description="text search"),
    instrument: str | None = Query(None, max_length=20),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    with_text: bool = True,
) -> ProvisionList:
    return search_provisions(kb_version, prefix, q, instrument, limit, offset, with_text)


@router.get("/search", response_model=SearchResult)
async def search(
    q: str = Query(..., min_length=2, max_length=200, description="words to find"),
    kb_version: str | None = None,
    instrument: str | None = Query(None, max_length=20),
    limit: int = Query(10, ge=1, le=50),
) -> SearchResult:
    """Ranked hits, one per article: label, title (own or inherited), snippet, score."""
    return search_regulation(kb_version, q, limit, instrument)


@router.get("/{provision_id}", response_model=Provision)
async def provision(provision_id: str, kb_version: str | None = None) -> Provision:
    return Provision(**get_provision(provision_id, kb_version))


@interpretations_router.get("", response_model=InterpretationList)
async def interpretations(
    kb_version: str | None = None,
    relates_to: str | None = Query(None, max_length=80),
    source_id: str | None = Query(None, max_length=80),
    limit: int = Query(200, ge=1, le=1000),
) -> InterpretationList:
    return search_interpretations(kb_version, relates_to, source_id, limit)


@interpretations_router.get("/{interpretation_id}", response_model=Interpretation)
async def interpretation(interpretation_id: str, kb_version: str | None = None) -> Interpretation:
    return Interpretation(**get_interpretation(interpretation_id, kb_version))
