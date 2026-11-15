"""The copilot's history tools: kb releases, diffs, regulation changes, findings, gates, re-runs.

Read-only except ``attach_upload_to_audit_draft`` (approval-gated in
``harness/tools/builtins.py``). Every result is a summary (ids, verdicts,
counts, short excerpts), never a raw dump of a body; every failure is a string.

Some routes land during the build (plan 01 §13): reg-memory's
``/v1/releases/{a}/diff/{b}`` and ``/v1/obligations``, the backend's
``/v1/audits/{id}/findings`` and ``/v1/systems/{id}/findings``. Each tool
falls back to what exists today (the changes on the release chain, the
requirements catalogue, the audit's ``finding`` artifacts) and says which
source it used, so the copilot answers either way.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from core.logging import get_logger
from harness.tools.workspace_api import rerun
from harness.tools.workspace_api.client import WorkspaceAPI, WorkspaceAPIError
from harness.tools.workspace_api.common import (
    NO_AUDIT,
    NO_SYSTEM,
    WorkspaceScope,
    clip,
    dump,
    pick_audit,
    pick_system,
)

logger = get_logger(__name__)

LIST_KB_RELEASES = "list_kb_releases"
DIFF_KB = "diff_kb"
LIST_REG_CHANGES = "list_reg_changes"
GET_REG_CHANGE = "get_reg_change"
AUDIT_NEEDS_RERUN = "audit_needs_rerun"
LIST_FINDINGS = "list_findings"
GET_GATE_DECISIONS = "get_gate_decisions"
LIST_OBLIGATIONS = "list_obligations"
ATTACH_UPLOAD_TO_AUDIT_DRAFT = "attach_upload_to_audit_draft"

HISTORY_TOOL_NAMES: tuple[str, ...] = (
    LIST_KB_RELEASES,
    DIFF_KB,
    LIST_REG_CHANGES,
    GET_REG_CHANGE,
    AUDIT_NEEDS_RERUN,
    LIST_FINDINGS,
    GET_GATE_DECISIONS,
    LIST_OBLIGATIONS,
    ATTACH_UPLOAD_TO_AUDIT_DRAFT,
)

#: Where an uploaded dataset lands in the system folder (plan 01 §10).
UPLOAD_FOLDER = "datasets/uploaded"
#: Status codes that mean "this route is not deployed yet" (fall back, don't fail).
_MISSING = frozenset({404, 405, 501})
#: The most rows a list result carries.
MAX_ROWS = 40

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_ANNEX_RE = re.compile(r"Annex\s+([IVX]+)\s*(\d+)?\s*(?:\(([a-z])\))?", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
class _NoArgs(BaseModel):
    pass


class _DiffArgs(BaseModel):
    from_version: str = Field(description="Older kb_version, e.g. an audit's pinned one.")
    to_version: str | None = Field(None, description="Newer kb_version. Default: the active one.")
    provisions: list[str] | None = Field(
        None, description="Only these provision ids (and their children), e.g. ['AIA.10.2']."
    )


class _ChangeArgs(BaseModel):
    change_id: str = Field(description="A regulation change id, e.g. RC-2026.11.15-1.")


class _ChangesArgs(BaseModel):
    status: Literal["proposed", "accepted", "rejected"] | None = Field(
        None, description="Only changes in this status."
    )


class _AuditArgs(BaseModel):
    audit_id: str | None = Field(
        None, description="e.g. SYS-001-20261115-0930. Defaults to this conversation's audit."
    )


class _FindingsArgs(BaseModel):
    audit_id: str | None = Field(None, description="One audit's findings.")
    system_id: str | None = Field(
        None, description="A system's current findings (its latest verdict per obligation)."
    )


class _ObligationArgs(BaseModel):
    system_id: str | None = Field(None, description="e.g. SYS-001. Defaults to the scope.")
    audit_id: str | None = Field(None, description="Read this audit's pinned obligation map.")


class _AttachArgs(BaseModel):
    attachment_id: str = Field(description="The upload's attachment id from the chat message.")
    system_id: str | None = Field(None, description="e.g. SYS-001. Defaults to the scope.")
    file_name: str | None = Field(
        None, description="File name to store it under, e.g. applicants.csv."
    )


# ---------------------------------------------------------------------------
# Shapers (pure)
# ---------------------------------------------------------------------------
def _release_row(item: dict[str, Any]) -> dict[str, Any]:
    counts = item.get("counts") or {}
    return {
        k: v
        for k, v in {
            "kb_version": item.get("kb_version"),
            "status": item.get("status"),
            "parent": item.get("parent"),
            "created_at": item.get("created_at"),
            "provisions": counts.get("provisions"),
            "obligations": counts.get("obligations"),
            "activated_by": item.get("activated_by"),
        }.items()
        if v not in (None, "")
    }


def _tally(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        out[value] = out.get(value, 0) + 1
    return out


def _filter_provisions(rows: list[dict[str, Any]], wanted: list[str] | None) -> list[dict]:
    if not wanted:
        return rows
    return [r for r in rows if any(rerun.touches(str(r.get("id")), w) for w in wanted)]


def _judges(judges: Any) -> dict[str, Any] | None:
    """``{judge: verdict}`` from a sealed finding's judges block."""
    if not isinstance(judges, dict):
        return None
    out = {}
    for name, value in judges.items():
        verdict = value.get("verdict") if isinstance(value, dict) else value
        if isinstance(verdict, str | bool | int | float):
            out[name] = verdict
    return out or None


