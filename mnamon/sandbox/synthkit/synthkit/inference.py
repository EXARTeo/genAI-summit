"""``synthkit run-inference``: call the model once and save the raw answers.

Save raw before analysing: this step only scores the generated dataset through the
plugin's target and writes what came back; it computes no metric. ``run-tests
--predictions`` (alias ``synthkit metrics``) then replays the file, so the numbers can
be recomputed, audited or re-judged without touching the model again.

Outputs in ``--out``:

* ``predictions.parquet``: one row per scored input. ``_row_id``, ``_test``,
  ``_variant`` (``original``, or ``perturbed:<test_id>`` for the seeded noisy copies a
  ``TT.robustness.perturbation`` plan test needs), ``score``, ``decision``, ``error``,
  and for edge rows (scored one at a time, raw, like ``t_edge_cases``) ``edge_outcome``
  + ``edge_detail``.
* ``run.json``: sha256 of the dataset and predictions, model reference and version,
  call stats, seed, the plan's ``audit_id`` / ``kb_version`` / ``obligation_id`` s, and
  the MLflow run id (one run ``inference`` in ``compliance/<SYS>``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from modelaccess.runlog import RunLogger

from synthkit.replay import ORIGINAL, PREDICTION_COLUMNS, file_sha256, perturbed_variant, row_keys
from synthkit.runtests import (
    Context,
    _output_contract,
    classify_edge,
    dataset_file,
    edge_columns,
    load_data,
    load_plan,
    perturbation_inputs,
)
from synthkit.spec import Dictionary, load_yaml
from synthkit.target import Target, TargetError

PERTURBATION = "TT.robustness.perturbation"
FAIL_FAST_ROWS = 3  # row-by-row fallback gives up when the first rows all fail


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _score_rows(target: Target, frame: pd.DataFrame) -> list[tuple[float, int | None, str | None]]:
    """Batch-score; if the batch fails, score row by row and keep each row's error.

    When nothing scores at all (model down), the first error is raised (exit 3)."""
    if frame.empty:
        return []
    try:
        scores, decisions = target.score(frame)
        return [(float(s), int(d), None) for s, d in zip(scores, decisions, strict=True)]
    except TargetError as first:
        out: list[tuple[float, int | None, str | None]] = []
        ok = 0
        for i in range(len(frame)):
            try:
                s, d = target.score(frame.iloc[[i]])
                out.append((float(s[0]), int(d[0]), None))
                ok += 1
            except TargetError as exc:
                if ok == 0 and i + 1 >= FAIL_FAST_ROWS:
                    raise first from exc
                out.append((float("nan"), None, f"{type(exc).__name__}: {exc}"[:300]))
        if ok == 0:
            raise first
        return out


def _records(
    frame: pd.DataFrame, variant: str, scored: list[tuple[float, int | None, str | None]]
) -> list[dict[str, Any]]:
    tests = frame["_test"] if "_test" in frame.columns else pd.Series("base", index=frame.index)
    return [
        {
            "_row_id": key,
            "_test": str(test),
            "_variant": variant,
            "score": score,
            "decision": decision,
            "error": error,
            "edge_outcome": None,
            "edge_detail": None,
        }
        for key, test, (score, decision, error) in zip(row_keys(frame), tests, scored, strict=True)
    ]


def run_inference(
    data_dir: Path,
    out_dir: Path,
    *,
    plugin_path: Path,
    target_factory: Callable[[], Target],
    plan_path: Path | None = None,
    dictionary_path: Path | None = None,
    run_logger: RunLogger | None = None,
    seed: int = 0,
) -> dict:
    """Score the dataset (and the plan's perturbed copies), save predictions + run.json."""
    started = _now()
    plugin = load_yaml(plugin_path) or {}
    plan = load_plan(plan_path) if plan_path else {"tests": []}
    base_dir = Path(plan_path).resolve().parent if plan_path else Path(data_dir)
    dict_path = dictionary_path or (
        base_dir / plan["dictionary"] if plan.get("dictionary") else None
    )
    dictionary = Dictionary.load(dict_path) if dict_path else None
    data, data_card = load_data(data_dir)
    data_path = dataset_file(Path(data_dir))
    system = plan.get("system") or plugin.get("system") or "unknown"
    obligation_ids = list(
        dict.fromkeys(t["obligation_id"] for t in plan["tests"] if t.get("obligation_id"))
    )
    ctx = Context(
        plan, plugin, {}, dictionary, data, data_card, base_dir, seed, target_factory, None
    )
    logger = run_logger or RunLogger(f"compliance/{system}")
    run_id = logger.start(
        "inference",
        {
            "system": system,
            "plugin": plugin.get("id"),
            "stage": "inference",
            "audit_id": plan.get("audit_id"),
            "kb_version": plan.get("kb_version"),
            "obligation_ids": ",".join(obligation_ids) or None,
            "dataset_id": data_card.get("dataset_id"),
            "dataset_sha256": file_sha256(data_path),
        },
    )
    status = "FAILED"
    try:
        target = ctx.target()
        edge_mask = (
            data["_test"] == "edge"
            if "_test" in data.columns
            else pd.Series(False, index=data.index)
        )
        regular = data[~edge_mask]
        records = _records(regular, ORIGINAL, _score_rows(target, regular))
        for test in plan["tests"]:
            if test["template"] != PERTURBATION:
                continue
            _, noisy, _, _ = perturbation_inputs(ctx, test)
            variant = perturbed_variant(test["id"])
            records += _records(noisy, variant, _score_rows(target, noisy))
        edges = data[edge_mask]
        if not edges.empty:
            contract = _output_contract(ctx)
            cols = edge_columns(target, edges)
            for key, (_, row) in zip(row_keys(edges), edges.iterrows(), strict=True):
                outcome, detail = classify_edge(target, row, cols, contract)
                records.append(
                    {
                        "_row_id": key,
                        "_test": "edge",
                        "_variant": ORIGINAL,
                        "score": float("nan"),
                        "decision": None,
                        "error": None,
                        "edge_outcome": outcome,
                        "edge_detail": detail,
                    }
                )
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame.from_records(records, columns=PREDICTION_COLUMNS)
        frame["score"] = frame["score"].astype(float)
        frame["decision"] = frame["decision"].astype("Int64")
        for col in ("_row_id", "_test", "_variant", "error", "edge_outcome", "edge_detail"):
            frame[col] = frame[col].astype("string")
        pred_path = out_dir / "predictions.parquet"
        frame.to_parquet(pred_path, index=False)
        run = {
            "dataset": {
                "file": str(data_path),
                "sha256": file_sha256(data_path),
                "dataset_id": data_card.get("dataset_id"),
                "content_sha256": data_card.get("content_sha256"),
                "n_rows": len(data),
            },
            "predictions": {
                "file": pred_path.name,
                "sha256": file_sha256(pred_path),
                "n_rows": len(frame),
                "variants": frame["_variant"].value_counts().to_dict(),
                "errors": int(frame["error"].notna().sum()),
            },
            "model": {
                "uri_or_url": target.name,
                "kind": target.kind,
                "version": target.metadata.get("version"),
                "input_columns": target.input_columns,
                "stats": target.stats(),
            },
            "system": system,
            "plugin": plugin.get("id"),
            "seed": seed,
            "audit_id": plan.get("audit_id"),
            "kb_version": plan.get("kb_version"),
            "obligation_ids": obligation_ids,
            "mlflow_run_id": run_id,
            "started_at": started,
            "finished_at": _now(),
        }
        run_path = out_dir / "run.json"
        run_path.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
        logger.set_tags({"predictions_sha256": run["predictions"]["sha256"]})
        logger.log_params(
            {"seed": seed, "target": target.name, "model_version": run["model"]["version"]}
        )
        logger.log_artifact(pred_path)
        logger.log_artifact(run_path)
        status = "FINISHED"
        return run
    finally:
        logger.end(status)
