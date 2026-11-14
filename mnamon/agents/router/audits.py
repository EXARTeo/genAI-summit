"""The audit and impact pipelines' routes (internal secret, called by the backend).

``POST /audits/{id}/run``       start (or continue) an audit's pipeline: 202.
``POST /audits/{id}/resume``    answer the gate it waits at (a human decision): 202.
``GET  /audits/{id}/state``     where the pipeline stands (``?system_id=``).
``POST /changes/{id}/judge``    impact index + change judge for a RegChange.

Thin: the logic is ``utils/audit_runs.py`` and ``utils/change_judge.py``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from core.security.internal_trust import require_internal_caller
from schema.audits import (
    ID_PATTERN,
    AuditResumeIn,
    AuditRunIn,
    AuditRunOut,
    AuditStateOut,
    ChangeJudgeIn,
    ChangeJudgeOut,
)
from utils.audit_runs import audit_state, resume_audit_run, start_audit_run
from utils.change_judge import judge_change

router = APIRouter(dependencies=[Depends(require_internal_caller)])

AuditId = Annotated[str, Path(pattern=ID_PATTERN)]


@router.post(
    "/audits/{audit_id}/run", response_model=AuditRunOut, status_code=status.HTTP_202_ACCEPTED
)
async def run_audit(audit_id: AuditId, body: AuditRunIn) -> AuditRunOut:
    """Start the audit pipeline in the background (or continue a cut run)."""
    return await start_audit_run(audit_id, body)


@router.post(
    "/audits/{audit_id}/resume", response_model=AuditRunOut, status_code=status.HTTP_202_ACCEPTED
)
async def resume_audit(audit_id: AuditId, body: AuditResumeIn) -> AuditRunOut:
    """Resume the pipeline with a human decision at its pending gate."""
    return await resume_audit_run(audit_id, body)


@router.get("/audits/{audit_id}/state", response_model=AuditStateOut)
async def get_audit_state(
    audit_id: AuditId, system_id: Annotated[str, Query(pattern=ID_PATTERN)]
) -> AuditStateOut:
    """The pipeline's checkpoint: next node, pending gate, artifact ids."""
    return await audit_state(audit_id, system_id)


@router.post("/changes/{change_id}/judge", response_model=ChangeJudgeOut)
async def judge(
    change_id: Annotated[str, Path(pattern=ID_PATTERN)], body: ChangeJudgeIn
) -> ChangeJudgeOut:
    """Impact index (no LLM) → change judge per affected system → artifacts (+ re-runs)."""
    return await judge_change(change_id, body)
