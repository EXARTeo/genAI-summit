"""Reach the model under test, by the plugin's ``access.type``.

The plugin access layer is shared with run-tests and the model gateway
(``mnamon/shared/modelaccess``):

* ``mlflow_model``: ``modelaccess.mlflow_models.load_mlflow_model(access.uri)``
  (local MLflow over ``MLFLOW_TRACKING_URI``); signature, registry version and run
  lineage come from the registry.
* ``rest``: ``POST {"inputs": [rows]}`` through ``modelaccess.rest.RestClient``
  (``access.url``, a path joins ``MODEL_GATEWAY_URL``; bearer from the env var named
  by ``auth.secret_ref: env://NAME`` / ``auth.token_env``, default
  ``MODEL_GATEWAY_TOKEN``; ``limits.rps``/``max_requests``; 429 retried).
* ``pickle``: a cloudpickled estimator/callable file (tests, or a model handed in
  as a file). ``predict_proba`` wins over ``predict``.

Every adapter returns ``(scores, decisions)``: a float score per row and a 0/1
decision (from ``io.output.label_field`` when the model returns one, else
``score >= threshold``).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cloudpickle
import httpx
import numpy as np
import pandas as pd
from modelaccess.mlflow_models import load_mlflow_model
from modelaccess.plugin import AccessError, access_config, resolve_url
from modelaccess.rest import EndpointError, RestClient


class TargetError(RuntimeError):
    """The model could not be reached or answered with something unreadable."""


class TargetRejected(TargetError):
    """The endpoint refused the input with a 4xx (a graceful rejection, not a crash)."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def rows_for_json(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{k: _jsonable(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def decisions_from_labels(labels: pd.Series, output: dict) -> np.ndarray:
    """0/1 decisions from a label column: numeric as is, text against ``positive_label``
    (e.g. ``decision: approve|decline`` with ``positive_label: approve``)."""
    if pd.api.types.is_numeric_dtype(labels) or pd.api.types.is_bool_dtype(labels):
        return labels.to_numpy(dtype=float).astype(int)
    positive = str(output.get("positive_label", "1"))
    return (labels.astype(str) == positive).to_numpy().astype(int)


