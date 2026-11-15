"""Sealed findings (plan 01 §7.2): append-only verdicts, annotations, status events.

The pipeline's ``seal`` step posts one finding per obligation
(``POST /internal/audits/{id}/findings``). A finding is never edited: the
database rejects UPDATE and DELETE (trigger, migration 0006). Humans add
annotations; a regulation change or a later finding adds a status event.

* **Idempotent on ``hash``:** posting the same hash again returns the stored row.
* **Hash chain:** a finding without ``hash`` gets ``sha256(prev_hash + canonical
  JSON of its sealed fields)``; a missing ``prev_hash`` is the audit's last hash.
* **Supersede:** a new finding for the same (system, obligation) adds a
  ``superseded`` event (``superseded_by`` = the new id) to the earlier ones that
  are still live, so ``current`` = no ``superseded`` event.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    AuditTable,
    FindingAnnotationTable,
    FindingStatusEventTable,
    FindingTable,
    gen_uuid,
)
from schema.findings import (
    AnnotationIn,
    AnnotationOut,
    FindingIn,
    FindingOut,
    StatusEventIn,
    StatusEventOut,
)

#: The fields the hash seals (everything the verdict rests on).
SEALED_FIELDS = (
    "obligation_id",
    "verdict",
    "severity",
    "gap_id",
    "metrics_ref",
    "evidence_refs",
    "citations",
    "kb_version",
    "reasoning",
    "counter_arguments",
    "would_change_if",
    "judges",
    "critic",
)
_KNOWN = {*SEALED_FIELDS, "id", "prev_hash", "hash"}


def finding_hash(sealed: dict[str, Any], prev_hash: str | None) -> str:
    canonical = json.dumps(sealed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash or ''}{canonical}".encode()).hexdigest()


def sealed_of(row: FindingTable) -> dict[str, Any]:
    return {k: getattr(row, k) for k in SEALED_FIELDS}


async def get_finding_or_404(db: AsyncSession, finding_id: str) -> FindingTable:
    row = await db.get(FindingTable, finding_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    return row


async def _last_hash(db: AsyncSession, audit_id: str) -> str | None:
    rows = (
        await db.scalars(
            select(FindingTable)
            .where(FindingTable.audit_id == audit_id)
            .order_by(FindingTable.created_at.desc())
        )
    ).all()
    return rows[0].hash if rows else None


async def _superseded_ids(db: AsyncSession, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    rows = await db.scalars(
        select(FindingStatusEventTable.finding_id).where(
            FindingStatusEventTable.finding_id.in_(ids),
            FindingStatusEventTable.status == "superseded",
        )
    )
    return set(rows.all())


async def seal_finding(
    db: AsyncSession, audit: AuditTable, payload: FindingIn, actor: str
) -> tuple[FindingTable, bool]:
    """Store one sealed finding. Returns ``(row, created)``; a known hash is not stored twice."""
    body = payload.model_dump(mode="json")
    sealed = {k: body.get(k) for k in SEALED_FIELDS}
    if payload.hash is None:
        # No hash given: a repost of the same content in this audit is the same finding.
        same = await db.scalars(
            select(FindingTable).where(
                FindingTable.audit_id == audit.id,
                FindingTable.obligation_id == payload.obligation_id,
            )
        )
        for row in same.all():
            if finding_hash(sealed_of(row), None) == finding_hash(sealed, None):
                return row, False
    prev_hash = payload.prev_hash or await _last_hash(db, audit.id)
    digest = payload.hash or finding_hash(sealed, prev_hash)
    existing = await db.scalar(select(FindingTable).where(FindingTable.hash == digest))
    if existing is not None:
        if existing.audit_id != audit.id:
            raise HTTPException(status_code=409, detail="This hash is sealed in another audit.")
        return existing, False
    if payload.id and await db.get(FindingTable, payload.id) is not None:
        raise HTTPException(status_code=409, detail="A different finding has this id.")
    earlier = list(
        (
            await db.scalars(
                select(FindingTable.id).where(
                    FindingTable.system_id == audit.system_id,
                    FindingTable.obligation_id == payload.obligation_id,
                )
            )
        ).all()
    )
    row = FindingTable(
        id=payload.id or gen_uuid(),
        audit_id=audit.id,
        system_id=audit.system_id,
        **sealed,
        data={k: v for k, v in body.items() if k not in _KNOWN},
        prev_hash=prev_hash,
        hash=digest,
        created_by=actor,
    )
    db.add(row)
    await db.flush()
    done = await _superseded_ids(db, earlier)
    for old in earlier:
        if old not in done:
            db.add(
                FindingStatusEventTable(
                    finding_id=old,
                    status="superseded",
                    superseded_by=row.id,
                    reason=f"A newer finding for {payload.obligation_id} (audit {audit.id}).",
                    data={"audit_id": audit.id},
                    actor=actor,
                )
            )
    await db.flush()
    return row, True


async def add_status_event(
    db: AsyncSession, finding: FindingTable, payload: StatusEventIn, actor: str
) -> FindingStatusEventTable:
    event = FindingStatusEventTable(
        finding_id=finding.id,
        status=payload.status,
        superseded_by=payload.superseded_by,
        reason=payload.reason,
        data=payload.data,
        actor=actor,
    )
    db.add(event)
    await db.flush()
    return event


async def add_annotation(
    db: AsyncSession, finding: FindingTable, payload: AnnotationIn, actor: str
) -> FindingAnnotationTable:
    note = FindingAnnotationTable(
        finding_id=finding.id, kind=payload.kind, body=payload.body, actor=actor
    )
    db.add(note)
    await db.flush()
    return note


async def list_annotations(db: AsyncSession, finding_id: str) -> list[FindingAnnotationTable]:
    return list(
        (
            await db.scalars(
                select(FindingAnnotationTable)
                .where(FindingAnnotationTable.finding_id == finding_id)
                .order_by(FindingAnnotationTable.created_at, FindingAnnotationTable.id)
            )
        ).all()
    )


def derived_status(statuses: list[str]) -> str:
    """``superseded`` wins; otherwise the latest event's status; ``current`` when none."""
    if "superseded" in statuses:
        return "superseded"
    return statuses[-1] if statuses else "current"


