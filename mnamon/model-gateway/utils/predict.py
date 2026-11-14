"""Predictions: validate rows against the model signature, run the model, serialise.

Validation is strict, like a production API: a row with a missing required
field, an unknown field or a value of the wrong type is a 422 that says which
row and field, before the model ever sees it.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException, status
from mlflow.exceptions import MlflowException
from starlette.concurrency import run_in_threadpool

from core.logging import get_logger
from core.settings import settings
from utils.models import (
    CV_PARSER,
    CV_RANKER,
    LoadedModel,
    ModelNotFoundError,
    ModelUnavailableError,
    registry,
)

logger = get_logger(__name__)

_INT_TYPES = frozenset({"long", "integer"})
_FLOAT_TYPES = frozenset({"double", "float"})
_MAX_ERRORS = 50


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name in _INT_TYPES:
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name in _FLOAT_TYPES:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    return True  # datetime, binary, ...: left to the model


def validate_rows(model: LoadedModel, rows: list[dict[str, Any]]) -> None:
    """Raise 422 listing every bad row/field (up to a cap)."""
    if len(rows) > settings.app.max_rows:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Too many rows: at most {settings.app.max_rows} per call.",
        )
    if model.input_columns is None:
        return
    columns = {col.name: col for col in model.input_columns}
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        for col in model.input_columns:
            value = row.get(col.name)
            if value is None:
                if col.required:
                    errors.append({"row": index, "field": col.name, "error": "missing"})
            elif not _type_ok(value, col.type):
                errors.append({"row": index, "field": col.name, "error": f"expected {col.type}"})
        errors.extend(
            {"row": index, "field": key, "error": "unknown field"}
            for key in row
            if key not in columns
        )
        if len(errors) >= _MAX_ERRORS:
            break
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": f"Input does not match the signature of '{model.name}'.",
                "expected": [
                    {"name": c.name, "type": c.type, "required": c.required}
                    for c in model.input_columns
                ],
                "errors": errors[:_MAX_ERRORS],
            },
        )


def _to_jsonable(output: Any) -> list[Any]:
    if isinstance(output, pd.DataFrame):
        return json.loads(output.to_json(orient="records"))
    if isinstance(output, pd.Series):
        return json.loads(output.to_json(orient="values"))
    if isinstance(output, np.ndarray):
        return json.loads(pd.Series(list(output)).to_json(orient="values"))
    if isinstance(output, list):
        return json.loads(json.dumps(output, default=str))
    return [output]


def _frame(model: LoadedModel, rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(rows)
    if model.input_columns is not None:
        frame = frame.reindex(columns=[c.name for c in model.input_columns])
    return frame


async def _run(model: LoadedModel, frame: pd.DataFrame) -> list[Any]:
    try:
        output = await run_in_threadpool(model.model.predict, frame)
    except (MlflowException, ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "model_rejected_input",
            "Model raised on the input",
            model=model.name,
            exception_type=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Model '{model.name}' rejected the input.",
        ) from exc
    return _to_jsonable(output)


async def load_or_raise(name: str) -> LoadedModel:
    try:
        return await registry.get(name)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "10"},
        ) from exc


async def predict(name: str, rows: list[dict[str, Any]]) -> tuple[LoadedModel, list[Any]]:
    model = await load_or_raise(name)
    validate_rows(model, rows)
    predictions = await _run(model, _frame(model, rows))
    logger.info(
        "model_predicted", "Prediction served", model=name, version=model.version, rows=len(rows)
    )
    return model, predictions


async def screen_sys001(
    rows: list[dict[str, Any]],
) -> tuple[list[LoadedModel], list[dict[str, Any]], list[Any]]:
    """SYS-001 pipeline: raw CV fields -> parser -> features -> ranker -> shortlist."""
    parser = await load_or_raise(CV_PARSER)
    ranker = await load_or_raise(CV_RANKER)
    validate_rows(parser, rows)
    features = await _run(parser, _frame(parser, rows))
    feature_rows = [f if isinstance(f, dict) else {"value": f} for f in features]
    # The ranker sees only the features in its own signature.
    predictions = await _run(ranker, _frame(ranker, feature_rows))
    logger.info(
        "pipeline_screened",
        "SYS-001 pipeline served",
        rows=len(rows),
        parser_version=parser.version,
        ranker_version=ranker.version,
    )
    return [parser, ranker], feature_rows, predictions
