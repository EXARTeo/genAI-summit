"""The model registry: lazy, cached loading of the seed models from MLflow.

Each served model is a registered MLflow model with the alias ``champion``
(``models:/<name>@champion``). Nothing is loaded at startup: the first call to
a model loads it (in a worker thread) and caches it for the life of the
process. A failed load is not cached, so the next call retries; until MLflow
and the seed job are up, calls answer 503 instead of crashing the service.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from modelaccess.mlflow_models import InputColumn, load_mlflow_model
from starlette.concurrency import run_in_threadpool

from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)

#: The models this gateway serves (the seed job registers them).
CV_PARSER = "sys-001-cv-parser"
CV_RANKER = "sys-001-cv-ranker"
SERVED_MODELS: tuple[str, ...] = (
    CV_PARSER,
    CV_RANKER,
    "sys-002-credit-scorer",
    "sys-003-benefits-triage",
)


class ModelNotFoundError(Exception):
    """The name is not one of the served models (404)."""


class ModelUnavailableError(Exception):
    """A served model could not be loaded right now (503)."""


@dataclass(slots=True)
class LoadedModel:
    name: str
    version: str
    model: Any  # anything with .predict(pandas.DataFrame)
    # None when the model was logged without a signature (no validation then).
    input_columns: list[InputColumn] | None = field(default=None)


class ModelLoader(Protocol):
    def load(self, name: str) -> LoadedModel: ...


class MlflowModelLoader:
    """Loads ``models:/<name>@<alias>`` through the shared access layer (registry version
    resolved from the alias)."""

    def load(self, name: str) -> LoadedModel:
        alias = settings.mlflow.model_alias
        handle = load_mlflow_model(
            f"models:/{name}@{alias}", tracking_uri=settings.mlflow.tracking_uri
        )
        return LoadedModel(
            name=name,
            version=str(handle.version),
            model=handle.model,
            input_columns=handle.input_columns,
        )


class ModelRegistry:
    def __init__(self, loader: ModelLoader) -> None:
        self._loader = loader
        self._cache: dict[str, LoadedModel] = {}
        self._lock = threading.Lock()

    def set_loader(self, loader: ModelLoader) -> None:
        """Swap the loader and drop the cache (tests, or a forced reload)."""
        with self._lock:
            self._loader = loader
            self._cache.clear()

    def status(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "loaded": name in self._cache,
                "version": self._cache[name].version if name in self._cache else None,
            }
            for name in SERVED_MODELS
        }

    def _load_sync(self, name: str) -> LoadedModel:
        with self._lock:
            cached = self._cache.get(name)
            if cached is not None:
                return cached
            try:
                loaded = self._loader.load(name)
            except Exception as exc:
                logger.warning(
                    "model_load_failed",
                    "Model could not be loaded from MLflow",
                    model=name,
                    exception_type=exc.__class__.__name__,
                )
                raise ModelUnavailableError(
                    f"Model '{name}@{settings.mlflow.model_alias}' is not available yet: "
                    "MLflow is unreachable or the model is not registered "
                    "(run the seed job). Retry later."
                ) from exc
            self._cache[name] = loaded
            logger.info("model_loaded", "Model loaded", model=name, version=loaded.version)
            return loaded

    async def get(self, name: str) -> LoadedModel:
        if name not in SERVED_MODELS:
            raise ModelNotFoundError(f"Model '{name}' not found.")
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        return await run_in_threadpool(self._load_sync, name)


registry = ModelRegistry(MlflowModelLoader())
