"""Risk classification of a system (plan 02 §7): runs, human decisions, stale marks
and the obligations preview.

A run (``CLS-<SYSTEM_ID>-<YYYYMMDD>-<HHMM>``, ``-2`` ... on a collision) is created
``running``; a background task sends the card and the readable dossier documents to
the agents service (``POST /systems/{id}/classify``, awaited like the change judge)
and stores its ``ClassificationResult`` once: ``proposed``, or ``failed``. A human
approves (the card is updated: ``system-card.yaml`` + ``classification.yaml`` new
versions, ``data.card`` merged, system ``active``; the earlier approved run is
``superseded``) or rejects with a reason (the next run gets it as feedback).

``status`` only moves through :func:`move`, and every move appends a
``classification_events`` row (append-only in the database). An accepted regulation
change that touches a provision an approved run relied on marks it ``stale``
(:func:`mark_stale_for_change`, no LLM); the card is not changed.

This module must not import ``utils.regulation`` (that one calls
:func:`mark_stale_for_change`), so reg-memory is called through its own small client.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime
from typing import Any

import httpx
import yaml
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    ClassificationEventTable,
    SessionLocal,
    SystemClassificationTable,
    SystemTable,
)
from core.logging import get_logger
from core.settings import settings
from schema.classifications import (
    ClassificationEventOut,
    ClassificationIn,
    ClassificationOut,
    ClassificationResult,
    DecisionIn,
    ObligationsPreviewOut,
)
from utils.agents import internal_headers
from utils.workspace import get_file, list_tree, put_file, system_namespace

logger = get_logger(__name__)

#: Who writes the agent's moves in the event log.
AGENT_ACTOR = "agent:risk-classifier"
CARD_PATH = "system-card.yaml"
CLASSIFICATION_PATH = "classification.yaml"
#: Documents the agent reads (others are stored but not sent: no PDF/DOCX extraction).
READABLE_SUFFIXES = (".md", ".txt", ".yaml", ".yml", ".json")
DOC_MAX_CHARS = 6000
DOCS_MAX_CHARS = 30000
#: The state machine (§7.1).
TRANSITIONS: dict[str, frozenset[str]] = {
    "running": frozenset({"proposed", "failed"}),
    "proposed": frozenset({"approved", "rejected"}),
    "approved": frozenset({"stale", "superseded"}),
    "stale": frozenset({"superseded"}),
}
#: Statuses whose card is in force (a stale class stays in force until a new approval).
IN_FORCE = ("approved", "stale")
#: Provisions every approved classification relies on, besides its citations (§7.5).
CORE_PROVISIONS = ("AIA.5", "AIA.6", "AIA.50", "AIA.25", "AIA.3.3", "AIA.3.4")
REG_SECRET_HEADER = "X-Internal-Secret"  # noqa: S105 - a header name

_ANNEX_RE = re.compile(
    r"annex[\s_]*(iii|ii|i)\b(?:[\s._]*(\d+)(?:\s*[.(]\s*([a-z])\b)?)?", re.IGNORECASE
)
_CLAIM_KEYS = ("exempt_6_3", "art_6_3_claim", "derogation_6_3", "art_6_3")

#: Test seams: an ``httpx.MockTransport`` for the agents service / reg-memory, and the
#: background task's own sessions.
agents_transport: httpx.AsyncBaseTransport | None = None
reg_transport: httpx.AsyncBaseTransport | None = None
session_factory: Any = SessionLocal
#: Runs in the background (kept referenced until they finish).
_classify_tasks: set[asyncio.Task[Any]] = set()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---- ids, reads, the state machine -----------------------------------------------------------


async def readable_classification_id(
    db: AsyncSession, system_id: str, now: datetime | None = None
) -> str:
    """``CLS-<SYSTEM_ID>-<YYYYMMDD>-<HHMM>`` (UTC), plus ``-2``, ``-3``, ... when taken."""
    base = f"CLS-{system_id}-{(now or datetime.now(UTC)):%Y%m%d-%H%M}"
    taken = set(
        (
            await db.scalars(
                select(SystemClassificationTable.id).where(
                    or_(
                        SystemClassificationTable.id == base,
                        SystemClassificationTable.id.like(f"{base}-%"),
                    )
                )
            )
        ).all()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def list_classifications(db: AsyncSession, system_id: str) -> list[SystemClassificationTable]:
    """Every run of the system, newest first."""
    return list(
        (
            await db.scalars(
                select(SystemClassificationTable)
                .where(SystemClassificationTable.system_id == system_id)
                .order_by(
                    SystemClassificationTable.created_at.desc(),
                    SystemClassificationTable.id.desc(),
                )
            )
        ).all()
    )


async def get_classification(
    db: AsyncSession, system_id: str, classification_id: str
) -> SystemClassificationTable:
    row = await db.get(SystemClassificationTable, classification_id)
    if row is None or row.system_id != system_id:
        raise HTTPException(status_code=404, detail="Classification not found.")
    return row


async def classifications_out(
    db: AsyncSession, rows: list[SystemClassificationTable]
) -> list[ClassificationOut]:
    """Rows with their events (oldest event first)."""
    if not rows:
        return []
    events = (
        await db.scalars(
            select(ClassificationEventTable)
            .where(ClassificationEventTable.classification_id.in_([r.id for r in rows]))
            .order_by(ClassificationEventTable.at, ClassificationEventTable.id)
        )
    ).all()
    by_row: dict[str, list[ClassificationEventOut]] = {}
    for e in events:
        by_row.setdefault(e.classification_id, []).append(ClassificationEventOut.model_validate(e))
    out = []
    for r in rows:
        item = ClassificationOut.model_validate(r)
        item.events = by_row.get(r.id, [])
        out.append(item)
    return out


async def add_event(
    db: AsyncSession,
    row: SystemClassificationTable,
    action: str,
    actor: str,
    *,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> ClassificationEventTable:
    event = ClassificationEventTable(
        classification_id=row.id,
        system_id=row.system_id,
        action=action,
        actor=actor,
        reason=reason,
        data=data or {},
        at=_now(),
    )
    db.add(event)
    await db.flush()
    return event


async def move(
    db: AsyncSession,
    row: SystemClassificationTable,
    to: str,
    actor: str,
    *,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """The only way ``status`` changes: along :data:`TRANSITIONS`, with an event (409 else)."""
    if to not in TRANSITIONS.get(row.status, frozenset()):
        raise HTTPException(
            status_code=409, detail=f"A {row.status} classification cannot become {to}."
        )
    row.status = to
    row.updated_at = _now()
    await add_event(db, row, to, actor, reason=reason, data=data)


def store_result(row: SystemClassificationTable, result: dict[str, Any]) -> None:
    """Write the result once (refuses a second write)."""
    if row.result is not None:
        raise ValueError(f"{row.id} already has a result.")
    row.result = result
    row.kb_version = result.get("kb_version") or row.kb_version
    row.trace_id = result.get("trace_id") or row.trace_id


# ---- the request to the agents service -------------------------------------------------------


def _parse_card(text: str) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


async def current_card(db: AsyncSession, system: SystemTable) -> tuple[dict[str, Any], int | None]:
    """The card: ``system-card.yaml`` (current version) when it parses, else ``data.card``."""
    try:
        file_row, content = await get_file(db, system_namespace(system.id), CARD_PATH)
    except HTTPException:
        file_row, content = None, b""
    card = _parse_card(content.decode("utf-8", errors="replace")) if file_row else None
    if card is not None:
        return card, file_row.version
    return dict((system.data or {}).get("card") or {}), None


def _is_readable_doc(path: str) -> bool:
    name = path.lower()
    if path.startswith("docs/"):
        return name.endswith(READABLE_SUFFIXES)
    return "/" not in path and name.endswith(".md")


async def build_request(
    db: AsyncSession, system: SystemTable, classification_id: str, feedback: dict | None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """``(body, input snapshot, dossier_version)`` for ``POST /systems/{id}/classify``."""
    card, card_version = await current_card(db, system)
    card = {**card, "id": card.get("id") or system.id, "name": card.get("name") or system.name}
    dossier: dict[str, int] = {}
    if card_version is not None:
        dossier[CARD_PATH] = card_version
    documents: list[dict[str, Any]] = []
    not_read: list[str] = []
    budget = DOCS_MAX_CHARS
    namespace = system_namespace(system.id)
    for file_row in await list_tree(db, namespace):
        if file_row.path in (CARD_PATH, CLASSIFICATION_PATH):
            continue
        if not _is_readable_doc(file_row.path):
            if file_row.path.startswith("docs/"):
                not_read.append(file_row.path)
            continue
        if budget <= 0:
            not_read.append(file_row.path)
            continue
        _, content = await get_file(db, namespace, file_row.path)
        text = content.decode("utf-8", errors="replace")[: min(DOC_MAX_CHARS, budget)]
        budget -= len(text)
        documents.append({"path": file_row.path, "version": file_row.version, "text": text})
        dossier[file_row.path] = file_row.version
    body = {
        "classification_id": classification_id,
        "kb_version": None,
        "card": card,
        "documents": documents,
        "feedback": feedback,
        "trace": {"name": f"classify:{classification_id}"},
    }
    snapshot = {
        "card": card,
        "documents": [{"path": d["path"], "version": d["version"]} for d in documents],
        "not_read": not_read,
        "feedback": feedback,
    }
    return body, snapshot, dossier


async def _feedback_from(
    db: AsyncSession, system_id: str, previous_id: str | None
) -> dict[str, Any] | None:
    """The previous run's last rejection reason, as ``{source: human, reason}``."""
    if not previous_id:
        return None
    previous = await db.get(SystemClassificationTable, previous_id)
    if previous is None or previous.system_id != system_id:
        raise HTTPException(status_code=404, detail="Previous classification not found.")
    reason = await db.scalar(
        select(ClassificationEventTable.reason)
        .where(
            ClassificationEventTable.classification_id == previous_id,
            ClassificationEventTable.action == "rejected",
        )
        .order_by(ClassificationEventTable.at.desc())
        .limit(1)
    )
    return {"source": "human", "reason": reason} if reason else None


