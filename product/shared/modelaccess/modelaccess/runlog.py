"""Log compliance test runs to the local MLflow tracking server.

One run per test in experiment ``compliance/<SYS>``. Artifacts go through the
tracking server (proxied artifact store, ``--serve-artifacts``), so the caller
needs only ``MLFLOW_TRACKING_URI``. When the server is not reachable the logger
is disabled and every call is a no-op, so tests and offline runs still work.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx


def tracking_reachable(uri: str | None, timeout: float = 3.0) -> bool:
    if not uri or not uri.startswith(("http://", "https://")):
        return False
    try:
        return httpx.get(uri.rstrip("/") + "/health", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


class RunLogger:
    """``with logger.run(name, tags) as run_id: logger.log_metrics(...)``."""

    def __init__(self, experiment: str, *, tracking_uri: str | None = None, enabled=None):
        self.tracking_uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "")
        self.experiment = experiment
        self.enabled = tracking_reachable(self.tracking_uri) if enabled is None else enabled
        self._mlflow = None
        if self.enabled:
            import mlflow  # noqa: PLC0415 - heavy, only when logging

            mlflow.set_tracking_uri(self.tracking_uri)
            mlflow.set_experiment(experiment)
            self._mlflow = mlflow

    def start(self, name: str, tags: dict[str, Any] | None = None) -> str | None:
        if not self._mlflow:
            return None
        run = self._mlflow.start_run(run_name=name)
        if tags:
            self._mlflow.set_tags({k: str(v) for k, v in tags.items() if v is not None})
        return run.info.run_id

    def log_params(self, params: dict[str, Any]) -> None:
        if self._mlflow and params:
            self._mlflow.log_params({k: str(v)[:500] for k, v in params.items()})

    def log_metrics(self, metrics: dict[str, float | None]) -> None:
        if self._mlflow:
            clean = {k: float(v) for k, v in metrics.items() if isinstance(v, int | float)}
            if clean:
                self._mlflow.log_metrics(clean)

    def log_json(self, name: str, payload: Any) -> None:
        if not self._mlflow:
            return
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            self._mlflow.log_artifact(str(path))

    def end(self, status: str = "FINISHED") -> None:
        if self._mlflow:
            self._mlflow.end_run(status=status)
