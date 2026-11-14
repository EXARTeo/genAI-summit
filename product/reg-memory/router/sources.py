from typing import Any, Literal

from fastapi import APIRouter, Depends

from core.security.rate_limit import read_rate_limit, write_rate_limit
from schema.sources import SourceList
from schema.watch import Decision, ProposalList
from utils.sources import decide_proposal, list_proposals, list_sources

router = APIRouter()


@router.get("", response_model=SourceList, dependencies=[Depends(read_rate_limit)])
async def sources() -> SourceList:
    return list_sources()


@router.get("/proposed", response_model=ProposalList, dependencies=[Depends(read_rate_limit)])
async def proposed(
    status: Literal["proposed", "accepted", "rejected", "ignored", "all"] = "proposed",
) -> ProposalList:
    """Documents discovery found that are not in the catalog (triaged, most relevant first)."""
    return list_proposals(status)


@router.post("/proposed/{proposal_id}/accept", dependencies=[Depends(write_rate_limit)])
async def accept(proposal_id: str, body: Decision | None = None) -> dict[str, Any]:
    """Add the proposal to the catalog overlay (data volume); the next check fetches it."""
    return decide_proposal(proposal_id, True, (body or Decision()).by)


@router.post("/proposed/{proposal_id}/reject", dependencies=[Depends(write_rate_limit)])
async def reject(proposal_id: str, body: Decision | None = None) -> dict[str, Any]:
    return decide_proposal(proposal_id, False, (body or Decision()).by)