async def create_classification(
    db: AsyncSession, system: SystemTable, payload: ClassificationIn, actor: str
) -> tuple[SystemClassificationTable, dict[str, Any]]:
    """A ``running`` row (+ ``created`` event) and the request body to send; 409 when
    the system already has a running one."""
    running = await db.scalar(
        select(SystemClassificationTable.id).where(
            SystemClassificationTable.system_id == system.id,
            SystemClassificationTable.status == "running",
        )
    )
    if running is not None:
        raise HTTPException(status_code=409, detail=f"{running} is still running.")
    feedback = await _feedback_from(db, system.id, payload.previousId)
    cid = await readable_classification_id(db, system.id)
    body, snapshot, dossier = await build_request(db, system, cid, feedback)
    now = _now()
    row = SystemClassificationTable(
        id=cid,
        system_id=system.id,
        status="running",
        dossier_version=dossier,
        input=snapshot,
        previous_id=payload.previousId,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    await add_event(db, row, "created", actor, data={"previous_id": payload.previousId})
    return row, body


# ---- the background run ----------------------------------------------------------------------


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    detail = body.get("detail") if isinstance(body, dict) else body
    return str(detail)[:500]


async def call_classifier(system_id: str, body: dict[str, Any]) -> tuple[dict | None, str | None]:
    """``(result, None)`` or ``(None, error)``; never raises."""
    url = f"{settings.upstream.agents_service_url.rstrip('/')}/systems/{system_id}/classify"
    try:
        async with httpx.AsyncClient(
            timeout=settings.upstream.classify_timeout_s, transport=agents_transport
        ) as client:
            response = await client.post(url, json=body, headers=internal_headers())
    except httpx.HTTPError as exc:
        return None, f"The agents service is not reachable ({type(exc).__name__})."
    if response.status_code >= 300:
        return None, f"The agents service answered {response.status_code}: " + _error_detail(
            response
        )
    try:
        result = ClassificationResult.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        return None, f"The classifier's answer is not a ClassificationResult: {exc}"[:500]
    return result.model_dump(mode="json"), None


async def finish_classification(
    db: AsyncSession, classification_id: str, result: dict | None, error: str | None
) -> SystemClassificationTable | None:
    """Store the result (``proposed``) or the error (``failed``); flushed, not committed."""
    row = await db.get(SystemClassificationTable, classification_id)
    if row is None or row.status != "running":
        return None
    if result is not None:
        store_result(row, result)
        await move(
            db,
            row,
            "proposed",
            AGENT_ACTOR,
            data={
                "risk_class": result.get("risk_class"),
                "route": result.get("route"),
                "needs_human": result.get("needs_human"),
            },
        )
    else:
        row.error = error
        await move(db, row, "failed", AGENT_ACTOR, reason=error)
    return row


async def run_classification(system_id: str, classification_id: str, body: dict[str, Any]) -> str:
    """Call the classifier and record its outcome in a fresh session: ``proposed`` / ``failed``."""
    result, error = await call_classifier(system_id, body)
    try:
        async with session_factory() as db:
            row = await finish_classification(db, classification_id, result, error)
            await db.commit()
    except Exception as exc:
        logger.warning(
            "classification_store_failed",
            "Could not store the classification outcome",
            classification_id=classification_id,
            error=type(exc).__name__,
        )
        return "failed"
    outcome = row.status if row is not None else "gone"
    logger.info(
        "classification_finished",
        "Risk classification finished",
        system_id=system_id,
        classification_id=classification_id,
        outcome=outcome,
    )
    return outcome


def start_classification(
    system_id: str, classification_id: str, body: dict[str, Any]
) -> asyncio.Task[str]:
    """Run in the background (call after the ``running`` row is committed)."""
    task = asyncio.create_task(run_classification(system_id, classification_id, body))
    _classify_tasks.add(task)
    task.add_done_callback(_classify_tasks.discard)
    return task


# ---- the human decision ----------------------------------------------------------------------


def approved_card(
    card: dict[str, Any], row: SystemClassificationTable, actor: str, at: str
) -> dict[str, Any]:
    """The card with the §7.3 keys from an approved result (keys ``card_profile()`` reads)."""
    result = row.result or {}
    art = result.get("art6_3") or {}
    features = (result.get("transparency") or {}).get("features")
    if not isinstance(features, list):
        features = card.get("features") if isinstance(card.get("features"), list) else []
    return {
        **card,
        "risk_class": result.get("risk_class"),
        "annex_basis": result.get("annex_basis"),
        "role": result.get("role") or card.get("role"),
        "features": features,
        "art_6_3_claim": {
            "claimed": art.get("holds") is True,
            "condition": art.get("condition"),
            "assessed_in": row.id,
        },
        "classification": {
            "id": row.id,
            "kb_version": row.kb_version,
            "approved_by": actor,
            "approved_at": at,
        },
        "provenance": "classified_by_agent_approved_by_human",
    }


def _yaml(data: dict[str, Any]) -> bytes:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode("utf-8")


async def _approve(
    db: AsyncSession, system: SystemTable, row: SystemClassificationTable, actor: str, reason: str
) -> None:
    at = datetime.now(UTC).isoformat()
    for other in await list_classifications(db, system.id):
        if other.id != row.id and other.status in IN_FORCE:
            await move(db, other, "superseded", actor, data={"superseded_by": row.id})
    await move(db, row, "approved", actor, reason=reason or None)
    card, _ = await current_card(db, system)
    card = approved_card(card, row, actor, at)
    namespace = system_namespace(system.id)
    why = f"classification {row.id} approved"
    meta = {"classification_id": row.id}
    await put_file(
        db,
        namespace=namespace,
        path=CARD_PATH,
        content=_yaml(card),
        content_type="application/yaml",
        actor=actor,
        reason=why,
        meta=meta,
        trace_id=row.trace_id,
    )
    record = {
        "id": row.id,
        "system_id": system.id,
        "status": "approved",
        "kb_version": row.kb_version,
        "dossier_version": row.dossier_version or {},
        "approved_by": actor,
        "approved_at": at,
        "reason": reason or None,
        "previous_id": row.previous_id,
        "result": row.result,
    }
    await put_file(
        db,
        namespace=namespace,
        path=CLASSIFICATION_PATH,
        content=_yaml(record),
        content_type="application/yaml",
        actor=actor,
        reason=why,
        meta=meta,
        trace_id=row.trace_id,
    )
    system.data = {**(system.data or {}), "card": card}
    system.status = "active"


async def decide(
    db: AsyncSession,
    system: SystemTable,
    classification_id: str,
    payload: DecisionIn,
    actor: str,
) -> SystemClassificationTable:
    """Approve or reject a ``proposed`` run (409 otherwise). Flushed, not committed."""
    row = await get_classification(db, system.id, classification_id)
    if row.status != "proposed":
        raise HTTPException(
            status_code=409, detail=f"Only a proposed classification can be decided ({row.status})."
        )
    reason = (payload.reason or "").strip()
    if payload.decision == "approve":
        await _approve(db, system, row, actor, reason)
    else:
        await move(db, row, "rejected", actor, reason=reason)
    await db.flush()
    return row


# ---- stale on a regulation change ------------------------------------------------------------


def _touches(provision: str, changed: set[str]) -> bool:
    return any(
        provision == c or provision.startswith(c + ".") or c.startswith(provision + ".")
        for c in changed
    )


def changed_provisions(change: dict[str, Any]) -> set[str]:
    """The change's provision and interpretation ids and what they relate to."""
    out: set[str] = set()
    entries = [
        *(change.get("provisions") or []),
        *(change.get("interpretations") or []),
        *(change.get("items") or []),
    ]
    for entry in entries:
        if isinstance(entry, str):
            out.add(entry)
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("id"):
            out.add(str(entry["id"]))
        out.update(str(p) for p in entry.get("relates_to") or [])
    return out


def relied_on(result: dict[str, Any]) -> set[str]:
    """A result's citation ids, its Annex basis node and the core provisions."""
    out = set(CORE_PROVISIONS)
    out.update(
        str(c.get("id") or c.get("provision_id"))
        for c in result.get("citations") or []
        if isinstance(c, dict) and (c.get("id") or c.get("provision_id"))
    )
    if result.get("annex_basis_id"):
        out.add(str(result["annex_basis_id"]))
    return out


async def mark_stale_for_change(
    db: AsyncSession, change: dict[str, Any], actor: str = "regulation-change"
) -> list[str]:
    """Mark every approved classification the change touches ``stale``; the ids marked.

    No LLM. Called when a change is accepted; flushed, not committed by itself."""
    changed = changed_provisions(change)
    if not changed:
        return []
    change_id = str(change.get("id") or "")
    rows = (
        await db.scalars(
            select(SystemClassificationTable).where(SystemClassificationTable.status == "approved")
        )
    ).all()
    marked = []
    for row in rows:
        touched = sorted(p for p in relied_on(row.result or {}) if _touches(p, changed))
        if not touched:
            continue
        await move(
            db,
            row,
            "stale",
            actor,
            reason=f"{change_id} changed {', '.join(touched[:6])}",
            data={"change_id": change_id, "provisions": touched},
        )
        marked.append(row.id)
    if marked:
        logger.info(
            "classifications_stale",
            "Classifications marked stale by a regulation change",
            change_id=change_id,
            item_count=len(marked),
        )
    return marked


# ---- the obligations preview -----------------------------------------------------------------


async def _reg_get(path: str, params: dict[str, Any]) -> Any:
    headers = {}
    secret = settings.reg_memory.secret.get_secret_value()
    if secret:
        headers[REG_SECRET_HEADER] = secret
    clean = {k: v for k, v in params.items() if v is not None}
    try:
        async with httpx.AsyncClient(
            timeout=settings.reg_memory.timeout_seconds, transport=reg_transport
        ) as client:
            response = await client.get(
                f"{settings.reg_memory.url.rstrip('/')}{path}", params=clean, headers=headers
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="reg-memory is unavailable.") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Not found in reg-memory.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"reg-memory answered {response.status_code}.")
    return response.json()


