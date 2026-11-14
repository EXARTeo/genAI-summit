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
recorded. Best effort: a pipeline that is not waiting (409) or not reachable
is logged, the approval stays recorded.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.database import ApprovalTable, AuditTable
from core.logging import get_logger
from core.settings import settings
from utils.agents import internal_headers

logger = get_logger(__name__)

PIPELINE_GATES = frozenset({"public_data", "scenarios", "datasets"})

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
