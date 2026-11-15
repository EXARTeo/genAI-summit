"""Findings register: the system's state per obligation across audits.

One row per ``(system, obligation)``. A finished audit (status ``done``) folds
its sealed findings into the register (:func:`apply_audit`, idempotent per
audit: a row that already has an event of that audit is skipped). Humans close
an item with a reason and can reopen it.

Rules for one finding (``is_gap`` = verdict ``gap`` / ``partial`` or a
documentation gap; "needs a human" = ``inconclusive``):

============  ===================================  ==============================
row now       finding                              -> state (event, register status)
============  ===================================  ==============================
none          gap / inconclusive                   open (opened, new)
none          pass / n.a. / not testable           monitoring (first_seen, new)
open          gap / inconclusive                   open (still_open | verdict_changed, still_open)
open          pass                                 resolved (resolved, resolved)
open          not testable / n.a. (no gap)         open (verdict_changed, still_open)
resolved/mon  gap / inconclusive                   open (regressed if it was ever open, else opened)
resolved/mon  anything else                        unchanged (checked, unchanged)
closed        pass                                 resolved (resolved, resolved)
closed        worse than the verdict it was        open (reopened, regressed)
              closed at
closed        same or better                       closed (still_open, accepted_risk)
============  ===================================  ==============================
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AuditTable, FindingRegisterTable, FindingTable
from schema.register import (
    RebuildOut,
    RegisterItemDetail,
    RegisterOut,
    RegisterSummary,
)

GAP_VERDICTS = {"gap", "partial"}
#: How bad a verdict is (a closed item reopens only on a worse one).
BADNESS = {
    "pass": 0,
    "not_applicable": 0,
    "not_assessable_by_testing": 0,
    "inconclusive": 1,
    "partial": 2,
    "gap": 3,
}
#: Event kind -> what the audit meant for the item (``register_status``).
STATUS_OF_KIND = {
    "opened": "new",
    "first_seen": "new",
    "verdict_changed": "still_open",
    "resolved": "resolved",
    "regressed": "regressed",
    "reopened": "regressed",
    "checked": "unchanged",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(at: datetime) -> str:
    return at.replace(tzinfo=UTC).isoformat()


def is_gap(verdict: str, gap_id: str | None = None) -> bool:
    return verdict in GAP_VERDICTS or bool(gap_id)


def badness(verdict: str, gap_id: str | None = None) -> int:
    base = BADNESS.get(verdict, 1)
    return max(base, 2) if gap_id and verdict not in GAP_VERDICTS else base


def event_status(event: dict[str, Any], state_after: str | None = None) -> str | None:
    """The register status an audit event stands for."""
    kind = event.get("kind")
    if kind == "still_open":
        return "accepted_risk" if (event.get("to") or state_after) == "closed" else "still_open"
    return STATUS_OF_KIND.get(str(kind))


def transition(
    state: str | None,
    verdict: str,
    gap_id: str | None,
    *,
    previous_verdict: str | None = None,
    closed_verdict: str | None = None,
    closed_gap_id: str | None = None,
    ever_open: bool = False,
) -> tuple[str, str]:
    """``(new_state, event_kind)`` for one sealed finding against the row's state."""
    gap = is_gap(verdict, gap_id)
    needs_human = verdict == "inconclusive"
    if state is None:
        return ("open", "opened") if gap or needs_human else ("monitoring", "first_seen")
    if state == "open":
        if verdict == "pass":
            return "resolved", "resolved"
        return "open", "still_open" if verdict == previous_verdict else "verdict_changed"
    if state == "closed":
        if verdict == "pass":
            return "resolved", "resolved"
        reference = closed_verdict or previous_verdict or verdict
        if badness(verdict, gap_id) > badness(reference, closed_gap_id):
            return "open", "reopened"
        return "closed", "still_open"
    # resolved | monitoring
    if gap or needs_human:
        return "open", "regressed" if ever_open else "opened"
    return state, "checked"


def _ever_open(row: FindingRegisterTable) -> bool:
    return any(e.get("to") == "open" for e in row.history or [])


def _seen_in(row: FindingRegisterTable, audit_id: str) -> bool:
    return any(e.get("audit_id") == audit_id for e in row.history or [])


def _display(finding: FindingTable) -> dict[str, Any]:
    data = finding.data or {}
    return {
        "article": (str(data["article"])[:300] if data.get("article") else None),
        "title": (str(data["title"]) if data.get("title") else None),
    }


