"""Regulation routes (``/v1/regulation``): the browser's way to reg-memory.

reg-memory is internal (``X-Internal-Secret``); these routes proxy it, map its
shapes to the frontend's types (``utils/regulation.py``) and record the human
decisions on regulation changes. Like systems and audits they are not scoped
by client id; the caller is the actor of every decision.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SystemTable, get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import _limit, workspace_rate_limit
from core.settings import settings
from schema.regulation import (
    ActivateIn,
    ChangeDecisionIn,
    CheckNowIn,
    DemoMirrorEditIn,
    DocDiffOut,
    DocTextOut,
    JudgeOverrideIn,
    RegChangeOut,
    RegSourceOut,
)
from utils.regulation import (
    decide_change,
    demo_mirror,
    document_diff,
    document_text,
    edit_demo_mirror,
    get_change,
    list_changes,
    list_sources,
    override_system,
    reg_call,
)
from utils.systems import actor_for
from utils.telegram_gates import close_prompts, safe
from utils.workspace import get_system_or_404

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]
#: "Simulate change" edits a page every viewer's Regulation view reads: a tight bucket.
DemoLimited = Annotated[None, Depends(_limit(10, 60, "regulation-demo"))]


@router.get("/sources", response_model=list[RegSourceOut], summary="Sources with their versions")
async def sources(_caller: CallerDep, _limited: Limited) -> list[dict[str, Any]]:
    items = await list_sources()
    logger.info("regulation_sources_listed", "Regulation sources listed", count=len(items))
    return items


@router.get("/documents/{doc_id}/text", response_model=DocTextOut, summary="A version's text")
async def text(
    doc_id: str,
    _caller: CallerDep,
    _limited: Limited,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    return await document_text(doc_id, version)


@router.get(
    "/documents/{doc_id}/diff",
    response_model=DocDiffOut,
    response_model_by_alias=True,
    summary="Unified diff of two versions",
)
async def diff(
    doc_id: str,
    _caller: CallerDep,
    _limited: Limited,
    from_: Annotated[int, Query(alias="from", ge=1)],
    to: Annotated[int, Query(ge=1)],
) -> dict[str, Any]:
    return await document_diff(doc_id, from_, to)


@router.get(
    "/changes", response_model=list[RegChangeOut], summary="Regulation changes, newest first"
)
async def changes(_caller: CallerDep, _limited: Limited, db: Db) -> list[dict[str, Any]]:
    return await list_changes(db)


@router.get("/changes/{change_id}", response_model=RegChangeOut, summary="One regulation change")
async def change(change_id: str, _caller: CallerDep, _limited: Limited, db: Db) -> dict[str, Any]:
    return await get_change(db, change_id)


@router.post(
    "/changes/{change_id}/decision",
    response_model=RegChangeOut,
    summary="Accept (activate the candidate kb release) or reject a change",
)
async def decision(
    change_id: str, payload: ChangeDecisionIn, caller: CallerDep, _limited: Limited, db: Db
) -> dict[str, Any]:
    actor = actor_for(caller.id)
    out = await decide_change(db, change_id, payload.status, actor, payload.reason)
    await safe(close_prompts(db, f"regchange:{change_id}", payload.status, actor))
    await db.commit()  # an accept starts the change judge in the background (judge: running)
    return out


@router.post(
    "/changes/{change_id}/systems/{system_id}",
    response_model=RegChangeOut,
    summary="Override the judge's decision for one system",
)
async def override(
    change_id: str,
    system_id: str,
    payload: JudgeOverrideIn,
    caller: CallerDep,
    _limited: Limited,
    db: Db,
) -> dict[str, Any]:
    system: SystemTable = await get_system_or_404(db, system_id)
    out = await override_system(
        db, change_id, system_id, system.name, payload.decision, actor_for(caller.id)
    )
    await db.commit()
    logger.info("regulation_judge_overridden", "Judge decision overridden", change_id=change_id)
    return out


# ---- pass-through (reg-memory's own shapes) -----------------------------------


@router.get("/releases", summary="kb releases (reg-memory shape)")
async def releases(_caller: CallerDep, _limited: Limited) -> Any:
    return await reg_call("GET", "/v1/releases")


@router.post("/releases/{kb_version}/activate", summary="Activate a kb release (HITL accept)")
async def activate(
    kb_version: str, caller: CallerDep, _limited: Limited, payload: ActivateIn | None = None
) -> Any:
    by = (payload.by if payload and payload.by else None) or actor_for(caller.id)
    out = await reg_call("POST", f"/v1/releases/{kb_version}/activate", json={"by": by})
    logger.info("regulation_release_activated", "kb release activated", kb_version=kb_version)
    return out


@router.post("/check-now", summary="Run a reg-memory watch check now")
async def check_now(caller: CallerDep, _limited: Limited, payload: CheckNowIn | None = None) -> Any:
    body = (payload or CheckNowIn()).model_dump(exclude_none=True)
    timeout = settings.reg_memory.check_timeout_seconds if body.get("wait") else None
    out = await reg_call("POST", "/v1/watch/check-now", json=body, timeout=timeout)
    logger.info("regulation_check_now", "reg-memory check started", wait=bool(body.get("wait")))
    return out


@router.get("/provisions", summary="Search provisions (reg-memory shape)")
async def provisions(request: Request, _caller: CallerDep, _limited: Limited) -> Any:
    return await reg_call("GET", "/v1/provisions", params=dict(request.query_params))


@router.get("/provisions/{provision_id}", summary="One provision (reg-memory shape)")
async def provision(
    provision_id: str, request: Request, _caller: CallerDep, _limited: Limited
) -> Any:
    return await reg_call(
        "GET", f"/v1/provisions/{provision_id}", params=dict(request.query_params)
    )


@router.get("/requirements", summary="Applicable requirements (reg-memory shape)")
async def requirements(request: Request, _caller: CallerDep, _limited: Limited) -> Any:
    return await reg_call("GET", "/v1/requirements", params=dict(request.query_params))


# ---- demo: "Simulate change" on the mirrored guideline page ------------------------------------


@router.get("/demo/mirror", summary="The demo mirror page (reg-memory shape)")
async def get_demo_mirror(_caller: CallerDep, _limited: Limited) -> Any:
    return await demo_mirror()


@router.put("/demo/mirror", summary="Simulate a change: edit the mirror (+ check it now)")
async def put_demo_mirror(
    payload: DemoMirrorEditIn, caller: CallerDep, _limited: DemoLimited
) -> Any:
    """Edit reg-memory's mirrored guideline page (find/replace, append, replace, reset).
    With ``check: true`` the mirror alone is re-checked at once (a RegChange appears in
    the inbox when the page changed). Admin demo control; every edit is logged."""
    edit = payload.model_dump(exclude={"check"}, exclude_none=True)
    if not edit.get("reset"):
        edit.pop("reset", None)
    out = await edit_demo_mirror(edit, check=payload.check)
    release = (out.get("check") or {}).get("release") or {}
    logger.info(
        "regulation_demo_mirror_edited",
        "Demo mirror edited",
        actor=actor_for(caller.id),
        checked=payload.check,
        change_id=release.get("change_id"),
    )
    return out
