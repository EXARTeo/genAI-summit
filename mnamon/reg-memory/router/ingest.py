from fastapi import APIRouter, Depends, status

from core.security.rate_limit import ingest_rate_limit, read_rate_limit
from schema.ingest import IngestAccepted, IngestRequest, IngestRun
from utils.ingest import get_run, start_ingest

router = APIRouter()


@router.post(
    "",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(ingest_rate_limit)],
)
async def ingest(body: IngestRequest | None = None) -> IngestAccepted:
    body = body or IngestRequest()
    return IngestAccepted(run_id=start_ingest(body.source_ids, body.force))


@router.get("/{run_id}", response_model=IngestRun, dependencies=[Depends(read_rate_limit)])
async def ingest_run(run_id: str) -> IngestRun:
    return get_run(run_id)