def _finding_row(raw: dict[str, Any]) -> dict[str, Any]:
    """One finding (a sealed findings-table row or a ``finding`` artifact) as a short summary."""
    nested = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    # A sealed row carries the verdict at the top and extras (title, ...) in data;
    # an artifact carries everything in data.
    data = {**nested, **raw} if "verdict" in raw else {**raw, **nested}
    evidence = []
    for e in (data.get("evidence") or data.get("evidence_refs") or [])[:3]:
        if isinstance(e, dict):
            keys = ("test_id", "metric", "value", "ci95", "threshold", "threshold_source")
            keys += ("path", "sha256", "mlflow_run_id")
            evidence.append({k: e.get(k) for k in keys if e.get(k) not in (None, "", [])})
    counters = data.get("counter_evidence") or data.get("counter_arguments") or []
    if isinstance(counters, str):
        counters = [counters]
    citations = [
        c.get("provision_id") if isinstance(c, dict) else c
        for c in (data.get("citations") or [])[:6]
    ]
    row = {
        "id": data.get("gap_id") or nested.get("id") or raw.get("name") or raw.get("id"),
        "obligation": data.get("obligation_id") or data.get("requirement"),
        "title": data.get("title"),
        "verdict": data.get("verdict"),
        "severity": data.get("severity"),
        "confidence": data.get("confidence"),
        "status": raw.get("status"),
        "sealed": raw.get("sealed"),
        "stale": raw.get("stale") or None,
        "audit_id": raw.get("audit_id") or raw.get("auditId"),
        "kb_version": data.get("kb_version"),
        "metrics": data.get("metrics_ref") if isinstance(data.get("metrics_ref"), dict) else None,
        "evidence": evidence,
        "judges": _judges(data.get("judges")),
        "counter_evidence": [clip(str(c), 160) for c in counters[:2] if c],
        "citations": citations,
        "reasoning": clip(data.get("reasoning"), 280),
        "annotations": len(raw.get("annotations") or []) or None,
        "artifact_id": raw.get("id") if raw.get("kind") == "finding" else None,
    }
    return {k: v for k, v in row.items() if v not in (None, "", [], {})}


_GAP_VERDICTS = frozenset({"gap", "indicates_gap", "partial"})


def _finding_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tally = _tally(rows, "verdict")
    gaps = [r.get("id") for r in rows if r.get("verdict") in _GAP_VERDICTS]
    return {"total": len(rows), "by_verdict": tally, "gaps": gaps}


def _approval_row(item: dict[str, Any], kinds: dict[str, str]) -> dict[str, Any]:
    art = item.get("artifactId")
    row = {
        "gate": item.get("gate"),
        "decision": item.get("decision"),
        "reason_category": item.get("reasonCategory"),
        "comment": clip(item.get("comment"), 400),
        "edits": sorted((item.get("edits") or {}).keys()) or None,
        "artifact": f"{kinds.get(art, 'artifact')} {art}" if art else None,
        "decided_by": item.get("decidedBy"),
        "at": item.get("at"),
    }
    return {k: v for k, v in row.items() if v not in (None, "", [])}


def _annex_basis(card: dict[str, Any]) -> str | None:
    """``"Annex III 4(a)"`` -> ``AIA.ANNEX_III.4.a``."""
    match = _ANNEX_RE.search(str(card.get("annex_basis") or ""))
    if not match:
        return None
    parts = ["AIA", f"ANNEX_{match.group(1).upper()}"]
    parts += [p.lower() for p in match.groups()[1:] if p]
    return ".".join(parts)


