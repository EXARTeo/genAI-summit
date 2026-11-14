"""Put mnamon/mlflow-seed on sys.path and share small, cached case builds."""

import os
import sys
from functools import cache
from pathlib import Path

import pytest

SEED_DIR = Path(__file__).resolve().parents[2] / "mnamon" / "mlflow-seed"
CASES = SEED_DIR / "cases"
sys.path.insert(0, str(SEED_DIR))
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

from seedlib.systems import sys001, sys002, sys003  # noqa: E402

N_SMALL = {"SYS-001": 3000, "SYS-002": 3000, "SYS-003": 1500}
BUILDERS = {"SYS-001": sys001.build, "SYS-002": sys002.build, "SYS-003": sys003.build}


@cache
def built(system_id: str):
    return BUILDERS[system_id](CASES / system_id, n=N_SMALL[system_id])


@pytest.fixture
def cases_dir() -> Path:
    return CASES
