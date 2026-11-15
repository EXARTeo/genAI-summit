"""Risk-classification DTOs: ``POST /systems/{id}/classify`` (plan 02 §7.4).

The response is ``classification.schemas.ClassificationResult`` (plan 02 §8.2).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schema.audits import ID_PATTERN


class ClassifyDocument(BaseModel):
    """One readable dossier file the backend sends (its text, already truncated)."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(..., max_length=512)
    version: int | None = None
    text: str = Field("", max_length=200_000)


class ClassifyFeedback(BaseModel):
    """``source: human`` = the previous run's rejection reason; anything else is context."""

    model_config = ConfigDict(extra="ignore")

    source: str = Field("human", max_length=32)
    reason: str = Field("", max_length=4_000)


class ClassifyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    classification_id: str = Field(..., pattern=ID_PATTERN)
    kb_version: str | None = Field(None, max_length=64)
    card: dict[str, Any] = Field(default_factory=dict)
    documents: list[ClassifyDocument] = Field(default_factory=list, max_length=100)
    feedback: ClassifyFeedback | None = None
    trace: dict[str, Any] | None = None


__all__ = ["ClassifyDocument", "ClassifyFeedback", "ClassifyIn"]
