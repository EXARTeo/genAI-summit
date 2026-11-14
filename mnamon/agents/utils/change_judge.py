"""``POST /changes/{id}/judge``: RegChange → impact index → change judge → artifacts (+ re-runs).

The RegChange comes from reg-memory (or the request); the systems' latest
evidence from the backend's ``GET /internal/impact-index``. Each judgement is a
``change_judgement`` artifact (``name`` = the change id, ``status: proposed``)
on the system's latest audit; the old findings are never rewritten. With
``rerun`` a ``rerun_tests`` / ``new_tests_needed`` judgement starts a new audit
of the system pinned to the change's ``to_kb_version``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from pipeline.clients import BackendImpact, BackendInternal, PipelineHTTPError, RegMemory
from pipeline.impact import DecisionModel, decision_model, impact_index, judge_brief
from pipeline.steps import StepScope

from core.logging import get_logger
from schema.audits import ChangeJudgeIn, ChangeJudgementOut, ChangeJudgeOut

logger = get_logger(__name__)

RERUN_DECISIONS = {"rerun_tests", "new_tests_needed"}


async def judge_change(
    change_id: str,
    body: ChangeJudgeIn,
    *,
    regmem: RegMemory | None = None,
    backend: BackendImpact | None = None,
    model: DecisionModel | None = None,
    audit_backend: Callable[[str], BackendInternal] | None = None,
) -> ChangeJudgeOut:
    audit_backend = audit_backend or (lambda aid: BackendInternal(aid, agent="change-judge"))
    regmem = regmem or RegMemory()
    backend = backend or BackendImpact()
    model = model or decision_model()
    try:
        change: dict[str, Any] = body.change or await regmem.change(change_id)
        systems = await backend.impact_index()
    except PipelineHTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=exc.public_message) from exc
    if body.system_ids:
        systems = [s for s in systems if s.get("system_id") in set(body.system_ids)]
    affected = impact_index(change, systems)
    out: list[ChangeJudgementOut] = []
    for system in affected:
        scope = StepScope(
            audit_id=system.audit_id or f"change-{change_id}",
            system_id=system.system_id,
            kb_version=change.get("to_kb_version"),
            step="change_judge",
            regmem=regmem,
        )
        judgement = await model.judge(judge_brief(change, system), scope)
        data = judgement.model_dump(mode="json")
        artifact_id = rerun_id = None
        if system.audit_id:
            art = await audit_backend(system.audit_id).write_artifact(
                "change_judgement",
                {
                    **data,
                    "change_id": change.get("id") or change_id,
                    "from_kb_version": change.get("from_kb_version"),
                    "to_kb_version": change.get("to_kb_version"),
                    "via_requirements": system.via_requirements,
                    "via_provisions": system.via_provisions,
                    "decided_by": model.name,
                },
                name=str(change.get("id") or change_id),
            )
            artifact_id = art.get("id")
        if body.rerun and judgement.decision in RERUN_DECISIONS:
            audit = await backend.start_audit(
                system.system_id,
                {
                    "trigger": f"regchange:{change.get('id') or change_id}",
                    "kb_version": change.get("to_kb_version"),
                    "previous_audit_id": system.audit_id,
                    "change_decision": judgement.decision,
                },
            )
            rerun_id = audit.get("id")
        logger.info(
            "change_judged",
            "Regulation change judged for a system",
            change_id=change_id,
            system_id=system.system_id,
            decision=judgement.decision,
            rerun=rerun_id is not None,
        )
        out.append(
            ChangeJudgementOut(
                system_id=system.system_id,
                audit_id=system.audit_id,
                decided_by=model.name,
                artifact_id=artifact_id,
                rerun_audit_id=rerun_id,
                **data,
            )
        )
    result_id = str(change.get("id") or change_id)
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
            "path": [*a.via_requirements, *a.via_provisions],
            "findings": j.affected_findings,
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
        await backend.store_judgement(result_id, affected_rows, model.name)
    except Exception as exc:  # the judgements are on the audits; the inbox row can catch up
        logger.warning(
            "change_judgement_store_failed",
            "Could not write the judgement onto the regulation change",
            change_id=result_id,
            failure_reason=type(exc).__name__,
        )
    return ChangeJudgeOut(
        change_id=result_id,
        kb_version=change.get("to_kb_version"),
        impacted_requirements=[
            str(r.get("requirement_id")) for r in change.get("impacted_requirements") or []
        ],
        judgements=out,
    )


__all__ = ["judge_change"]