def fold_finding(
    row: FindingRegisterTable | None,
    finding: FindingTable,
    audit_id: str,
    actor: str,
) -> tuple[FindingRegisterTable, dict[str, Any]]:
    """Fold one sealed finding into its register row (new row when ``row`` is None)."""
    at = finding.created_at or _now()
    display = _display(finding)
    if row is None:
        row = FindingRegisterTable(
            system_id=finding.system_id,
            obligation_id=finding.obligation_id,
            state="monitoring",
            verdict=finding.verdict,
            first_seen_audit_id=audit_id,
            last_seen_audit_id=audit_id,
            history=[],
            data={},
            created_at=at,
        )
        state_before = None
        previous = None
    else:
        state_before = row.state
        previous = row.verdict
    data = dict(row.data or {})
    new_state, kind = transition(
        state_before,
        finding.verdict,
        finding.gap_id,
        previous_verdict=previous,
        closed_verdict=data.get("closed_verdict"),
        closed_gap_id=data.get("closed_gap_id"),
        ever_open=_ever_open(row) if state_before else False,
    )
    event = {
        "at": _iso(at),
        "audit_id": audit_id,
        "finding_id": finding.id,
        "actor": actor,
        "kind": kind,
        "from": state_before,
        "to": new_state,
        "verdict": finding.verdict,
        "previous_verdict": previous,
        "note": _note(kind, previous, finding.verdict),
    }
    if new_state == "open" and state_before != "open":
        row.opened_at = at
    if new_state == "resolved" and state_before != "resolved":
        row.closed_by = f"audit:{audit_id}"
        row.closed_at = at
        row.close_reason = f"Audit {audit_id} found it passing."
    if new_state == "open" and state_before in {"closed", "resolved"}:
        row.closed_by = row.closed_at = row.close_reason = None
        data.pop("closed_verdict", None)
        data.pop("closed_gap_id", None)
    row.state = new_state
    row.verdict = finding.verdict
    row.severity = finding.severity
    row.gap_id = finding.gap_id
    row.article = display["article"] or row.article
    row.title = display["title"] or row.title
    row.last_seen_audit_id = audit_id
    row.last_finding_id = finding.id
    data["last_status"] = event_status(event)
    data["last_reasoning"] = (finding.reasoning or "")[:600] or None
    data["last_evidence"] = [
        str(r.get("path")) for r in (finding.evidence_refs or [])[:5] if isinstance(r, dict)
    ]
    row.data = data
    row.history = [*(row.history or []), event]
    row.updated_at = _now()
    return row, event


def _note(kind: str, previous: str | None, verdict: str) -> str | None:
    if kind in {"verdict_changed", "reopened", "regressed"} and previous:
        return f"{previous} -> {verdict}"
    if kind == "still_open" and previous and previous != verdict:
        return f"{previous} -> {verdict}"
    return None


def latest_per_obligation(findings: list[FindingTable]) -> list[FindingTable]:
    """One finding per obligation: the latest sealed in the audit."""
    latest: dict[str, FindingTable] = {}
    for f in sorted(findings, key=lambda f: (f.created_at or _now(), f.id)):
        latest[f.obligation_id] = f
    return list(latest.values())


async def _rows(db: AsyncSession, system_id: str) -> dict[str, FindingRegisterTable]:
    rows = await db.scalars(
        select(FindingRegisterTable).where(FindingRegisterTable.system_id == system_id)
    )
    return {r.obligation_id: r for r in rows.all()}


async def apply_audit(db: AsyncSession, audit: AuditTable, actor: str | None = None) -> int:
    """Fold a finished audit's sealed findings into the register. Returns rows touched."""
    findings = list(
        (await db.scalars(select(FindingTable).where(FindingTable.audit_id == audit.id))).all()
    )
    if not findings:
        return 0
    rows = await _rows(db, audit.system_id)
    touched = 0
    for finding in latest_per_obligation(findings):
        row = rows.get(finding.obligation_id)
        if row is not None and _seen_in(row, audit.id):
            continue
        row, _event = fold_finding(row, finding, audit.id, actor or f"audit:{audit.id}")
        if finding.obligation_id not in rows:
            db.add(row)
            rows[finding.obligation_id] = row
        touched += 1
    await db.flush()
    return touched


async def on_audit_status(db: AsyncSession, audit: AuditTable, previous_status: str) -> int:
    """Hook for the PATCH routes: a move to ``done`` folds the audit into the register."""
    if audit.status != "done" or previous_status == "done":
        return 0
    return await apply_audit(db, audit)


