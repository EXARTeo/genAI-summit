"""Shared fixtures for the model-gateway suite.

No MLflow, no network: the registry's loader is swapped for ``FakeLoader``,
which serves small in-process models with MLflow-like signatures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# tests/model_gateway/ -> repo root -> mnamon/model-gateway (the service's import root).
SERVICE_ROOT = Path(__file__).resolve().parents[2] / "mnamon" / "model-gateway"
# The shared plugin access layer (installed in the image; on the path for a bare venv).
SHARED_ROOT = SERVICE_ROOT.parent / "shared" / "modelaccess"
for root in (SERVICE_ROOT, SHARED_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

TOKEN = "test-gateway-token"  # noqa: S105 - test-only token

# Settings are read at import time, so the environment is set before the app loads.
os.environ["APP_ENV"] = "test"
os.environ["MODEL_GATEWAY_TOKEN"] = TOKEN
os.environ["MODEL_GATEWAY_LATENCY_MS"] = "0"
os.environ["MODEL_GATEWAY_RATE_LIMIT_RPS"] = "5"

from core.security.rate_limit import backend as rate_limit_backend  # noqa: E402
from utils.models import InputColumn, LoadedModel, registry  # noqa: E402


class FakeParser:
    """Raw CV fields -> features (rule-based, like the seed parser)."""

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "years_experience": frame["years_experience"].astype(float),
                "has_degree": (frame["education"] != "none").astype(int),
            }
        )


class FakeRanker:
    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        proba = (frame["years_experience"] / 10).clip(0, 1) * 0.8 + frame["has_degree"] * 0.2
        return pd.DataFrame({"shortlist": (proba >= 0.5).astype(int), "proba": proba.round(3)})


class FakeScorer:
    def predict(self, frame: pd.DataFrame):
        return (frame["income"] / 100_000).clip(0, 1).to_numpy()


FAKE_MODELS: dict[str, LoadedModel] = {
    "sys-001-cv-parser": LoadedModel(
        "sys-001-cv-parser",
        "3",
        FakeParser(),
        [InputColumn("years_experience", "long"), InputColumn("education", "string")],
    ),
    "sys-001-cv-ranker": LoadedModel(
        "sys-001-cv-ranker",
        "7",
        FakeRanker(),
        [InputColumn("years_experience", "double"), InputColumn("has_degree", "long")],
    ),
    "sys-002-credit-scorer": LoadedModel(
        "sys-002-credit-scorer",
        "1",
        FakeScorer(),
        [InputColumn("income", "double"), InputColumn("age", "long", required=False)],
    ),
}


class FakeLoader:
    """Serves FAKE_MODELS; any other served name fails like a missing MLflow model."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def load(self, name: str) -> LoadedModel:
        self.calls.append(name)
        if name not in FAKE_MODELS:
            raise ConnectionError("mlflow unreachable")
        return FAKE_MODELS[name]


@pytest.fixture
def loader() -> FakeLoader:
    fake = FakeLoader()
    registry.set_loader(fake)
    return fake


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest_asyncio.fixture
async def api(loader: FakeLoader):
    from main import app

    rate_limit_backend.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
