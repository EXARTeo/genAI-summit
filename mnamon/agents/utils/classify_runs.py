"""``POST /systems/{id}/classify``: one synchronous risk classification (plan 02 §7.4).

The backend awaits it inside its background task (like the change judge). This
module wires the dependencies, opens the run's own Langfuse trace
(``classify:<id>``, kind ``classification``; never an audit trace) and maps
failures to 502: reg-memory down, the Gemini step failing twice, or the
deadline passing.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import uuid4

from classification.agent import (
    ClassifierStep,
    ClassifyRequest,
    KbUnavailable,
    Tracing,
    classify,
)
from classification.schemas import ClassificationResult
from fastapi import HTTPException, status
from pipeline.clients import PipelineHTTPError, RegMemory
from pipeline.decision import IrisClient

from core.logging import get_logger
from harness.observability import end_span, start_span, trace_run_config
from schema.classifications import ClassifyIn

logger = get_logger(__name__)

#: Under the backend's CLASSIFY_TIMEOUT_S (120 s), so the answer is ours, not a cut socket.
DEADLINE_SECONDS = 110.0
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


def _trace_id(trace: dict[str, Any] | None) -> str:
    given = str((trace or {}).get("trace_id") or "").lower()
    return given if _TRACE_ID.match(given) else uuid4().hex


async def classify_system(
    system_id: str,
    body: ClassifyIn,
    *,
    regmem: RegMemory | None = None,
    step: ClassifierStep | None = None,
    iris: IrisClient | None = None,
) -> ClassificationResult:
    trace_id = _trace_id(body.trace)
    name = str((body.trace or {}).get("name") or f"classify:{body.classification_id}")
    root = start_span(
        name,
        trace_id=trace_id,
        input={"classification_id": body.classification_id, "system_id": system_id},
        metadata={"kind": "classification", "system": system_id},
    )
    root_id = getattr(root, "id", None)
    step_config = trace_run_config(
        {},
        kind="classification",
        name=name,
        trace={"trace_id": trace_id, "parent_observation_id": root_id},
        tags=["classification", f"system:{system_id}"],
    )
    request = ClassifyRequest(
        classification_id=body.classification_id,
        system_id=system_id,
        card=dict(body.card),
        documents=[d.model_dump() for d in body.documents],
        kb_version=body.kb_version,
        feedback=body.feedback.model_dump() if body.feedback else None,
    )
    try:
        result = await asyncio.wait_for(
            classify(
                request,
                regmem=regmem or RegMemory(),
                step=step,
                iris=iris if iris is not None else IrisClient(),
                tracing=Tracing(trace_id=trace_id, root_id=root_id, step_config=step_config),
            ),
            timeout=DEADLINE_SECONDS,
        )
    except (KbUnavailable, PipelineHTTPError) as exc:
        end_span(root, output={"error": "reg-memory unavailable"}, level="ERROR")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=KbUnavailable.public_message
        ) from exc
    except TimeoutError as exc:
        end_span(root, output={"error": "deadline"}, level="ERROR")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The classifier ran out of time; retry."
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "classification_failed",
            "Risk classification failed",
            classification_id=body.classification_id,
            failure_reason=type(exc).__name__,
        )
        end_span(root, output={"error": type(exc).__name__}, level="ERROR")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The classifier failed; it can be retried."
        ) from exc
    end_span(
        root,
        output={
            "risk_class": result.risk_class,
            "route": result.route,
            "needs_human": result.needs_human,
            "agreement": result.agreement,
        },
    )
    return result


__all__ = ["DEADLINE_SECONDS", "classify_system"]
