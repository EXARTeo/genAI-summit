"""The risk-classification route (internal secret, called by the backend).

``POST /systems/{id}/classify``  one synchronous classification (≤ 120 s): 200 +
``ClassificationResult``; 502 when reg-memory or the model fails.

Thin: the logic is ``utils/classify_runs.py`` and ``classification/``.
"""

from typing import Annotated

from classification.schemas import ClassificationResult
from fastapi import APIRouter, Depends, Path

from core.security.internal_trust import require_internal_caller
from schema.audits import ID_PATTERN
from schema.classifications import ClassifyIn
from utils.classify_runs import classify_system

router = APIRouter(dependencies=[Depends(require_internal_caller)])


@router.post("/systems/{system_id}/classify", response_model=ClassificationResult)
async def classify(
    system_id: Annotated[str, Path(pattern=ID_PATTERN)], body: ClassifyIn
) -> ClassificationResult:
    """Pre-checks → classify_risk (Gemini) → verifier → Iris → dates; a proposal only."""
    return await classify_system(system_id, body)