async def rebuild(db: AsyncSession, *, reset: bool, system_id: str | None = None) -> RebuildOut:
    """Fold every finished audit, oldest first. ``reset`` drops the register first
    (human closures are lost); without it, audits already folded are skipped."""
    if reset:
        query = delete(FindingRegisterTable)
        if system_id:
            query = query.where(FindingRegisterTable.system_id == system_id)
        await db.execute(query)
        await db.flush()
    audits_q = (
        select(AuditTable)
        .where(AuditTable.status == "done")
        .order_by(AuditTable.created_at, AuditTable.id)
    )
    if system_id:
        audits_q = audits_q.where(AuditTable.system_id == system_id)
    applied = []
    for audit in (await db.scalars(audits_q)).all():
        if await apply_audit(db, audit):
            applied.append(audit.id)
    count_q = select(FindingRegisterTable)
    if system_id:
        count_q = count_q.where(FindingRegisterTable.system_id == system_id)
    items = len((await db.scalars(count_q)).all())
    return RebuildOut(reset=reset, audits_applied=applied, items=items)


async def get_item_or_404(
    db: AsyncSession, system_id: str, obligation_id: str
) -> FindingRegisterTable:
    row = await db.scalar(
        select(FindingRegisterTable).where(
            FindingRegisterTable.system_id == system_id,
            FindingRegisterTable.obligation_id == obligation_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Register item not found.")
    return row


def close_item(row: FindingRegisterTable, reason: str, actor: str) -> None:
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required to close an item.")
    if row.state == "closed":
        raise HTTPException(status_code=409, detail="The item is already closed.")
    at = _now()
    event = {
        "at": _iso(at),
        "audit_id": None,
        "actor": actor,
        "kind": "closed",
        "from": row.state,
        "to": "closed",
        "verdict": row.verdict,
        "note": reason,
    }
    row.state = "closed"
    row.closed_by = actor
    row.close_reason = reason
    row.closed_at = at
    row.data = {**(row.data or {}), "closed_verdict": row.verdict, "closed_gap_id": row.gap_id}
    row.history = [*(row.history or []), event]
    row.updated_at = at


def reopen_item(row: FindingRegisterTable, reason: str | None, actor: str) -> None:
    if row.state == "open":
        raise HTTPException(status_code=409, detail="The item is already open.")
    at = _now()
    event = {
        "at": _iso(at),
        "audit_id": None,
        "actor": actor,
        "kind": "reopened",
        "from": row.state,
        "to": "open",
        "verdict": row.verdict,
        "note": (reason or "").strip() or None,
    }
    data = {**(row.data or {})}
    data.pop("closed_verdict", None)
    data.pop("closed_gap_id", None)
    row.state = "open"
    row.opened_at = at
    row.closed_by = row.closed_at = row.close_reason = None
    row.data = data
    row.history = [*(row.history or []), event]
    row.updated_at = at


def item_out(row: FindingRegisterTable) -> RegisterItemDetail:
    item = RegisterItemDetail.model_validate(row)
    data = row.data or {}
    item.last_status = data.get("last_status")
    item.last_reasoning = data.get("last_reasoning")
    item.last_evidence = list(data.get("last_evidence") or [])
    item.history = list(row.history or [])
    return item


def summary_of(rows: list[FindingRegisterTable]) -> RegisterSummary:
    states = Counter(r.state for r in rows)
    verdicts = Counter(r.verdict for r in rows)
    return RegisterSummary(
        total=len(rows),
        by_state=dict(states),
        by_verdict=dict(verdicts),
        open_gaps=sum(1 for r in rows if r.state == "open" and r.verdict != "inconclusive"),
        needs_review=sum(1 for r in rows if r.state == "open" and r.verdict == "inconclusive"),
        accepted_risks=states.get("closed", 0),
        resolved=states.get("resolved", 0),
        monitoring=states.get("monitoring", 0),
    )


_STATE_ORDER = {"open": 0, "closed": 1, "resolved": 2, "monitoring": 3}


async def register_out(db: AsyncSession, system_id: str) -> RegisterOut:
    rows = sorted(
        (await _rows(db, system_id)).values(),
        key=lambda r: (
            _STATE_ORDER.get(r.state, 9),
            -badness(r.verdict, r.gap_id),
            r.obligation_id,
        ),
    )
    return RegisterOut(
        system_id=system_id, summary=summary_of(rows), items=[item_out(r) for r in rows]
    )
