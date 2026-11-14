"""The regulation proxy: reg-memory (internal, ``X-Internal-Secret``) seen
through the backend, mapped to the frontend's camelCase types
(``mnamon/frontend/src/features/regulation/lib/types.ts``).

reg-memory owns sources, documents, releases and RegChanges. The backend adds
what the humans decide: accepting a change (= activating its candidate
release in reg-memory) or rejecting it, and per-system judge overrides. Those
live in ``regulation_changes`` (JSONB), next to the payload reg-memory POSTs
to ``/internal/regulation/changes``.

Not in reg-memory yet: the per-system change judge. ``affected`` is ``[]``
until a judge (or a human override) writes it; ``judge`` says ``pending``.
"""

from __future__ import annotations

import asyncio
import difflib
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import RegulationChangeTable
from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)

SECRET_HEADER = "X-Internal-Secret"  # noqa: S105 - a header name

#: reg-memory change types -> the UI's ChangeType, and how severe each is.
_CHANGE_TYPE = {
    "editorial": "editorial",
    "new_interpretation": "clarification",
    "date": "scope_change",
    "scope": "scope_change",
    "substantive": "new_obligation",
}
_SEVERITY = ["editorial", "clarification", "scope_change", "new_obligation", "repeal"]
JUDGE_DECISIONS = ("no_impact", "reinterpret_existing_evidence", "rerun_tests", "new_tests_needed")

#: A test seam: tests swap in an ``httpx.MockTransport``.
transport: httpx.AsyncBaseTransport | None = None


class RegMemoryUnavailable(HTTPException):
    def __init__(self, detail: str = "reg-memory is unavailable.") -> None:
        super().__init__(status_code=502, detail=detail)


def _client(timeout: float | None = None) -> httpx.AsyncClient:
    headers = {}
    secret = settings.reg_memory.secret.get_secret_value()
    if secret:
        headers[SECRET_HEADER] = secret
    return httpx.AsyncClient(
        base_url=settings.reg_memory.url.rstrip("/"),
        headers=headers,
        timeout=timeout or settings.reg_memory.timeout_seconds,
        transport=transport,
    )


async def reg_call(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    timeout: float | None = None,
) -> Any:
    """One reg-memory call. 404 stays 404; any other failure is a 502."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        async with _client(timeout) as client:
            response = await client.request(method, path, params=clean, json=json)
    except httpx.HTTPError as exc:
        logger.warning(
            "reg_memory_unreachable", "reg-memory call failed", path=path, error=type(exc).__name__
        )
        raise RegMemoryUnavailable() from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Not found in reg-memory.")
    if response.status_code >= 400:
        logger.warning(
            "reg_memory_error", "reg-memory answered an error", path=path, code=response.status_code
        )
        detail = _json_or_text(response)
        if 400 <= response.status_code < 500:
            raise HTTPException(status_code=response.status_code, detail=detail)
        raise RegMemoryUnavailable(f"reg-memory answered {response.status_code}.")
    return _json_or_text(response)


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


# ---- sources and documents ---------------------------------------------------


def _doc_versions(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fetch log collapsed to one entry per stored version (+ failures)."""
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in log:
        status = entry.get("status") or "same"
        version = int(entry.get("version") or 0)
        if status != "failed" and version in seen:
            continue
        if status != "failed":
            seen.add(version)
        out.append(
            {
                "version": version,
                "fetchedAt": entry.get("fetched_at") or "",
                "sha256": entry.get("sha256") or "",
                "status": status if status in ("new", "changed", "same", "failed") else "same",
                "bytes": int(entry.get("bytes") or 0),
            }
        )
    return out


def map_source(source: dict[str, Any], versions_log: list[dict[str, Any]] | None) -> dict[str, Any]:
    latest = source.get("latest") or {}
    versions = _doc_versions(versions_log or [])
    if not versions and latest:
        versions = _doc_versions([latest])
    return {
        "id": source["id"],
        "title": source.get("title") or source["id"],
        "kind": source.get("kind") or "other",
        "binding": source.get("binding", False),
        "status": source.get("status") or "final",
        "publisher": source.get("publisher") or "",
        "url": source.get("url")
        or (
            f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{source['celex']}"
            if source.get("celex")
            else None
        ),
        "tags": source.get("tags") or [],
        "documents": int(source.get("documents") or 0),
        "versions": versions,
    }


async def list_sources() -> list[dict[str, Any]]:
    """Every catalog source with its main document's versions."""
    sources = (await reg_call("GET", "/v1/sources")).get("items", [])

    async def versions(source_id: str) -> list[dict[str, Any]] | None:
        try:
            return (await reg_call("GET", f"/v1/documents/{source_id}")).get("versions", [])
        except HTTPException:
            return None  # never fetched yet

    logs = await asyncio.gather(*(versions(s["id"]) for s in sources))
    return [map_source(s, log) for s, log in zip(sources, logs, strict=True)]


