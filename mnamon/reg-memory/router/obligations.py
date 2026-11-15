from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.security.rate_limit import read_rate_limit
from schema.kb import ObligationList
from utils.kb import obligations

router = APIRouter(dependencies=[Depends(read_rate_limit)])


@router.get("", response_model=ObligationList)
async def list_obligations(
    role: str | None = Query(None, max_length=40, description="provider | deployer | ..."),
    risk_class: str | None = Query(None, max_length=40, description="high | limited | ..."),
    basis: str | None = Query(None, max_length=80, description="AIA.ANNEX_III.4.a or annex_iii"),
    annex_point: str | None = Query(None, max_length=10, pattern=r"^\d+(\.[a-z])?$"),
    features: Annotated[list[str] | None, Query(description="e.g. interacts_with_persons")] = None,
    exempt_6_3: bool | None = Query(None, description="the system claims the Art. 6(3) derogation"),
    date: Annotated[Date | None, Query(description="in force on this date (default today)")] = None,
    kb_version: str | None = None,
    include_not_applicable: bool = Query(False, description="also rows that do not apply"),
) -> ObligationList:
    """The obligation catalogue at ``kb_version``, activated for a system profile.

    A parameter left out is not checked (no ``features`` = features-gated rows pass)."""
    return obligations(
        kb_version,
        role,
        risk_class,
        basis,
        annex_point,
        features,
        exempt_6_3,
        date,
        include_not_applicable,
    )
