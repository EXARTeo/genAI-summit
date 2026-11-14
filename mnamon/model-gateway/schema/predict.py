from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PredictRequest(BaseModel):
    """MLflow-serving style body: one object per row."""

    model_config = ConfigDict(extra="forbid")

    inputs: list[dict[str, Any]] = Field(min_length=1)


class PredictResponse(BaseModel):
    predictions: list[Any]
    model: str
    version: str