def obligation_query(card: dict[str, Any]) -> dict[str, Any]:
    """Card → reg-memory ``GET /v1/obligations`` parameters (same reading as
    ``card_profile()``): ``high_risk`` → ``high``, Annex basis family and point."""
    raw = str(card.get("risk_class") or "").strip().lower()
    risk = "high" if raw.startswith("high") else raw.removesuffix("_risk")
    basis, point = None, None
    m = _ANNEX_RE.search(str(card.get("annex_basis") or card.get("basis") or ""))
    if m:
        basis = {"iii": "annex_iii", "i": "annex_i"}.get(m.group(1).lower())
        if basis == "annex_iii" and m.group(2):
            point = m.group(2) + (f".{m.group(3).lower()}" if m.group(3) else "")
    claim = next((card[k] for k in _CLAIM_KEYS if k in card), None)
    if isinstance(claim, dict):
        claim = claim.get("claimed")
    features = card.get("features")
    return {
        "role": str(card.get("role") or "").strip().lower() or None,
        "risk_class": risk or None,
        "basis": basis,
        "annex_point": point,
        "features": [str(f) for f in features] if isinstance(features, list) and features else None,
        "exempt_6_3": bool(claim),
    }


async def obligations_preview(
    db: AsyncSession, system: SystemTable, on: date | None = None
) -> ObligationsPreviewOut:
    """The obligations that follow from the system's card, before any audit."""
    card = dict((system.data or {}).get("card") or {})
    in_force = next(
        (r for r in await list_classifications(db, system.id) if r.status in IN_FORCE), None
    )
    out = ObligationsPreviewOut(
        systemId=system.id,
        classificationId=in_force.id if in_force else None,
        classificationStatus=in_force.status if in_force else None,
        kb_version=in_force.kb_version if in_force else None,
    )
    risk = str(card.get("risk_class") or "").strip().lower()
    if risk in ("", "unclassified", "unknown", "none"):
        out.classified = False
        return out
    if risk == "out_of_scope":
        return out
    query = obligation_query(card)
    common = {
        "date": on.isoformat() if on else None,
        "kb_version": out.kb_version,
    }
    if risk == "prohibited":
        out.prohibited = True
        params = {**common, "include_not_applicable": "false"}
    else:
        params = {**query, **common, "include_not_applicable": "true"}
    body = await _reg_get("/v1/obligations", params)
    items = [i for i in body.get("items") or [] if isinstance(i, dict)]
    if out.prohibited:
        items = [i for i in items if str(i.get("id", "")).startswith("OBL.AIA.5.")]
    out.query = {k: v for k, v in params.items() if v is not None}
    out.kb_version = out.kb_version or body.get("kb_version")
    out.items = items
    out.total = len(items)
    return out