async def document_text(doc_id: str, version: int | None) -> dict[str, Any]:
    body = await reg_call("GET", f"/v1/documents/{doc_id}/text", params={"version": version})
    return {"docId": body["doc_id"], "version": body["version"], "text": body.get("text") or ""}


async def document_diff(doc_id: str, from_version: int, to_version: int) -> dict[str, Any]:
    """A unified diff of two versions' extracted texts."""
    old, new = await asyncio.gather(
        document_text(doc_id, from_version), document_text(doc_id, to_version)
    )
    unified = "".join(
        difflib.unified_diff(
            old["text"].splitlines(keepends=True),
            new["text"].splitlines(keepends=True),
            fromfile=f"{doc_id} v{from_version}",
            tofile=f"{doc_id} v{to_version}",
            n=3,
        )
    )
    return {"docId": doc_id, "from": from_version, "to": to_version, "unified": unified}


# ---- changes -----------------------------------------------------------------


def _ui_change_type(items: list[dict[str, Any]], types: dict[str, Any] | None) -> str:
    found = {"repeal" for e in items if e.get("change") == "removed"}
    found |= {_CHANGE_TYPE.get(str(e.get("change_type")), "clarification") for e in items}
    found |= {_CHANGE_TYPE.get(str(t), "clarification") for t in (types or {})}
    return max(found, key=_SEVERITY.index) if found else "clarification"


def _source_version(release: dict[str, Any] | None, source_id: str) -> int:
    inputs = (release or {}).get("inputs") or {}
    return int((inputs.get(source_id) or {}).get("version") or 0)


def _ui_status(
    raw: str | None, stored: RegulationChangeTable | None, release: dict[str, Any] | None
) -> str:
    """Our decision wins; otherwise a candidate that was activated (in reg-memory
    directly) counts as accepted."""
    if stored is not None and stored.status in ("accepted", "rejected"):
        return stored.status
    if raw in ("accepted", "rejected"):
        return raw
    if (release or {}).get("status") in ("active", "superseded"):
        return "accepted"
    return "proposed"


def map_change(
    change: dict[str, Any],
    *,
    releases: dict[str, dict[str, Any]],
    stored: RegulationChangeTable | None,
) -> dict[str, Any]:
    """reg-memory's RegChange (detail, or the payload it POSTs) -> the UI's RegChange."""
    items = [
        *(change.get("provisions") or []),
        *(change.get("interpretations") or []),
        *(change.get("items") or []),
    ]
    source_id = next(
        (
            str(e.get("source_id") or e.get("source_doc"))
            for e in items
            if e.get("source_id") or e.get("source_doc")
        ),
        "ai-act-consolidated",
    )
    to_kb = change.get("to_kb_version")
    title = next((e.get("title") for e in items if e.get("title")), None)
    data = (stored.data if stored is not None else None) or {}
    impacted = change.get("impacted_requirements")
    return {
        "id": change["id"],
        "sourceId": source_id,
        "title": title or change.get("summary") or change["id"],
        "detectedAt": change.get("created_at") or "",
        "changeType": _ui_change_type(items, change.get("change_types")),
        "provisions": [str(e["id"]) for e in items if e.get("id")],
        "fromVersion": _source_version(
            releases.get(change.get("from_kb_version") or ""), source_id
        ),
        "toVersion": _source_version(releases.get(to_kb or ""), source_id),
        "candidateKbVersion": to_kb or "",
        "status": _ui_status(change.get("status"), stored, releases.get(to_kb or "")),
        "summary": change.get("summary") or "",
        "affected": data.get("affected") or [],
        "traceId": data.get("traceId"),
        # Extras (not in the UI type yet): what reg-memory's impact index found.
        "impactedRequirements": impacted if isinstance(impacted, list) else [],
        "judge": "done" if data.get("affected") else "pending",
        "decidedBy": data.get("decidedBy"),
    }


async def _releases() -> dict[str, dict[str, Any]]:
    try:
        body = await reg_call("GET", "/v1/releases")
    except HTTPException:
        return {}
    return {r["kb_version"]: r for r in body.get("items", [])}


async def _stored(db: AsyncSession) -> dict[str, RegulationChangeTable]:
    rows = (await db.scalars(select(RegulationChangeTable))).all()
    return {r.id: r for r in rows}


