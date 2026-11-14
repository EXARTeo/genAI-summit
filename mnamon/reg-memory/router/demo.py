from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from core.security.rate_limit import read_rate_limit, write_rate_limit
from schema.watch import MirrorEdit, MirrorOut
from utils.demo import edit, mirror_html, mirror_out

# Public page (no secret): what the demo source fetches and Firecrawl could monitor.
public_router = APIRouter(dependencies=[Depends(read_rate_limit)])
router = APIRouter()


@public_router.get("/art6-guidelines.html", response_class=HTMLResponse, include_in_schema=False)
async def mirror_page() -> HTMLResponse:
    return HTMLResponse(mirror_html(), headers={"Cache-Control": "no-store"})


@router.get("", response_model=MirrorOut, dependencies=[Depends(read_rate_limit)])
async def mirror() -> MirrorOut:
    return mirror_out()


@router.put("", response_model=MirrorOut, dependencies=[Depends(write_rate_limit)])
async def edit_mirror(body: MirrorEdit) -> MirrorOut:
    """Edit the mirror (replace, find/replace, append, reset); then POST /v1/watch/check-now."""
    return edit(body)