class Target:
    def __init__(
        self,
        name: str,
        kind: str,
        predict: Callable[[pd.DataFrame], Any],
        *,
        input_columns: list[str] | None = None,
        input_types: dict[str, str] | None = None,
        output: dict | None = None,
        batch_size: int = 500,
    ) -> None:
        self.name = name
        self.kind = kind
        self._predict = predict
        self.predict_raw: Callable[[pd.DataFrame], Any] = predict
        self.metadata: dict[str, Any] = {}
        self.input_columns = input_columns
        self.input_types = input_types or {}
        self.output = output or {}
        self.threshold = float(self.output.get("threshold", 0.5))
        self.batch_size = batch_size
        self.calls = 0
        self.rows = 0
        self.errors = 0
        self.latencies_ms: list[float] = []

    def _normalise(self, out: Any, n: int) -> tuple[np.ndarray, np.ndarray]:
        score_field = self.output.get("score_field", "proba")
        label_field = self.output.get("label_field")
        if isinstance(out, list) and out and isinstance(out[0], dict):
            out = pd.DataFrame(out)
        if isinstance(out, pd.DataFrame):
            if score_field in out.columns:
                scores = out[score_field].to_numpy(dtype=float)
            else:
                numeric = out.select_dtypes("number")
                if numeric.empty:
                    raise TargetError("model output has no numeric column")
                scores = numeric.iloc[:, -1].to_numpy(dtype=float)
            if label_field and label_field in out.columns:
                return scores, decisions_from_labels(out[label_field], self.output)
            return scores, (scores >= self.threshold).astype(int)
        if isinstance(out, pd.Series):
            out = out.to_numpy()
        arr = np.asarray(out, dtype=float)
        if arr.ndim == 2:
            arr = arr[:, -1]
        if arr.shape[0] != n:
            raise TargetError(f"model returned {arr.shape[0]} predictions for {n} rows")
        return arr, (arr >= self.threshold).astype(int)

    def score(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        if self.input_columns:
            missing = [c for c in self.input_columns if c not in frame.columns]
            if missing:
                raise TargetError(f"rows miss model inputs: {missing}")
            frame = frame[self.input_columns]
        scores, decisions = [], []
        for start in range(0, len(frame), self.batch_size):
            chunk = frame.iloc[start : start + self.batch_size].reset_index(drop=True)
            began = time.perf_counter()
            try:
                out = self._predict(chunk)
            except TargetError:
                self.errors += 1
                raise
            except Exception as exc:  # noqa: BLE001 - any model failure is a target error
                self.errors += 1
                raise TargetError(f"{type(exc).__name__}: {exc}") from exc
            self.latencies_ms.append((time.perf_counter() - began) * 1000)
            self.calls += 1
            self.rows += len(chunk)
            s, d = self._normalise(out, len(chunk))
            scores.append(s)
            decisions.append(d)
        if not scores:
            return np.array([]), np.array([], dtype=int)
        return np.concatenate(scores), np.concatenate(decisions)

    def stats(self) -> dict:
        lat = np.array(self.latencies_ms) if self.latencies_ms else np.array([0.0])
        return {
            "calls": self.calls,
            "rows": self.rows,
            "errors": self.errors,
            "latency_ms_per_call": {
                "p50": round(float(np.percentile(lat, 50)), 2),
                "p95": round(float(np.percentile(lat, 95)), 2),
                "max": round(float(lat.max()), 2),
            },
        }


def _cast_for_signature(frame: pd.DataFrame, types: dict[str, str]) -> pd.DataFrame:
    frame = frame.copy()
    for col, t in types.items():
        if col not in frame.columns:
            continue
        if t in ("long", "integer"):
            frame[col] = pd.to_numeric(frame[col]).fillna(0).astype("int64")
        elif t in ("double", "float"):
            frame[col] = pd.to_numeric(frame[col]).astype(float)
        elif t == "string":
            frame[col] = frame[col].astype(str)
    return frame


def mlflow_target(uri: str, output: dict) -> Target:
    handle = load_mlflow_model(uri)
    columns = [c.name for c in handle.input_columns] if handle.input_columns else None
    types = handle.input_types

    def predict(chunk: pd.DataFrame) -> Any:
        return handle.predict(_cast_for_signature(chunk, types))

    def predict_raw(chunk: pd.DataFrame) -> Any:
        # No casting: edge-case rows go in as they are (null stays null).
        return handle.predict(chunk)

    target = Target(
        uri, "mlflow_model", predict, input_columns=columns, input_types=types, output=output
    )
    target.predict_raw = predict_raw
    target.metadata = {"name": handle.name, "version": handle.version, **handle.metadata}
    return target


def rest_target(
    access: dict,
    output: dict,
    *,
    url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Target:
    try:
        config = access_config({"access": access}, override_type="rest")
        client = RestClient(config, url=resolve_url(url) if url else None, transport=transport)
    except (AccessError, EndpointError) as exc:
        raise TargetError(str(exc)) from exc

    def predict(chunk: pd.DataFrame) -> Any:
        try:
            resp = client.post({"inputs": rows_for_json(chunk)})
        except EndpointError as exc:
            raise TargetError(str(exc)) from exc
        if 400 <= resp.status_code < 500:
            raise TargetRejected(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code != 200:
            raise TargetError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        return body.get("predictions", body) if isinstance(body, dict) else body

    target = Target(client.url, "rest", predict, output=output, batch_size=config.batch_size)
    target.predict_raw = predict
    return target


def pickle_target(path: Path, output: dict, input_columns: list[str] | None = None) -> Target:
    with Path(path).open("rb") as fh:
        model = cloudpickle.load(fh)
    columns = input_columns or (
        list(model.feature_names_in_) if hasattr(model, "feature_names_in_") else None
    )

    def predict(chunk: pd.DataFrame) -> Any:
        if hasattr(model, "predict_proba"):
            return model.predict_proba(chunk)[:, 1]
        if hasattr(model, "predict"):
            return model.predict(chunk)
        return model(chunk)

    target = Target(str(path), "pickle", predict, input_columns=columns, output=output)
    target.predict_raw = model.predict if hasattr(model, "predict") else model
    return target


def load_target(
    plugin: dict,
    *,
    model_uri: str | None = None,
    model_pickle: Path | None = None,
    url: str | None = None,
    input_columns: list[str] | None = None,
) -> Target:
    access = plugin.get("access") or {}
    output = (plugin.get("io") or {}).get("output") or {}
    if model_pickle:
        return pickle_target(model_pickle, output, input_columns)
    kind = "rest" if url else access.get("type")
    if kind == "mlflow_model":
        return mlflow_target(model_uri or access.get("uri", ""), output)
    if kind == "rest":
        return rest_target(access, output, url=url)
    if kind == "pickle":
        return pickle_target(Path(access.get("uri", "")), output, input_columns)
    raise TargetError(
        f"access.type {kind!r} is not supported here (mlflow_model, rest, pickle; "
        "llm_chat targets are tested by run-tests' chat probes)"
    )
