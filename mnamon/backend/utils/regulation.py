"""The regulation proxy: reg-memory (internal, ``X-Internal-Secret``) seen
through the backend, mapped to the frontend's camelCase types
(``mnamon/frontend/src/features/regulation/lib/types.ts``).

reg-memory owns sources, documents, releases and RegChanges. The backend adds
what the humans decide: accepting a change (= activating its candidate
release in reg-memory) or rejecting it, and per-system judge overrides. Those
live in ``regulation_changes`` (JSONB), next to the payload reg-memory POSTs
to ``/internal/regulation/changes``.

Accepting a change also starts the agents' change judge in the background
(``POST {AGENTS_SERVICE_URL}/changes/{id}/judge`` with ``rerun: true`` and every
system's card + current sealed findings): impact via each system's obligation
map, Iris per affected system, focused re-runs, stale marks, delta reports.
``judge`` is ``pending`` -> ``running`` -> ``done`` (the agents write
``affected``, possibly ``[]`` when no system is affected) or ``failed``.

The demo mirror (``/v1/regulation/demo/mirror``) edits reg-memory's mirrored
guideline page so "Simulate change" -> "Check now" produces a live RegChange.
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

from core.database import RegulationChangeTable, SessionLocal, SystemTable
from core.logging import get_logger
from core.settings import settings
from utils.agents import internal_headers
from utils.findings import findings_out, system_findings

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

#: Test seams: tests swap in an ``httpx.MockTransport`` (reg-memory / agents service).
transport: httpx.AsyncBaseTransport | None = None
agents_transport: httpx.AsyncBaseTransport | None = None

#: The change judge can call Iris once per system and start re-runs: give it time.
JUDGE_TIMEOUT_SECONDS = 600.0
#: The demo mirror's source in reg-memory's catalog.
DEMO_MIRROR_SOURCE = "demo-art6-guideline-mirror"
#: Change judges running in the background (kept referenced until they finish).
_judge_tasks: set[asyncio.Task[Any]] = set()


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
        "impactedObligations": change.get("impacted_obligations") or [],
        # The judge's own flag: "done" with no affected system is a real answer.
        "judge": data.get("judge") or ("done" if data.get("affected") else "pending"),
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
    systems: list[dict[str, Any]] = []
    if status == "accepted":
        systems = await judge_systems(db)
        row.data = {**row.data, "judge": "running", "judgeStartedAt": row.data["decidedAt"]}
    await db.flush()
    logger.info(
        "reg_change_decided", "Regulation change decided", change_id=change_id, decision=status
    )
    if status == "accepted":
        # The task waits until this accept is committed (router or Telegram), so the
        # judge's own write onto the row never races ours.
        start_change_judge(change_id, systems)
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


# ---- the change judge (agents service), started on accept ------------------------------------


def _finding_brief(finding: Any) -> dict[str, Any]:
    out = finding.model_dump(mode="json") if hasattr(finding, "model_dump") else dict(finding)
    keep = (
        "id",
        "audit_id",
        "obligation_id",
        "verdict",
        "severity",
        "gap_id",
        "kb_version",
        "metrics_ref",
        "citations",
        "hash",
        "data",
    )
    return {k: out.get(k) for k in keep if k in out}


async def judge_systems(db: AsyncSession) -> list[dict[str, Any]]:
    """Every system's card and current sealed findings: what the judge maps and compares."""
    systems = list((await db.scalars(select(SystemTable).order_by(SystemTable.id))).all())
    out = []
    for system in systems:
        try:
            findings = await findings_out(db, await system_findings(db, system.id, current=True))
        except Exception as exc:  # the judge still works from the impact index's artifacts
            logger.warning(
                "judge_findings_unavailable",
                "Sealed findings could not be read for the judge",
                system_id=system.id,
                error=type(exc).__name__,
            )
            findings = []
        out.append(
            {
                "system_id": system.id,
                "name": system.name,
                "card": (system.data or {}).get("card") or {},
                "findings": [_finding_brief(f) for f in findings],
            }
        )
    return out


#: The judge task's own sessions (tests point it at their database).
session_factory: Any = SessionLocal
COMMIT_WAIT_SECONDS = 10.0


async def _wait_accepted(change_id: str) -> None:
    """Until the accept is visible in a fresh session (bounded; best effort)."""
    waited = 0.0
    while waited < COMMIT_WAIT_SECONDS:
        try:
            async with session_factory() as db:
                row = await db.get(RegulationChangeTable, change_id)
                if row is not None and row.status == "accepted":
                    return
        except Exception:
            return
        await asyncio.sleep(0.25)
        waited += 0.25


async def mark_judge(change_id: str, state: str, **extra: Any) -> None:
    """Set ``data.judge`` on the change row in its own session (best effort)."""
    try:
        async with session_factory() as db:
            row = await _row(db, change_id)
            if (row.data or {}).get("judge") == "done" and state != "done":
                return  # the agents already wrote their result
            row.data = {**(row.data or {}), "judge": state, **extra}
            await db.commit()
    except Exception as exc:
        logger.warning(
            "reg_change_judge_flag_failed",
            "Could not record the judge state",
            change_id=change_id,
            error=type(exc).__name__,
        )


async def run_change_judge(change_id: str, systems: list[dict[str, Any]]) -> str:
    """``POST /changes/{id}/judge`` (rerun) on the agents service; ``done`` / ``failed``."""
    await _wait_accepted(change_id)
    url = f"{settings.upstream.agents_service_url.rstrip('/')}/changes/{change_id}/judge"
    body = {"rerun": True, "systems": systems}
    try:
        async with httpx.AsyncClient(
            timeout=JUDGE_TIMEOUT_SECONDS, transport=agents_transport
        ) as client:
            response = await client.post(url, json=body, headers=internal_headers())
        ok = response.status_code < 300
        code = response.status_code
    except httpx.HTTPError as exc:
        ok, code = False, type(exc).__name__
    logger.info(
        "reg_change_judged",
        "Change judge finished" if ok else "Change judge failed",
        change_id=change_id,
        outcome=code,
    )
    if not ok:
        await mark_judge(change_id, "failed", judgeError=str(code))
        return "failed"
    return "done"


def start_change_judge(change_id: str, systems: list[dict[str, Any]]) -> asyncio.Task[str]:
    """Run the judge in the background (it starts once the accept is committed)."""
    task = asyncio.create_task(run_change_judge(change_id, systems))
    _judge_tasks.add(task)
    task.add_done_callback(_judge_tasks.discard)
    return task


# ---- the demo mirror ("Simulate change") ------------------------------------------------------


async def edit_demo_mirror(edit: dict[str, Any], *, check: bool) -> dict[str, Any]:
    """Edit reg-memory's mirrored guideline page; with ``check`` run "Check now" on the
    mirror alone (no EU download, no Firecrawl credit) and return the check record."""
    mirror = await reg_call("PUT", "/v1/demo/mirror", json=edit)
    out: dict[str, Any] = {
        "url": mirror.get("url"),
        "bytes": mirror.get("bytes"),
        "html": mirror.get("html"),
    }
    if check:
        out["check"] = await reg_call(
            "POST",
            "/v1/watch/check-now",
            json={"source_ids": [DEMO_MIRROR_SOURCE], "wait": True, "discovery": False},
            timeout=settings.reg_memory.check_timeout_seconds,
        )
    return out


async def demo_mirror() -> dict[str, Any]:
    return await reg_call("GET", "/v1/demo/mirror")