async def findings_out(db: AsyncSession, rows: list[FindingTable]) -> list[FindingOut]:
    """Findings with their annotations, status events and the derived status."""
    ids = [r.id for r in rows]
    notes: dict[str, list[FindingAnnotationTable]] = defaultdict(list)
    events: dict[str, list[FindingStatusEventTable]] = defaultdict(list)
    if ids:
        for note in (
            await db.scalars(
                select(FindingAnnotationTable)
                .where(FindingAnnotationTable.finding_id.in_(ids))
                .order_by(FindingAnnotationTable.created_at, FindingAnnotationTable.id)
            )
        ).all():
            notes[note.finding_id].append(note)
        for event in (
            await db.scalars(
                select(FindingStatusEventTable)
                .where(FindingStatusEventTable.finding_id.in_(ids))
                .order_by(FindingStatusEventTable.created_at, FindingStatusEventTable.id)
            )
        ).all():
            events[event.finding_id].append(event)
    out = []
    for row in rows:
        item = FindingOut.model_validate(row)
        item.annotations = [AnnotationOut.model_validate(n) for n in notes[row.id]]
        item.status_events = [StatusEventOut.model_validate(e) for e in events[row.id]]
        item.status = derived_status([e.status for e in events[row.id]])
        item.stale = item.status == "stale"
        out.append(item)
    return out


async def audit_findings(db: AsyncSession, audit_id: str) -> list[FindingTable]:
    return list(
        (
            await db.scalars(
                select(FindingTable)
                .where(FindingTable.audit_id == audit_id)
                .order_by(FindingTable.created_at, FindingTable.obligation_id)
            )
        ).all()
    )


async def system_findings(
    db: AsyncSession, system_id: str, current: bool = False
) -> list[FindingTable]:
    """All of a system's findings, newest first; ``current`` drops superseded ones."""
    rows = list(
        (
            await db.scalars(
                select(FindingTable)
                .where(FindingTable.system_id == system_id)
                .order_by(FindingTable.created_at.desc(), FindingTable.obligation_id)
            )
        ).all()
    )
    if not current:
        return rows
    gone = await _superseded_ids(db, [r.id for r in rows])
    return [r for r in rows if r.id not in gone]
