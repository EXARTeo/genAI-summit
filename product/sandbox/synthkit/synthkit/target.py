"""Reach the model under test, by the plugin's ``access.type``.

* ``mlflow_model``: ``mlflow.pyfunc.load_model(access.uri)`` (MLflow over
  ``MLFLOW_TRACKING_URI``); the input signature comes from the model metadata.
* ``rest``: ``POST {"inputs": [rows]}`` to ``access.url`` (a path is joined to
  ``MODEL_GATEWAY_URL``) with ``Authorization: Bearer $MODEL_GATEWAY_TOKEN`` (or the
  env var named by ``access.auth.token_env``); ``access.limits.rps`` and
  ``max_requests`` are respected, 429 is retried after ``Retry-After``.
* ``pickle``: a cloudpickled estimator/callable file (tests, or a model handed in
  as a file). ``predict_proba`` wins over ``predict``.

Every adapter returns ``(scores, decisions)``: a float score per row and a 0/1
decision (from ``io.output.label_field`` when the model returns one, else
``score >= threshold``).
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cloudpickle
import httpx
import numpy as np
import pandas as pd


class TargetError(RuntimeError):
    """The model could not be reached or answered with something unreadable."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def rows_for_json(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{k: _jsonable(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


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
                return scores, out[label_field].to_numpy(dtype=float).astype(int)
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
    # Imported here: mlflow is heavy and only this adapter needs it.
    import mlflow.pyfunc  # noqa: PLC0415

    model = mlflow.pyfunc.load_model(uri)
    columns, types = None, {}
    schema = model.metadata.get_input_schema() if model.metadata else None
    if schema is not None and schema.has_input_names():
        columns = schema.input_names()
        types = {c.name: str(c.type).split(".")[-1].lower() for c in schema.inputs}

    def predict(chunk: pd.DataFrame) -> Any:
        return model.predict(_cast_for_signature(chunk, types))

    return Target(
        uri, "mlflow_model", predict, input_columns=columns, input_types=types, output=output
    )


def rest_target(
    access: dict,
    output: dict,
    *,
    url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Target:
    target_url = url or access.get("url") or ""
    if target_url.startswith("/"):
        base = os.environ.get("MODEL_GATEWAY_URL", "http://model-gateway:8000")
        target_url = base.rstrip("/") + target_url
    if not target_url:
        raise TargetError("rest access needs access.url")
    token_env = (access.get("auth") or {}).get("token_env", "MODEL_GATEWAY_TOKEN")
    token = os.environ.get(token_env, "")
    limits = access.get("limits") or {}
    rps = float(limits.get("rps") or 0)
    max_requests = int(limits.get("max_requests") or 0)
    timeout = float(limits.get("timeout_s") or 30)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    client = httpx.Client(timeout=timeout, transport=transport)
    state = {"last": 0.0, "sent": 0}

    def predict(chunk: pd.DataFrame) -> Any:
        for _attempt in range(4):
            if max_requests and state["sent"] >= max_requests:
                raise TargetError(f"max_requests ({max_requests}) reached")
            if rps > 0:
                wait = state["last"] + 1.0 / rps - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            state["last"] = time.monotonic()
            state["sent"] += 1
            resp = client.post(target_url, json={"inputs": rows_for_json(chunk)}, headers=headers)
            if resp.status_code == 429:
                time.sleep(min(float(resp.headers.get("Retry-After", "1")), 30.0))
                continue
            if resp.status_code != 200:
                raise TargetError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            body = resp.json()
            return body.get("predictions", body) if isinstance(body, dict) else body
        raise TargetError("rate limited (429) after retries")

    return Target(
        target_url, "rest", predict, output=output, batch_size=int(access.get("batch_size", 100))
    )


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

    return Target(str(path), "pickle", predict, input_columns=columns, output=output)


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
    raise TargetError(f"access.type {kind!r} is not supported by synthkit (mlflow_model, rest)")
