"""Shared fixtures for the sandbox suite (runner + synthkit).

No network: the model under test is a tiny local sklearn pipeline (pickled) or
an ``httpx.MockTransport``; the runner runs real subprocesses in temp dirs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cloudpickle
import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "product" / "sandbox"
SYNTHKIT_ROOT = SERVICE_ROOT / "synthkit"
for root in (SERVICE_ROOT, SYNTHKIT_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

# Settings are read at import time, so the environment is set before the app loads.
os.environ.setdefault("APP_ENV", "test")
os.environ["TRUSTED_PROXY_SECRET"] = "test-secret"  # noqa: S105
os.environ.setdefault("SANDBOX_MAX_OUTPUT_BYTES", "4096")
os.environ.setdefault("SANDBOX_MAX_DISK_BYTES", str(2 * 1024 * 1024))

from synthkit.sampler import Sampler  # noqa: E402
from synthkit.spec import Dictionary  # noqa: E402

from core.security.rate_limit import backend as rate_limit_backend  # noqa: E402
from main import app  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED_PLUGIN = REPO_ROOT / "product" / "mlflow-seed" / "cases" / "SYS-001" / "plugins" / "cv-ranker"
RANKER_FEATURES = [
    "postcode_region",
    "education_level",
    "years_experience",
    "career_gap_months",
    "skills_match",
    "languages",
]


def case_file(name: str) -> Path:
    """SYS-001 cv-ranker files from the seed case, or the test copy when absent."""
    seeded = SEED_PLUGIN / ("data" if name == "data-dictionary.yaml" else "") / name
    return seeded if seeded.exists() else FIXTURES / "sys001" / name


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    rate_limit_backend.reset()
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://runner") as c:
        yield c


@pytest.fixture
def case_dir(tmp_path: Path) -> Path:
    """A work dir holding the SYS-001 cv-ranker plugin.yaml + data-dictionary.yaml."""
    for name in ("plugin.yaml", "data-dictionary.yaml"):
        (tmp_path / name).write_bytes(case_file(name).read_bytes())
    return tmp_path


@pytest.fixture(scope="session")
def planted_model() -> Pipeline:
    """A tiny ranker with the SYS-001 planted issue: it never sees sex or
    nationality, but penalises athens_west (proxy for nationality) and career
    gaps (proxy for sex)."""
    sampler = Sampler(Dictionary.load(case_file("data-dictionary.yaml")))
    rng = np.random.default_rng(1)
    df = pd.DataFrame([sampler.valid_row(rng)[0] for _ in range(2000)])
    z = (
        0.25 * df.years_experience.clip(0, 15)
        + 4 * (df.skills_match - 0.55)
        - 0.05 * df.career_gap_months
        - 1.5 * (df.postcode_region == "athens_west")
        + 0.5 * df.education_level.isin(["master", "phd"])
        - 1.5
    )
    y = (rng.random(len(df)) < 1 / (1 + np.exp(-z))).astype(int)
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), ["postcode_region", "education_level"])],
        remainder="passthrough",
    )
    model = Pipeline([("pre", pre), ("lr", LogisticRegression(max_iter=1000))])
    return model.fit(df[RANKER_FEATURES], y)


@pytest.fixture
def model_pickle(tmp_path: Path, planted_model: Pipeline) -> Path:
    path = tmp_path / "model.pkl"
    path.write_bytes(cloudpickle.dumps(planted_model))
    return path