async def list_changes(db: AsyncSession) -> list[dict[str, Any]]:
    """reg-memory's RegChanges (with detail) and any stored-only ones, newest first.
    reg-memory down: the stored payloads alone."""
    stored = await _stored(db)
    try:
        summaries = (await reg_call("GET", "/v1/changes")).get("items", [])
        details = await asyncio.gather(
            *(reg_call("GET", f"/v1/changes/{c['id']}") for c in summaries)
        )
    except HTTPException as exc:
        if exc.status_code != 502 or not stored:
            raise
        details = []
    releases = await _releases()
    seen = {d["id"] for d in details}
    extra = [r.data.get("payload") for r in stored.values() if r.id not in seen]
    out = [
        map_change(d, releases=releases, stored=stored.get(d["id"]))
        for d in [*details, *(p for p in extra if isinstance(p, dict) and p.get("id"))]
    ]
    return sorted(out, key=lambda c: c["detectedAt"], reverse=True)


async def get_change(db: AsyncSession, change_id: str) -> dict[str, Any]:
    stored = await db.get(RegulationChangeTable, change_id)
    try:
        detail = await reg_call("GET", f"/v1/changes/{change_id}")
    except HTTPException as exc:
        payload = (stored.data or {}).get("payload") if stored is not None else None
        if not payload:
            raise
        logger.info(
            "reg_change_from_store", "Change served from the backend store", status=exc.status_code
        )
        detail = payload
    releases = await _releases()
    return map_change(detail, releases=releases, stored=stored)


async def _row(db: AsyncSession, change_id: str) -> RegulationChangeTable:
    row = await db.get(RegulationChangeTable, change_id)
    if row is None:
        row = RegulationChangeTable(id=change_id, status="proposed", data={})
        db.add(row)
        await db.flush()
    return row


async def store_notified_change(db: AsyncSession, payload: dict[str, Any]) -> RegulationChangeTable:
    """``POST /internal/regulation/changes``: keep reg-memory's payload (idempotent)."""
    row = await _row(db, str(payload["id"]))
    row.data = {**(row.data or {}), "payload": payload}
    await db.flush()
    return row


async def store_judgement(
    db: AsyncSession, change_id: str, affected: list[dict[str, Any]], decided_by: str
) -> RegulationChangeTable:
    """The agents' change judge writes its per-system decisions (``judge`` becomes ``done``).

    A human override (``humanDecision``) already on a system survives a re-judge.
    """
    row = await _row(db, change_id)
    previous = {a.get("systemId"): a for a in (row.data or {}).get("affected") or []}
    merged = []
    for entry in affected:
        old = previous.get(entry.get("systemId")) or {}
        keep = {k: old[k] for k in ("humanDecision", "decidedBy") if k in old and old.get(k)}
        merged.append({**entry, "judgedBy": decided_by, **keep})
    row.data = {
        **(row.data or {}),
        "affected": merged,
        "judge": "done",
        "judgedBy": decided_by,
        "judgedAt": datetime.now(UTC).isoformat(),
    }
    await db.flush()
    return row


async def decide_change(
    db: AsyncSession, change_id: str, status: str, actor: str, reason: str | None = None
) -> dict[str, Any]:
    """Accept (activate the candidate release in reg-memory) or reject a change.
    A change already decided answers 409."""
    current = await get_change(db, change_id)
    if current["status"] != "proposed":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Change already {current['status']} by {current.get('decidedBy') or 'someone'}."
            ),
        )
    if status == "accepted" and current["candidateKbVersion"]:
        await reg_call(
            "POST", f"/v1/releases/{current['candidateKbVersion']}/activate", json={"by": actor}
        )
    row = await _row(db, change_id)
    row.status = status
    row.data = {
        **(row.data or {}),
        "decidedBy": actor,
        "decidedAt": datetime.now(UTC).isoformat(),
        "reason": reason,
    }
    await db.flush()
    logger.info(
        "reg_change_decided", "Regulation change decided", change_id=change_id, decision=status
    )
    return await get_change(db, change_id)


async def override_system(
    db: AsyncSession, change_id: str, system_id: str, system_name: str, decision: str, actor: str
) -> dict[str, Any]:
    """A human sets the judge decision for one system."""
    await get_change(db, change_id)  # 404 when unknown
    row = await _row(db, change_id)
    affected = [dict(a) for a in (row.data or {}).get("affected") or []]
    entry = next((a for a in affected if a.get("systemId") == system_id), None)
    if entry is None:
        entry = {
            "systemId": system_id,
            "systemName": system_name,
            "path": [],
            "findings": [],
            "decision": decision,
            "confidence": 0.0,
            "reasoning": "No judge run yet; set by a human.",
            "rerunAuditId": None,
        }
        affected.append(entry)
    entry["humanDecision"] = decision
    entry["decidedBy"] = actor
    row.data = {**(row.data or {}), "affected": affected}
    await db.flush()
    return await get_change(db, change_id)
