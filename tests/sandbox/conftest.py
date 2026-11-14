"""Shared fixtures for the sandbox suite. No network: models are local sklearn
pipelines or plain callables; the runner runs real subprocesses in temp dirs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "product" / "sandbox"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

os.environ.setdefault("APP_ENV", "test")
os.environ["TRUSTED_PROXY_SECRET"] = "test-secret"  # noqa: S105
os.environ.setdefault("SANDBOX_MAX_OUTPUT_BYTES", "4096")
os.environ.setdefault("SANDBOX_MAX_DISK_BYTES", str(2 * 1024 * 1024))

from core.security.rate_limit import backend as rate_limit_backend  # noqa: E402
from main import app  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED_PLUGIN = REPO_ROOT / "product" / "mlflow-seed" / "cases" / "SYS-001" / "plugins" / "cv-ranker"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    rate_limit_backend.reset()
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://runner") as c:
        yield c


@pytest.fixture
def dictionary_path() -> Path:
    """The SYS-001 cv-ranker dictionary from the seed case, or the test copy."""
    seeded = SEED_PLUGIN / "data" / "data-dictionary.yaml"
    return seeded if seeded.exists() else FIXTURES / "sys001" / "data-dictionary.yaml"
