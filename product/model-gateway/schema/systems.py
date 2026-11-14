from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScreenRequest(BaseModel):
    """Raw CV fields, one object per applicant (the parser's input)."""

    model_config = ConfigDict(extra="forbid")

    inputs: list[dict[str, Any]] = Field(min_length=1)


class StageInfo(BaseModel):
    model: str
    version: str


class ScreenResponse(BaseModel):
    system: str
    # The ranker's output per applicant (shortlist + proba).
    predictions: list[Any]
    # The parser's output, i.e. the ranker's input: lets a caller test a stage alone.
    features: list[dict[str, Any]]
    stages: list[StageInfo]
