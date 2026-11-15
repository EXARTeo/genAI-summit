"""Start an audit's pipeline on the agents service, and forward human gate decisions to it.

``start_pipeline``: a new audit (``POST /v1/systems/{id}/audits``, or the change
judge's re-run through ``POST /internal/systems/{id}/audits``) calls
``POST {AGENTS_SERVICE_URL}/audits/{id}/run`` (202, the pipeline runs in the
background there). Off with ``AUDIT_PIPELINE_AUTOSTART=false`` or an audit
created with ``data.autostart: false``.

The pipeline (agents service, ``pipeline/graph.py``) pauses at each gate on a
LangGraph ``interrupt()``; ``POST {AGENTS_SERVICE_URL}/audits/{id}/resume``
answers it. Every approval of a pipeline gate (``public_data``, ``scenarios``,
``datasets``), from the UI or from Telegram, is forwarded here after it is
recorded. A 409 right after the gate opens (the backend shows ``waiting_approval``
a moment before the pipeline's interrupt is checkpointed) is retried for ~10 s.
Best effort after that: a pipeline that is not waiting (409) or not reachable
is logged, the approval stays recorded.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import HTTPException

from core.database import ApprovalTable, AuditTable
from core.logging import get_logger
from core.settings import settings
from utils.agents import internal_headers

logger = get_logger(__name__)

PIPELINE_GATES = frozenset({"public_data", "scenarios", "datasets"})

#: Waits (s) before each retry of a resume the pipeline answered with 409 (~10 s in all).
RESUME_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 2.0, 3.0)

#: A test seam: tests swap in an ``httpx.MockTransport``.
transport: httpx.AsyncBaseTransport | None = None


async def _post(path: str, body: dict[str, Any]) -> int | None:
    url = f"{settings.upstream.agents_service_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(
            timeout=settings.http.agents_timeout, transport=transport
        ) as client:
            response = await client.post(url, json=body, headers=internal_headers())
    except httpx.HTTPError:
        return None
    return response.status_code


async def start_pipeline(audit: AuditTable) -> str:
    """``started``, ``skipped`` (off), ``http_<code>`` or ``failed``; never raises."""
    data = audit.data or {}
    if not settings.upstream.audit_pipeline_autostart or data.get("autostart") is False:
        return "skipped"
    code = await _post(
        f"/audits/{audit.id}/run",
        {"system_id": audit.system_id, "trigger": data.get("trigger") or "manual"},
    )
    outcome = "failed" if code is None else ("started" if code < 300 else f"http_{code}")
    logger.info(
        "audit_pipeline_start",
        "Audit pipeline start requested",
        audit_id=audit.id,
        outcome=outcome,
    )
    return outcome


#: Statuses an audit can be retried from (``open`` = never started or the start was lost).
RETRYABLE_STATUSES = frozenset({"failed", "open"})


async def retry_pipeline(audit: AuditTable) -> str:
    """Continue a failed audit's pipeline: the agents service's ``run`` re-runs the
    failed node from the kept checkpoint. 409 unless failed; 409 when the agents
    service says it is running or waiting at a gate; 502 when it is unreachable.
    The caller sets the audit ``running`` on success."""
    if audit.status not in RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Only a failed audit can be retried (it is {audit.status})."
        )
    code = await _post(
        f"/audits/{audit.id}/run",
        {"system_id": audit.system_id, "trigger": "retry"},
    )
    logger.info("audit_pipeline_retry", "Audit retry requested", audit_id=audit.id, code=code)
    if code is None:
        raise HTTPException(status_code=502, detail="The agents service is not reachable.")
    if code == 409:
        raise HTTPException(
            status_code=409, detail="The pipeline is already running or waiting at a gate."
        )
    if code >= 300:
        raise HTTPException(status_code=502, detail=f"The agents service answered {code}.")
    return "started"


def resume_body(audit: AuditTable, approval: ApprovalTable) -> dict[str, Any]:
    return {
        "system_id": audit.system_id,
        "gate": approval.gate,
        "decision": approval.decision,
        "reasonCategory": approval.reason_category,
        "comment": approval.comment,
        "edits": approval.edits or {},
        "artifactId": approval.artifact_id,
        "decidedBy": approval.decided_by,
    }


async def forward_gate_decision(audit: AuditTable, approval: ApprovalTable) -> str:
    """``resumed``, ``skipped`` (not a pipeline gate), ``http_<code>`` or ``failed``."""
    if approval.gate not in PIPELINE_GATES:
        return "skipped"
    url = f"{settings.upstream.agents_service_url.rstrip('/')}/audits/{audit.id}/resume"
    try:
        async with httpx.AsyncClient(
            timeout=settings.http.agents_timeout, transport=transport
        ) as client:
            response = await client.post(
                url, json=resume_body(audit, approval), headers=internal_headers()
            )
            # The gate may still be opening: retry a 409 a few times before giving up.
            for delay in RESUME_RETRY_DELAYS:
                if response.status_code != 409:
                    break
                await asyncio.sleep(delay)
                response = await client.post(
                    url, json=resume_body(audit, approval), headers=internal_headers()
                )
    except httpx.HTTPError as exc:
        logger.warning(
            "audit_resume_failed",
            "Pipeline resume failed",
            audit_id=audit.id,
            gate=approval.gate,
            error=type(exc).__name__,
        )
        return "failed"
    outcome = "resumed" if response.status_code < 300 else f"http_{response.status_code}"
    logger.info(
        "audit_resume_forwarded",
        "Gate decision forwarded to the pipeline",
        audit_id=audit.id,
        gate=approval.gate,
        outcome=outcome,
    )
    return outcome
