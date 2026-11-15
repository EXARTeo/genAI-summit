"""Answer the test templates from saved predictions instead of the model.

``synthkit run-inference`` writes ``predictions.parquet`` (one row per scored input,
keyed by ``_row_id`` + ``_variant``) and ``run.json`` next to it. ``run-tests
--predictions`` (alias ``synthkit metrics``) swaps the live target for a
``ReplayTarget``: same interface the templates use (``score(frame)``, ``.metadata``,
``.input_columns``, ``.stats()``) plus ``edge(row_id)`` for the saved edge-case outcome.
A row that is not in the file raises ``TargetError``, so that test becomes an error row.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from synthkit.target import TargetError

ORIGINAL = "original"
PREDICTION_COLUMNS = [
    "_row_id",
    "_test",
    "_variant",
    "score",
    "decision",
    "error",
    "edge_outcome",
    "edge_detail",
]


def perturbed_variant(test_id: str) -> str:
    return f"perturbed:{test_id}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def row_keys(frame: pd.DataFrame) -> list[str]:
    """The replay key of each row: ``_row_id`` when the dataset has it, else the index."""
    ids = frame["_row_id"] if "_row_id" in frame.columns else frame.index
    return [str(v) for v in ids]


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA


class ReplayTarget:
    """A target that answers from ``predictions.parquet``; it never calls a model."""

    kind = "replay"

    def __init__(self, predictions: Path, run: dict | None = None) -> None:
        self.path = Path(predictions)
        self.sha256 = file_sha256(self.path)
        self.run = run or {}
        model = self.run.get("model") or {}
        self.name = f"replay:{self.path.name}"
        self.metadata: dict[str, Any] = {
            "version": model.get("version"),
            "replayed_from": str(self.path),
            "model": model.get("uri_or_url"),
        }
        self.input_columns = model.get("input_columns")
        self.input_types: dict[str, str] = {}
        self.output: dict = {}
        frame = pd.read_parquet(self.path)
        missing = [c for c in ("_row_id", "_variant", "score", "decision") if c not in frame]
        if missing:
            raise TargetError(f"{self.path.name} misses columns {missing}")
        self._rows: dict[tuple[str, str], tuple[float, int | None, str | None]] = {}
        self._edges: dict[str, tuple[str, str]] = {}
        for rec in frame.to_dict(orient="records"):
            key = str(rec["_row_id"])
            outcome = rec.get("edge_outcome")
            if rec.get("_test") == "edge" and not _missing(outcome):
                detail = rec.get("edge_detail")
                self._edges[key] = (str(outcome), "" if _missing(detail) else str(detail))
                continue
            error = rec.get("error")
            decision = rec.get("decision")
            self._rows[(key, str(rec["_variant"]))] = (
                float(rec["score"]) if not _missing(rec["score"]) else float("nan"),
                None if _missing(decision) else int(decision),
                None if _missing(error) else str(error),
            )
        self.lookups = 0

    def score(self, frame: pd.DataFrame, variant: str = ORIGINAL) -> tuple[np.ndarray, np.ndarray]:
        scores, decisions = [], []
        for key in row_keys(frame):
            hit = self._rows.get((key, variant))
            if hit is None:
                raise TargetError(f"no saved prediction for row {key!r} ({variant})")
            score, decision, error = hit
            if error is not None or decision is None:
                raise TargetError(f"row {key!r} ({variant}) failed at inference: {error}")
            scores.append(score)
            decisions.append(decision)
            self.lookups += 1
        return np.array(scores, dtype=float), np.array(decisions, dtype=int)

    def edge(self, row_id: str) -> tuple[str, str]:
        hit = self._edges.get(str(row_id))
        if hit is None:
            raise TargetError(f"no saved edge-case outcome for row {row_id!r}")
        self.lookups += 1
        return hit

    def stats(self) -> dict:
        return {
            "calls": 0,
            "rows": 0,
            "errors": 0,
            "replayed_lookups": self.lookups,
            "inference": (self.run.get("model") or {}).get("stats"),
        }


def load_run(predictions: Path) -> dict:
    """``run.json`` next to the predictions file, or ``{}``."""
    path = Path(predictions).parent / "run.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
