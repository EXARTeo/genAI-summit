"""``POST /changes/{id}/judge``: RegChange → obligation maps → impact → judge → re-run → delta.

1. The RegChange comes from reg-memory (or the request); the systems' latest
   evidence from the backend's ``GET /internal/impact-index``, merged with what
   the backend sends on accept (``systems``: each card + its current sealed
   findings).
2. Each system's **obligation map** is resolved at the change's ``to_kb_version``
   (``pipeline/obligations.py``, Iris on the borderline rows); impact = the
   changed provisions ∩ the map's applicable obligations (+ the older
   requirement / citation paths, ``pipeline/impact.py``).
3. The change judge (Iris, Gemini fallback) decides per affected system. Each
   judgement is a ``change_judgement`` artifact (``name`` = the change id,
   ``status: proposed``) on the system's latest audit (or on the re-run when the
   system has none). Old findings are never rewritten: a decision other than
   ``no_impact`` marks the findings on the affected obligations ``stale`` (a
   ``POST /internal/findings/{id}/status-events`` for sealed findings, else a
   ``finding_status`` artifact on the old audit).
4. With ``rerun``, ``rerun_tests`` / ``new_tests_needed`` start a **focused**
   audit (``data.obligations`` = the affected obligation ids, ``data.kb_version``
   = the new kb). A background watcher waits for it to finish and writes a
   ``delta_report`` artifact on it: per obligation, old verdict → new verdict,
   metric deltas, and whether the law or the model changed.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from pipeline.clients import BackendImpact, BackendInternal, PipelineHTTPError, RegMemory
from pipeline.decision import IrisClient
from pipeline.impact import (
    AffectedSystem,
    ChangeJudge,
    decision_model,
    finding_obligation,
    impact_index,
    judge_brief,
)
from pipeline.obligations import resolve_obligation_map
from pipeline.steps import StepScope

from core.logging import get_logger
from core.settings import settings
from schema.audits import ChangeJudgeIn, ChangeJudgementOut, ChangeJudgeOut

logger = get_logger(__name__)

RERUN_DECISIONS = {"rerun_tests", "new_tests_needed"}
TERMINAL_AUDIT_STATUSES = {"done", "failed", "completed", "stopped"}
#: The backend's public reads (``/v1/audits/{id}/findings``) need a client id; this one
#: names the change judge in the backend's logs.
SERVICE_CLIENT_ID = "00000000-0000-4000-8000-00000000c0de"
DELTA_POLL_SECONDS = 20.0
DELTA_TIMEOUT_SECONDS = 6 * 3600.0
_SLUG = re.compile(r"[^A-Za-z0-9._:-]+")

#: The delta watchers in flight (kept referenced until they finish).
_watchers: set[asyncio.Task[Any]] = set()

Resolver = Callable[..., Awaitable[list[dict[str, Any]]]]


def _slug(value: str) -> str:
    cleaned = _SLUG.sub("-", value).strip("-.") or "x"
    return cleaned[:128]


class FindingsApi:
    """The backend's sealed-findings routes the change flow needs (Agent C's tables)."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.base = settings.pipeline.backend_internal_url.rstrip("/")
        self.client = client
        secret = settings.proxy.internal_service_secret.get_secret_value()
        self.headers = {"X-Internal-Secret": secret, "X-Agent-Name": "change-judge"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response | None:
        client = self.client or httpx.AsyncClient(timeout=30.0)
        try:
            return await client.request(method, f"{self.base}{path}", **kwargs)
        except httpx.HTTPError as exc:
            logger.warning(
                "findings_api_unreachable",
                "Backend findings route unreachable",
                path=path,
                failure_reason=type(exc).__name__,
            )
            return None
        finally:
            if self.client is None:
                await client.aclose()

    async def status_event(self, finding_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        """``POST /internal/findings/{id}/status-events``; ``None`` when not possible."""
        resp = await self._request(
            "POST",
            f"/internal/findings/{quote(finding_id, safe='')}/status-events",
            json=body,
            headers=self.headers,
        )
        if resp is None or resp.status_code >= 400:
            return None
        return resp.json() if resp.content else {}

    async def audit_findings(self, audit_id: str) -> list[dict[str, Any]]:
        """An audit's sealed findings (``[]`` when none or the route is missing)."""
        resp = await self._request(
            "GET",
            f"/v1/audits/{quote(audit_id, safe='')}/findings",
            headers={"X-Client-Id": SERVICE_CLIENT_ID},
        )
        if resp is None or resp.status_code >= 400:
            return []
        body = resp.json()
        return [f for f in body if isinstance(f, dict)] if isinstance(body, list) else []


# ---- inputs ----------------------------------------------------------------------------------


def merge_systems(
    index: list[dict[str, Any]], extra: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """The impact index + the backend's cards and sealed findings (sealed findings win)."""
    by_id = {str(s.get("system_id")): dict(s) for s in index}
    for item in extra or []:
        sid = str(item.get("system_id") or item.get("id") or "")
        if not sid:
            continue
        row = by_id.setdefault(sid, {"system_id": sid, "findings": [], "tests": []})
        if item.get("card"):
            row["card"] = item["card"]
        if item.get("name"):
            row.setdefault("name", item["name"])
        sealed = [{**f, "sealed": True} for f in item.get("findings") or [] if isinstance(f, dict)]
        if sealed:
            row["findings"] = sealed
            row.setdefault("audit_id", sealed[0].get("audit_id"))
            row["kb_version"] = row.get("kb_version") or sealed[0].get("kb_version")
    return list(by_id.values())


async def obligation_maps(
    systems: list[dict[str, Any]],
    kb_version: str | None,
    *,
    resolver: Resolver,
    regmem: RegMemory,
    iris: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Each system's obligation map at ``kb_version`` (a system without a card is skipped)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for system in systems:
        card = system.get("card")
        if not isinstance(card, dict):
            continue
        try:
            out[str(system["system_id"])] = await resolver(
                card, kb_version, iris=iris, regmem=regmem
            )
        except Exception as exc:  # the requirement / citation paths still work without it
            logger.warning(
                "obligation_map_failed",
                "Could not resolve a system's obligation map",
                system_id=system.get("system_id"),
                failure_reason=type(exc).__name__,
            )
    return out


def focused_obligations(system: AffectedSystem, entries: list[dict[str, Any]]) -> list[str]:
    """The re-run's scope: the affected obligations, else those behind impacted requirements."""
    if system.via_obligations:
        return list(system.via_obligations)
    reqs = set(system.via_requirements)
    return sorted(
        e["obligation_id"]
        for e in entries
        if e.get("applicable") and reqs & set(e.get("requirements") or [])
    )


# ---- stale marks -----------------------------------------------------------------------------


async def mark_stale(
    system: AffectedSystem,
    change: dict[str, Any],
    decision: str,
    *,
    audit_backend: Callable[[str], BackendInternal],
    findings_api: FindingsApi,
    entries: list[dict[str, Any]],
) -> list[str]:
    """Mark the latest findings on the affected obligations ``stale`` (never an edit)."""
    change_id = str(change.get("id") or "")
    marked: list[str] = []
    for finding in system.affected_findings:
        fid = str(finding.get("id") or "")
        if not fid:
            continue
        obligation = finding_obligation(finding, entries)
        reason = (
            f"Regulation change {change_id} ({change.get('from_kb_version')} -> "
            f"{change.get('to_kb_version')}) touched {obligation or finding.get('requirement')}; "
            f"change judge: {decision}."
        )
        data = {
            "reg_change_id": change_id,
            "from_kb_version": change.get("from_kb_version"),
            "to_kb_version": change.get("to_kb_version"),
            "decision": decision,
            "obligation_id": obligation,
        }
        done = False
        if finding.get("sealed") or finding.get("hash"):
            event = await findings_api.status_event(
                fid, {"status": "stale", "reason": reason, "data": data}
            )
            done = event is not None
        audit_id = finding.get("audit_id") or system.audit_id
        if not done and audit_id:
            try:
                await audit_backend(str(audit_id)).write_artifact(
                    "finding_status",
                    {"finding": fid, "status": "stale", "reason": reason, **data},
                    name=_slug(f"{fid}.{change_id}"),
                )
                done = True
            except PipelineHTTPError as exc:
                logger.warning(
                    "finding_stale_failed",
                    "Could not mark a finding stale",
                    finding_id=fid,
                    failure_reason=exc.public_message,
                )
        if done:
            marked.append(fid)
    return marked


# ---- the delta report ------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "point", "estimate"):
            if isinstance(value.get(key), (int, float)):
                return float(value[key])
    return None


def finding_metrics(finding: dict[str, Any]) -> dict[str, float]:
    """``metric -> value`` from a finding (sealed ``metrics_ref`` / ``metrics`` / data)."""
    out: dict[str, float] = {}
    sources = [finding.get("metrics"), finding.get("metrics_ref")]
    data = finding.get("data") if isinstance(finding.get("data"), dict) else {}
    sources += [data.get("metrics"), data.get("metrics_ref")]
    for src in sources:
        if isinstance(src, dict):
            for name, value in src.items():
                num = _number(value)
                if num is not None:
                    out.setdefault(str(name), num)
        elif isinstance(src, list):
            for item in src:
                if not isinstance(item, dict):
                    continue
                name = item.get("metric") or item.get("name")
                num = _number(item.get("value"))
                if name and num is not None:
                    out.setdefault(str(name), num)
    for f in (finding, data):
        if f.get("metric") and _number(f.get("value")) is not None:
            out.setdefault(str(f["metric"]), float(f["value"]))
    return out


def _model_version(audit: dict[str, Any] | None) -> str | None:
    if not audit:
        return None
    pins = audit.get("pins") or (audit.get("data") or {}).get("pins") or {}
    data = audit.get("data") or {}
    value = pins.get("model_version") or data.get("model_version") or data.get("model_uri")
    return str(value) if value else None


def _brief(finding: dict[str, Any] | None) -> dict[str, Any] | None:
    if not finding:
        return None
    return {
        k: finding.get(k)
        for k in ("id", "audit_id", "verdict", "severity", "gap_id", "kb_version")
        if finding.get(k) is not None
    }


def build_delta_report(
    ctx: dict[str, Any],
    old_findings: list[dict[str, Any]],
    new_findings: list[dict[str, Any]],
    *,
    old_audit: dict[str, Any] | None,
    new_audit: dict[str, Any] | None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per obligation of the focused re-run: old verdict -> new verdict, metric deltas and
    the reason (``law_changed`` / ``model_changed`` / ``law_and_model_changed``)."""
    entries = entries or []
    old_by = {finding_obligation(f, entries): f for f in old_findings}
    new_by = {finding_obligation(f, entries): f for f in new_findings}
    obligations = list(ctx.get("obligations") or [])
    for oid in [*old_by, *new_by]:
        if oid and oid not in obligations and (not obligations or oid in new_by):
            obligations.append(oid)
    old_model, new_model = _model_version(old_audit), _model_version(new_audit)
    model_changed = bool(old_model and new_model and old_model != new_model)
    rows = []
    for oid in obligations:
        old, new = old_by.get(oid), new_by.get(oid)
        old_kb = (old or {}).get("kb_version") or ctx.get("from_kb_version")
        new_kb = (new or {}).get("kb_version") or ctx.get("to_kb_version")
        law_changed = bool(old_kb and new_kb and old_kb != new_kb)
        if old is None and new is None:
            reason = "not_assessed"
        elif old is None:
            reason = "new_evidence"
        elif new is None:
            reason = "no_new_verdict"
        elif law_changed and model_changed:
            reason = "law_and_model_changed"
        elif model_changed:
            reason = "model_changed"
        elif law_changed:
            reason = "law_changed"
        else:
            reason = "unchanged"
        old_m, new_m = finding_metrics(old or {}), finding_metrics(new or {})
        deltas = [
            {
                "metric": m,
                "old": old_m.get(m),
                "new": new_m.get(m),
                "delta": round(new_m[m] - old_m[m], 6) if m in old_m and m in new_m else None,
            }
            for m in sorted(set(old_m) | set(new_m))
        ]
        old_v, new_v = (old or {}).get("verdict"), (new or {}).get("verdict")
        rows.append(
            {
                "obligation_id": oid,
                "old": _brief(old),
                "new": _brief(new),
                "verdict_change": f"{old_v or '—'} -> {new_v or '—'}",
                "verdict_changed": old_v != new_v,
                "metric_deltas": deltas,
                "reason": reason,
            }
        )
    changed = sum(1 for r in rows if r["verdict_changed"])
    return {
        "change_id": ctx.get("change_id"),
        "system_id": ctx.get("system_id"),
        "decision": ctx.get("decision"),
        "previous_audit_id": ctx.get("previous_audit_id"),
        "audit_id": (new_audit or {}).get("id"),
        "audit_status": (new_audit or {}).get("status"),
        "from_kb_version": ctx.get("from_kb_version"),
        "to_kb_version": ctx.get("to_kb_version"),
        "model_version": {"old": old_model, "new": new_model},
        "obligations": rows,
        "summary": (
            f"{len(rows)} obligation(s) re-assessed after {ctx.get('change_id')}: "
            f"{changed} verdict(s) changed."
        ),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _artifact_findings(audit: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**(a.get("data") or {}), "id": a.get("name"), "artifact_id": a.get("id")}
        for a in audit.get("artifacts") or []
        if a.get("kind") == "finding" and a.get("status") != "superseded"
    ]


async def write_delta_report(
    audit_id: str,
    ctx: dict[str, Any],
    *,
    audit_backend: Callable[[str], BackendInternal],
    findings_api: FindingsApi,
) -> dict[str, Any]:
    """Build and store the ``delta_report`` artifact of a finished focused audit."""
    new_audit = (await audit_backend(audit_id).audit()).get("audit") or {}
    new_findings = await findings_api.audit_findings(audit_id) or _artifact_findings(new_audit)
    old_audit = None
    if ctx.get("previous_audit_id"):
        try:
            old_audit = (await audit_backend(str(ctx["previous_audit_id"])).audit()).get("audit")
        except PipelineHTTPError:
            old_audit = None
    report = build_delta_report(
        ctx,
        list(ctx.get("old_findings") or []),
        new_findings,
        old_audit=old_audit,
        new_audit=new_audit,
        entries=ctx.get("entries"),
    )
    art = await audit_backend(audit_id).write_artifact(
        "delta_report", report, name=_slug(str(ctx.get("change_id") or "main"))
    )
    logger.info(
        "delta_report_written",
        "Delta report written for a focused re-run",
        audit_id=audit_id,
        change_id=ctx.get("change_id"),
        obligations=len(report["obligations"]),
    )
    return {**report, "artifact_id": art.get("id")}


async def watch_delta(
    audit_id: str,
    ctx: dict[str, Any],
    *,
    audit_backend: Callable[[str], BackendInternal],
    findings_api: FindingsApi,
    poll_seconds: float = DELTA_POLL_SECONDS,
    timeout_seconds: float = DELTA_TIMEOUT_SECONDS,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> dict[str, Any] | None:
    """Wait for the focused audit to finish, then write its delta report (best effort)."""
    waited = 0.0
    while waited <= timeout_seconds:
        try:
            body = await audit_backend(audit_id).audit()
            current = str((body.get("audit") or {}).get("status") or "")
        except PipelineHTTPError:
            current = ""
        if current in TERMINAL_AUDIT_STATUSES:
            try:
                return await write_delta_report(
                    audit_id, ctx, audit_backend=audit_backend, findings_api=findings_api
                )
            except Exception as exc:
                logger.warning(
                    "delta_report_failed",
                    "Could not write the delta report",
                    audit_id=audit_id,
                    failure_reason=type(exc).__name__,
                )
                return None
        await sleep(poll_seconds)
        waited += poll_seconds
    logger.warning("delta_report_timeout", "Focused re-run did not finish", audit_id=audit_id)
    return None


async def delta_for_audit(
    audit_id: str,
    *,
    audit_backend: Callable[[str], BackendInternal] | None = None,
    findings_api: FindingsApi | None = None,
) -> dict[str, Any]:
    """(Re)write the delta report of a focused re-run from what is stored: the audit's
    ``change_judgement`` artifact (scope, kb versions) and the previous audit's findings.
    For a watcher lost to a restart, or the pipeline's own end-of-audit hook."""
    audit_backend = audit_backend or (lambda aid: BackendInternal(aid, agent="change-judge"))
    findings_api = findings_api or FindingsApi()
    try:
        audit = (await audit_backend(audit_id).audit()).get("audit") or {}
    except PipelineHTTPError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.public_message) from exc
    data = audit.get("data") or {}
    judged = next(
        (
            a.get("data") or {}
            for a in reversed(audit.get("artifacts") or [])
            if a.get("kind") == "change_judgement"
        ),
        {},
    )
    change_id = data.get("change_id") or judged.get("change_id")
    if not change_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Not a regulation-change re-run.")
    previous = data.get("previous_audit_id")
    old: list[dict[str, Any]] = []
    if previous:
        old = await findings_api.audit_findings(str(previous))
        if not old:
            try:
                prev = (await audit_backend(str(previous)).audit()).get("audit") or {}
                old = _artifact_findings(prev)
            except PipelineHTTPError:
                old = []
    scope = list(data.get("obligations") or judged.get("affected_obligations") or [])
    old = [
        f for f in old if not scope or f.get("obligation_id") in scope or not f.get("obligation_id")
    ]
    ctx = {
        "change_id": change_id,
        "system_id": audit.get("systemId") or audit.get("system_id"),
        "decision": data.get("change_decision") or judged.get("decision"),
        "previous_audit_id": previous,
        "from_kb_version": judged.get("from_kb_version"),
        "to_kb_version": judged.get("to_kb_version") or data.get("kb_version"),
        "obligations": scope,
        "old_findings": old,
    }
    return await write_delta_report(
        audit_id, ctx, audit_backend=audit_backend, findings_api=findings_api
    )


def _spawn(coro: Awaitable[Any]) -> None:
    task = asyncio.ensure_future(coro)
    _watchers.add(task)
    task.add_done_callback(_watchers.discard)


# ---- the route's logic ------------------------------------------------------------------------


async def judge_change(
    change_id: str,
    body: ChangeJudgeIn,
    *,
    regmem: RegMemory | None = None,
    backend: BackendImpact | None = None,
    model: ChangeJudge | None = None,
    audit_backend: Callable[[str], BackendInternal] | None = None,
    resolver: Resolver | None = None,
    iris: Any = None,
    findings_api: FindingsApi | None = None,
    spawn: Callable[[Awaitable[Any]], None] | None = None,
) -> ChangeJudgeOut:
    audit_backend = audit_backend or (lambda aid: BackendInternal(aid, agent="change-judge"))
    regmem = regmem or RegMemory()
    backend = backend or BackendImpact()
    model = model or decision_model()
    resolver = resolver or resolve_obligation_map
    findings_api = findings_api or FindingsApi()
    spawn = spawn or _spawn
    if iris is None:
        client = IrisClient()
        iris = client if client.configured else None
    try:
        change: dict[str, Any] = body.change or await regmem.change(change_id)
        systems = merge_systems(await backend.impact_index(), body.systems)
    except PipelineHTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=exc.public_message) from exc
    if body.system_ids:
        systems = [s for s in systems if s.get("system_id") in set(body.system_ids)]
    result_id = str(change.get("id") or change_id)
    to_kb = change.get("to_kb_version")
    maps = await obligation_maps(systems, to_kb, resolver=resolver, regmem=regmem, iris=iris)
    affected = impact_index(change, systems, maps)
    out: list[ChangeJudgementOut] = []
    for system in affected:
        entries = maps.get(system.system_id) or []
        scope = StepScope(
            audit_id=system.audit_id or f"change-{change_id}",
            system_id=system.system_id,
            kb_version=to_kb,
            step="change_judge",
            regmem=regmem,
        )
        decision = await model.judge(judge_brief(change, system), scope)
        judgement = decision.result
        data = judgement.model_dump(mode="json")
        focus = focused_obligations(system, entries)
        artifact = {
            **data,
            "change_id": result_id,
            "from_kb_version": change.get("from_kb_version"),
            "to_kb_version": to_kb,
            "via_requirements": system.via_requirements,
            "via_provisions": system.via_provisions,
            "via_obligations": system.via_obligations,
            "affected_obligations": focus,
            "decided_by": decision.model,
            "decision_fallback": decision.fallback,
        }
        artifact_id = rerun_id = None
        if system.audit_id:
            art = await audit_backend(system.audit_id).write_artifact(
                "change_judgement", artifact, name=_slug(result_id)
            )
            artifact_id = art.get("id")
        stale: list[str] = []
        if judgement.decision != "no_impact":
            stale = await mark_stale(
                system,
                change,
                judgement.decision,
                audit_backend=audit_backend,
                findings_api=findings_api,
                entries=entries,
            )
        if body.rerun and judgement.decision in RERUN_DECISIONS:
            rerun_data: dict[str, Any] = {
                "trigger": f"regchange:{result_id}",
                "kb_version": to_kb,
                "previous_audit_id": system.audit_id,
                "change_decision": judgement.decision,
                "change_id": result_id,
                "focused": bool(focus),
            }
            if focus:
                rerun_data["obligations"] = focus
            audit = await backend.start_audit(system.system_id, rerun_data)
            rerun_id = audit.get("id")
            if rerun_id and not system.audit_id:
                art = await audit_backend(str(rerun_id)).write_artifact(
                    "change_judgement", artifact, name=_slug(result_id)
                )
                artifact_id = art.get("id")
            if rerun_id:
                ctx = {
                    "change_id": result_id,
                    "system_id": system.system_id,
                    "decision": judgement.decision,
                    "previous_audit_id": system.audit_id,
                    "from_kb_version": change.get("from_kb_version"),
                    "to_kb_version": to_kb,
                    "obligations": focus,
                    "old_findings": system.affected_findings,
                    "entries": entries,
                }
                spawn(
                    watch_delta(
                        str(rerun_id), ctx, audit_backend=audit_backend, findings_api=findings_api
                    )
                )
        logger.info(
            "change_judged",
            "Regulation change judged for a system",
            change_id=change_id,
            system_id=system.system_id,
            decision=judgement.decision,
            rerun=rerun_id is not None,
            decided_by=decision.model,
            obligations=len(focus),
            stale=len(stale),
        )
        out.append(
            ChangeJudgementOut(
                system_id=system.system_id,
                audit_id=system.audit_id,
                decided_by=decision.model,
                artifact_id=artifact_id,
                rerun_audit_id=rerun_id,
                affected_obligations=focus,
                stale_findings=stale,
                **data,
            )
        )
    used = sorted({j.decided_by for j in out})
    decided_by = "+".join(used) if used else model.name
    affected_rows = [
        {
            "systemId": j.system_id,
            "systemName": next(
                (
                    str(s.get("name") or j.system_id)
                    for s in systems
                    if s.get("system_id") == j.system_id
                ),
                j.system_id,
            ),
            "path": [*a.via_obligations, *a.via_requirements, *a.via_provisions],
            "obligations": j.affected_obligations,
            "findings": j.affected_findings,
            "staleFindings": j.stale_findings,
            "decision": j.decision,
            "confidence": j.confidence,
            "reasoning": j.rationale,
            "counterArgument": j.strongest_counter_argument,
            "auditId": j.audit_id,
            "artifactId": j.artifact_id,
            "rerunAuditId": j.rerun_audit_id,
            "decidedBy": j.decided_by,
        }
        for j, a in zip(out, affected, strict=True)
    ]
    try:
        await backend.store_judgement(result_id, affected_rows, decided_by)
    except Exception as exc:  # the judgements are on the audits; the inbox row can catch up
        logger.warning(
            "change_judgement_store_failed",
            "Could not write the judgement onto the regulation change",
            change_id=result_id,
            failure_reason=type(exc).__name__,
        )
    return ChangeJudgeOut(
        change_id=result_id,
        kb_version=to_kb,
        impacted_requirements=[
            str(r.get("requirement_id")) for r in change.get("impacted_requirements") or []
        ],
        judgements=out,
    )


__all__ = [
    "FindingsApi",
    "build_delta_report",
    "delta_for_audit",
    "finding_metrics",
    "judge_change",
    "mark_stale",
    "merge_systems",
    "watch_delta",
    "write_delta_report",
]
