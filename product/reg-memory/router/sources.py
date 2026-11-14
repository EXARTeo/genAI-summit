from fastapi import APIRouter, Depends

from core.security.rate_limit import read_rate_limit
from schema.sources import SourceList
from utils.sources import list_sources

router = APIRouter()


@router.get("", response_model=SourceList, dependencies=[Depends(read_rate_limit)])
async def sources() -> SourceList:
    return list_sources()