def _obligation_row(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id",
        "obligation_id",
        "title",
        "obligation",
        "applies",
        "why",
        "source",
        "provisions",
        "verification_mode",
        "testability",
        "in_force",
        "in_force_from",
        "effective_valid_from",
    )
    out = {k: row.get(k) for k in keep if row.get(k) not in (None, "", [])}
    for key in ("why", "obligation"):
        if key in out:
            out[key] = clip(out[key], 200)
    return out


def _audit_error(audit_id: str, exc: WorkspaceAPIError) -> str:
    if exc.status == 404:
        return f"Audit {audit_id} does not exist; call list_audits for the real ids."
    return f"Could not read audit {audit_id}: {exc.public}."


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def history_builders(scope: WorkspaceScope, api: WorkspaceAPI) -> dict[str, Callable[[], BaseTool]]:
    """One factory per history tool, sharing the run's API client."""

    async def _active_and_releases() -> tuple[str | None, list[dict[str, Any]]]:
        body = await api.releases()
        items = [i for i in body.get("items") or [] if isinstance(i, dict)]
        active = body.get("active") if isinstance(body.get("active"), str) else None
        return active, items

    async def _changed(
        from_version: str, to_version: str, provisions: list[str] | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """(changed provision rows, the reg changes on the way, source)."""
        try:
            body = await api.release_diff(
                from_version, to_version, ",".join(provisions) if provisions else None
            )
            rows = rerun.provision_rows(body or {})
            return _filter_provisions(rows, provisions), [], "reg-memory diff"
        except WorkspaceAPIError as exc:
            if exc.status not in _MISSING:
                raise
        _, releases = await _active_and_releases()
        chain = rerun.release_chain(releases, to_version, from_version)
        if chain is None:
            raise WorkspaceAPIError("reg-memory", 404, "no release chain between the versions")
        changes = rerun.changes_between(await api.regmem_changes(), chain)
        details = await asyncio.gather(*(api.regmem_change(str(c["id"])) for c in changes))
        rows: list[dict[str, Any]] = []
        for change in details:
            rows.extend(rerun.provision_rows(change or {}))
        return _filter_provisions(rows, provisions), list(details), "changes on the release chain"

    async def list_kb_releases() -> str:
        try:
            active, items = await _active_and_releases()
        except WorkspaceAPIError as exc:
            return f"Could not list kb releases: {exc.public}."
        return dump({"active": active, "releases": [_release_row(i) for i in items][:MAX_ROWS]})

    async def diff_kb(
        from_version: str, to_version: str | None = None, provisions: list[str] | None = None
    ) -> str:
        try:
            target = (to_version or "").strip() or (await _active_and_releases())[0]
            if not target:
                return "reg-memory has no active kb release."
            rows, changes, source = await _changed(from_version.strip(), target, provisions)
        except WorkspaceAPIError as exc:
            return f"Could not diff {from_version} -> {to_version or 'active'}: {exc.public}."
        return dump(
            {
                "from": from_version,
                "to": target,
                "source": source,
                "total": len(rows),
                "by_change": _tally(rows, "change"),
                "by_change_type": _tally(rows, "change_type"),
                "reg_changes": [c.get("id") for c in changes if c.get("id")],
                "provisions": rows[:MAX_ROWS],
            }
        )

    async def list_reg_changes(status: str | None = None) -> str:
        try:
            items = await api.reg_changes()
        except WorkspaceAPIError as exc:
            return f"Could not list regulation changes: {exc.public}."
        if status:
            items = [i for i in items if i.get("status") == status]
        rows = [
            {
                "id": i.get("id"),
                "title": i.get("title"),
                "status": i.get("status"),
                "change_type": i.get("changeType"),
                "candidate_kb_version": i.get("candidateKbVersion"),
                "detected_at": i.get("detectedAt"),
                "provisions": len(i.get("provisions") or []),
                "affected_systems": [a.get("systemId") for a in i.get("affected") or []],
                "judge": i.get("judge"),
                "summary": clip(i.get("summary"), 200),
            }
            for i in items[:MAX_ROWS]
        ]
        return dump({"total": len(items), "items": rows})

    async def get_reg_change(change_id: str) -> str:
        cid = change_id.strip()
        try:
            inbox = await api.reg_change(cid)
        except WorkspaceAPIError as exc:
            return f"Could not read regulation change {cid}: {exc.public}."
        try:
            detail = await api.regmem_change(cid)
        except WorkspaceAPIError:
            detail = {}
        rows = rerun.provision_rows(detail) or [{"id": p} for p in inbox.get("provisions") or []]
        affected = [
            {
                k: v
                for k, v in {
                    "system_id": a.get("systemId"),
                    "decision": a.get("humanDecision") or a.get("decision"),
                    "judge_decision": a.get("decision"),
                    "confidence": a.get("confidence"),
                    "findings": a.get("findings") or None,
                    "reasoning": clip(a.get("reasoning"), 300),
                    "rerun_audit_id": a.get("rerunAuditId"),
                }.items()
                if v not in (None, "", [])
            }
            for a in inbox.get("affected") or []
        ]
        out = {
            "id": inbox.get("id") or cid,
            "title": inbox.get("title"),
            "status": inbox.get("status"),
            "change_type": inbox.get("changeType"),
            "from_kb_version": detail.get("from_kb_version"),
            "to_kb_version": detail.get("to_kb_version") or inbox.get("candidateKbVersion"),
            "summary": clip(inbox.get("summary"), 400),
            "by_change_type": _tally(rows, "change_type"),
            "impacted_requirements": [
                {"id": r.get("requirement_id"), "via": r.get("via")}
                for r in (inbox.get("impactedRequirements") or [])[:MAX_ROWS]
            ],
            "judge": inbox.get("judge"),
            "affected_systems": affected,
            "decided_by": inbox.get("decidedBy"),
            "provisions": rows[:MAX_ROWS],
            "provisions_total": len(rows),
        }
        return dump({k: v for k, v in out.items() if v not in (None, "", [])})

    async def _judged(system_id: str | None) -> dict[str, dict[str, Any]]:
        """Per reg change: its status and the judge's call for this system."""
        try:
            items = await api.reg_changes()
        except WorkspaceAPIError:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for item in items:
            entry: dict[str, Any] = {
                "title": item.get("title"),
                "status": item.get("status"),
                "change_type": item.get("changeType"),
            }
            for a in item.get("affected") or []:
                if a.get("systemId") == system_id:
                    entry["judge_decision"] = a.get("humanDecision") or a.get("decision")
                    entry["rerun_audit_id"] = a.get("rerunAuditId")
            out[str(item.get("id"))] = entry
        return out

    async def audit_needs_rerun(audit_id: str | None = None) -> str:
        aid = pick_audit(scope, audit_id)
        if aid is None:
            return NO_AUDIT
        try:
            audit = await api.audit(aid)
            active, _ = await _active_and_releases()
        except WorkspaceAPIError as exc:
            return _audit_error(aid, exc)
        pins = rerun.audit_pins(audit)
        pinned = pins.get("kb_version")
        relied = rerun.audit_provisions(audit)
        changed: list[dict[str, Any]] = []
        source = None
        if pinned and active and pinned != active:
            try:
                changed, _, source = await _changed(pinned, active, None)
            except WorkspaceAPIError as exc:
                return f"Could not diff {pinned} -> {active} for {aid}: {exc.public}."
        result = rerun.needs_rerun(
            audit_id=aid,
            system_id=audit.get("systemId"),
            pinned=pinned,
            active=active,
            changed=changed,
            relied=relied,
            judged=await _judged(audit.get("systemId")) if changed else None,
        )
        result["pins"] = pins
        result["obligations_checked"] = len([k for k in relied if not k.startswith("finding:")])
        if source:
            result["diff_source"] = source
        logger.info(
            "workspace_rerun_checked",
            "Copilot checked whether an audit needs a re-run",
            audit_id=aid,
            needs_rerun=result["needs_rerun"],
            changed=len(result["changed_provisions"]),
        )
        return dump(result)

    async def list_findings(audit_id: str | None = None, system_id: str | None = None) -> str:
        aid = (audit_id or "").strip() or None
        sid = (system_id or "").strip() or None
        if not aid and not sid:
            aid = scope.audit_id
            sid = None if aid else scope.system_id
        if not aid and not sid:
            return NO_AUDIT
        source = "findings"
        try:
            if aid:
                try:
                    raw = await api.audit_findings(aid)
                except WorkspaceAPIError as exc:
                    if exc.status not in _MISSING:
                        raise
                    raw, source = None, "finding artifacts"
                if not raw:
                    audit = await api.audit(aid)
                    raw = rerun.live_artifacts(audit, "finding")
                    source = "finding artifacts"
                    kb = rerun.audit_pins(audit).get("kb_version")
                else:
                    kb = None
                scope_label = {"audit_id": aid}
            else:
                sid = sid or ""
                try:
                    raw = await api.system_findings(sid)
                    scope_label = {"system_id": sid, "current": True}
                    kb = None
                except WorkspaceAPIError as exc:
                    if exc.status not in _MISSING:
                        raise
                    raw = []
                if not raw:
                    audits = await api.audits(sid)
                    if not audits:
                        return f"{sid} has no audits yet."
                    latest = audits[0]
                    audit = await api.audit(str(latest.get("id")))
                    raw = rerun.live_artifacts(audit, "finding")
                    source = "finding artifacts of the latest audit"
                    kb = rerun.audit_pins(audit).get("kb_version")
                    scope_label = {"system_id": sid, "audit_id": latest.get("id")}
        except WorkspaceAPIError as exc:
            return _audit_error(aid, exc) if aid else f"Could not list findings: {exc.public}."
        rows = [_finding_row(r) for r in raw or [] if isinstance(r, dict)]
        out: dict[str, Any] = {**scope_label, "source": source}
        if kb:
            out["kb_version"] = kb
        out["summary"] = _finding_summary(rows)
        out["findings"] = rows[:MAX_ROWS]
        return dump(out)

    async def get_gate_decisions(audit_id: str | None = None) -> str:
        aid = pick_audit(scope, audit_id)
        if aid is None:
            return NO_AUDIT
        try:
            audit = await api.audit(aid)
        except WorkspaceAPIError as exc:
            return _audit_error(aid, exc)
        kinds = {
            str(a.get("id")): f"{a.get('kind')}/{a.get('name')}"
            for a in audit.get("artifacts") or []
            if isinstance(a, dict)
        }
        approvals = [a for a in audit.get("approvals") or [] if isinstance(a, dict)]
        rows = [_approval_row(a, kinds) for a in approvals]
        data = audit.get("data") or {}
        pending = data.get("pending_gate") or data.get("pendingGate")
        out = {
            "audit_id": aid,
            "status": audit.get("status"),
            "stage": audit.get("stage"),
            "pending_gate": pending,
            "decisions": rows[:MAX_ROWS],
            "by_gate": _tally(rows, "gate"),
            "rejections": [r for r in rows if r.get("decision") not in ("approved", "approve")],
        }
        if not rows:
            out["note"] = "No human decision recorded at any gate yet."
        return dump({k: v for k, v in out.items() if v not in (None, "", [])})

    async def list_obligations(system_id: str | None = None, audit_id: str | None = None) -> str:
        aid = (audit_id or "").strip() or None
        sid = pick_system(scope, system_id)
        try:
            if aid is None and sid is not None:
                audits = await api.audits(sid)
                aid = str(audits[0].get("id")) if audits else None
            if aid:
                audit = await api.audit(aid)
                rows = rerun.obligation_map_rows(audit)
                if rows:
                    return dump(
                        {
                            "source": f"obligation_map of {aid}",
                            "kb_version": rerun.audit_pins(audit).get("kb_version"),
                            "obligations": [_obligation_row(r) for r in rows][: MAX_ROWS * 2],
                        }
                    )
                sid = sid or audit.get("systemId")
            if sid is None:
                return NO_SYSTEM
            card = ((await api.system(sid)).get("data") or {}).get("card") or {}
            risk = str(card.get("risk_class") or "").lower()
            params = {
                "role": card.get("role") or "provider",
                "risk_class": "high" if risk.startswith("high") else (risk or None),
                "basis": _annex_basis(card),
                "kb_version": await api.kb_version(),
            }
            try:
                items, source = await api.obligations(**params), "reg-memory obligations"
            except WorkspaceAPIError as exc:
                if exc.status not in _MISSING:
                    raise
                items, source = await api.requirements(**params), "reg-memory requirements"
        except WorkspaceAPIError as exc:
            return f"Could not list obligations: {exc.public}."
        return dump(
            {
                "system_id": sid,
                "source": source,
                "kb_version": params["kb_version"],
                "obligations": [_obligation_row(r) for r in items][: MAX_ROWS * 2],
            }
        )

    async def attach_upload_to_audit_draft(
        attachment_id: str, system_id: str | None = None, file_name: str | None = None
    ) -> str:
        sid = pick_system(scope, system_id)
        if sid is None:
            return NO_SYSTEM
        att = attachment_id.strip()
        if not att:
            return "An attachment_id is needed (it is shown next to the upload in the message)."
        name = _SAFE_NAME.sub("_", (file_name or "").strip().rsplit("/", 1)[-1]).strip("._")
        path = f"{UPLOAD_FOLDER}/{name or att}"
        try:
            body = await api.file_from_attachment(
                sid, att, path, reason=f"dataset uploaded in chat for an audit ({scope.agent_slug})"
            )
        except WorkspaceAPIError as exc:
            return f"Could not attach the upload to {sid}: {exc.public}."
        file = (body or {}).get("file") or {}
        logger.info(
            "workspace_upload_attached",
            "Copilot attached a chat upload to a system's datasets",
            system_id=sid,
            path=file.get("path") or path,
            version=file.get("version"),
        )
        stored = file.get("path") or path
        return dump(
            {
                "system_id": sid,
                "path": stored,
                "version": file.get("version"),
                "dataset_ref": stored,
                "next": "Pass dataset_ref to start_audit; the pipeline still checks it at Gate C.",
            }
        )

    def tool(fn: Any, name: str, description: str, schema: type[BaseModel]) -> Callable[[], Any]:
        return lambda: StructuredTool.from_function(
            coroutine=fn, name=name, description=description, args_schema=schema
        )

    return {
        LIST_KB_RELEASES: tool(
            list_kb_releases,
            LIST_KB_RELEASES,
            "Every kb release (regulation knowledge-base version): kb_version, status, parent, "
            "created_at, and which one is active.",
            _NoArgs,
        ),
        DIFF_KB: tool(
            diff_kb,
            DIFF_KB,
            "Which provisions changed between two kb versions (to defaults to the active one): "
            "counts by change and change_type, the regulation changes on the way, and per "
            "provision id, change and change_type. Filter with provisions.",
            _DiffArgs,
        ),
        LIST_REG_CHANGES: tool(
            list_reg_changes,
            LIST_REG_CHANGES,
            "The regulation change inbox: id, title, status, candidate kb_version, affected "
            "systems and whether the change judge has run.",
            _ChangesArgs,
        ),
        GET_REG_CHANGE: tool(
            get_reg_change,
            GET_REG_CHANGE,
            "One regulation change: from/to kb_version, changed provisions with change_type, "
            "impacted requirements, and the judge's decision per affected system.",
            _ChangeArgs,
        ),
        AUDIT_NEEDS_RERUN: tool(
            audit_needs_rerun,
            AUDIT_NEEDS_RERUN,
            "Deterministic check (no model): compares the audit's pinned kb_version with the "
            "active one and intersects the changed provisions with the audit's obligations and "
            "cited provisions. Returns needs_rerun, reason, changed_provisions, "
            "affected_obligations, affected_findings, related_reg_changes and the pins.",
            _AuditArgs,
        ),
        LIST_FINDINGS: tool(
            list_findings,
            LIST_FINDINGS,
            "Findings of one audit (audit_id) or a system's current findings (system_id): "
            "verdict tally, gap ids, and per finding the obligation, verdict, severity, "
            "evidence (metric, value, threshold and its source), counter-evidence, citations.",
            _FindingsArgs,
        ),
        GET_GATE_DECISIONS: tool(
            get_gate_decisions,
            GET_GATE_DECISIONS,
            "The human decisions at an audit's gates (scenarios, public data, datasets, "
            "sign-off): decision, reason category, comment, edited fields, who and when; "
            "plus the pending gate.",
            _AuditArgs,
        ),
        LIST_OBLIGATIONS: tool(
            list_obligations,
            LIST_OBLIGATIONS,
            "The obligations that apply to a system: its latest audit's obligation map, else "
            "the catalogue for its role, risk class and Annex basis at the active kb_version. "
            "Use the ids to tie scenarios and focused audits to obligations.",
            _ObligationArgs,
        ),
        ATTACH_UPLOAD_TO_AUDIT_DRAFT: tool(
            attach_upload_to_audit_draft,
            ATTACH_UPLOAD_TO_AUDIT_DRAFT,
            f"Copy a file the user uploaded in this chat into the system folder under "
            f"{UPLOAD_FOLDER}/ so an audit can use it as its dataset (returns the dataset_ref). "
            "The user is asked before it is written.",
            _AttachArgs,
        ),
    }


__all__ = [
    "ATTACH_UPLOAD_TO_AUDIT_DRAFT",
    "AUDIT_NEEDS_RERUN",
    "HISTORY_TOOL_NAMES",
    "UPLOAD_FOLDER",
    "history_builders",
]
