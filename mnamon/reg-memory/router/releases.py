from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from core.security.rate_limit import read_rate_limit, write_rate_limit
from schema.kb import Activate, Release, ReleaseBuild, ReleaseDiff, ReleaseList
from utils.kb import activate_release, get_release, list_releases, release_diff
from utils.watch import build_release_now

router = APIRouter()


@router.get("", response_model=ReleaseList, dependencies=[Depends(read_rate_limit)])
async def releases() -> ReleaseList:
    return list_releases()


@router.post("", dependencies=[Depends(write_rate_limit)])
async def build_release(body: ReleaseBuild | None = None) -> dict[str, Any]:
    """Snapshot the current texts into a candidate release (+ RegChange if it differs)."""
    return await build_release_now(force=(body or ReleaseBuild()).force)


@router.get(
    "/{from_version}/diff/{to_version}",
    response_model=ReleaseDiff,
    dependencies=[Depends(read_rate_limit)],
)
async def diff(
    from_version: str,
    to_version: str,
    provisions: Annotated[
        list[str] | None, Query(description="only these provision ids (and their children)")
    ] = None,
) -> ReleaseDiff:
    """Provision-level diff between two releases (``content_hash``) + changed obligations."""
    flat = [p.strip() for raw in provisions or [] for p in raw.split(",") if p.strip()]
    return release_diff(from_version, to_version, flat)


@router.get("/{kb_version}", response_model=Release, dependencies=[Depends(read_rate_limit)])
async def release(kb_version: str) -> Release:
    return get_release(kb_version)


@router.post(
    "/{kb_version}/activate", response_model=Release, dependencies=[Depends(write_rate_limit)]
)
async def activate(kb_version: str, body: Activate | None = None) -> Release:
    """The HITL accept (G6): make a candidate release the active kb_version."""
    return activate_release(kb_version, (body or Activate()).by)
