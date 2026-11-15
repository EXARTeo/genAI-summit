"""synthkit run-inference (save raw predictions) and run-tests --predictions (replay).

The model is the planted pickle ranker; replay runs get a target factory that raises,
so any model call would fail the test. MLflow is off or faked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from conftest import case_file
from modelaccess.runlog import RunLogger
from synthkit.cli import main
from synthkit.generate import generate
from synthkit.inference import run_inference
from synthkit.replay import file_sha256
from synthkit.runtests import run_tests
from synthkit.spec import load_spec
from synthkit.target import TargetError, pickle_target
from test_synthkit_runtests import ALL_MODEL_TESTS, CARD, SPEC

TESTS = [{**t, "obligation_id": f"OBL.{t['id']}"} for t in ALL_MODEL_TESTS]


def _write(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def case(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("inf")
    for name in ("plugin.yaml", "data-dictionary.yaml"):
        (root / name).write_bytes(case_file(name).read_bytes())
    _write(root / "generation-spec.yaml", SPEC)
    _write(root / "system-card.yaml", CARD)
    generate(load_spec(root / "generation-spec.yaml"), 3, root / "data")
    _write(
        root / "plan.yaml",
        {
            "system": "SYS-001",
            "audit_id": "SYS-001-20261115-1200",
            "card": "system-card.yaml",
            "dictionary": "data-dictionary.yaml",
            "kb_version": "kb-1",
            "tests": TESTS,
        },
    )
    return root


def _off() -> RunLogger:
    return RunLogger("compliance/test", enabled=False)


def _factory(case: Path, model_pickle: Path):
    output = yaml.safe_load((case / "plugin.yaml").read_text(encoding="utf-8"))["io"]["output"]
    return lambda: pickle_target(model_pickle, output)


def _no_model():
    raise AssertionError("replay must not call the model")


class ArtifactLogger(RunLogger):
    def __init__(self) -> None:
        super().__init__("compliance/SYS-001", enabled=False)
        self.enabled = True
        self.runs: list[dict] = []

    def start(self, name, tags=None):
        self.runs.append({"name": name, "tags": dict(tags or {}), "artifacts": [], "status": None})
        return f"run-{len(self.runs)}"

    def set_tags(self, tags):
        self.runs[-1]["tags"].update(tags)

    def log_artifact(self, path):
        self.runs[-1]["artifacts"].append(Path(path).name)

    def log_json(self, name, payload):
        self.runs[-1]["artifacts"].append(name)

    def end(self, status="FINISHED"):
        self.runs[-1]["status"] = status


@pytest.fixture
def inferred(case, model_pickle, tmp_path) -> tuple[Path, dict, ArtifactLogger]:
    logger = ArtifactLogger()
    run = run_inference(
        case / "data",
        tmp_path / "inference",
        plugin_path=case / "plugin.yaml",
        plan_path=case / "plan.yaml",
        target_factory=_factory(case, model_pickle),
        run_logger=logger,
        seed=1,
    )
    return tmp_path / "inference", run, logger


def test_run_inference_saves_raw_predictions(case, inferred):
    out, run, logger = inferred
    preds = pd.read_parquet(out / "predictions.parquet")
    data = pd.read_parquet(case / "data" / "dataset.parquet")
    saved = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert saved == json.loads(json.dumps(run, default=str))
    assert saved["predictions"]["sha256"] == file_sha256(out / "predictions.parquet")
    assert saved["dataset"]["sha256"] == file_sha256(case / "data" / "dataset.parquet")
    assert saved["dataset"]["n_rows"] == len(data)
    assert saved["dataset"]["content_sha256"] and saved["dataset"]["dataset_id"]
    assert saved["predictions"]["n_rows"] == len(preds)
    assert saved["model"]["kind"] == "pickle" and saved["model"]["stats"]["calls"] > 0
    assert saved["audit_id"] == "SYS-001-20261115-1200" and saved["kb_version"] == "kb-1"
    assert saved["obligation_ids"] == [f"OBL.{t['id']}" for t in ALL_MODEL_TESTS]
    assert saved["mlflow_run_id"] == "run-1" and saved["seed"] == 1
    # No metrics: inference only records what the model said.
    assert not {"results", "summary", "metrics"} & set(saved)
    assert list(preds.columns) == [
        "_row_id",
        "_test",
        "_variant",
        "score",
        "decision",
        "error",
        "edge_outcome",
        "edge_detail",
    ]
    variants = preds["_variant"].value_counts().to_dict()
    n_edge = int((data["_test"] == "edge").sum())
    assert variants == {"original": len(data), "perturbed:P": 200}
    edges = preds[preds["_test"] == "edge"]
    assert len(edges) == n_edge and edges["edge_outcome"].notna().all()
    assert edges["score"].isna().all()
    regular = preds[preds["_test"] != "edge"]
    assert regular["score"].between(0, 1).all() and regular["error"].isna().all()
    assert set(regular["decision"].unique()) <= {0, 1}
    (mlrun,) = logger.runs
    assert mlrun["name"] == "inference" and mlrun["status"] == "FINISHED"
    assert mlrun["artifacts"] == ["predictions.parquet", "run.json"]
    tags = mlrun["tags"]
    assert tags["stage"] == "inference" and tags["audit_id"] == "SYS-001-20261115-1200"
    assert tags["obligation_ids"] == ",".join(saved["obligation_ids"])
    assert tags["dataset_sha256"] == saved["dataset"]["sha256"]
    assert tags["predictions_sha256"] == saved["predictions"]["sha256"]


def _comparable(report: dict) -> list[tuple]:
    return [
        (r["id"], r["value"], r["ci95"], r["status"], json.dumps(r["details"], default=str))
        for r in report["results"]
    ]


def test_replay_matches_a_live_run_without_calling_the_model(
    case, model_pickle, inferred, tmp_path
):
    out, run, _ = inferred
    live = run_tests(
        case / "plan.yaml",
        case / "plugin.yaml",
        case / "data",
        tmp_path / "live",
        target_factory=_factory(case, model_pickle),
        run_logger=_off(),
        seed=1,
    )
    logger = ArtifactLogger()
    replay = run_tests(
        case / "plan.yaml",
        case / "plugin.yaml",
        case / "data",
        tmp_path / "replay",
        target_factory=_no_model,
        run_logger=logger,
        seed=1,
        predictions_path=out / "predictions.parquet",
    )
    assert live["summary"]["error"] == 0
    assert _comparable(replay) == _comparable(live)
    sha = run["predictions"]["sha256"]
    assert replay["predictions_sha256"] == sha
    assert replay["inference"]["predictions_sha256"] == sha
    assert replay["inference"]["dataset_sha256"] == run["dataset"]["sha256"]
    assert {r["predictions_sha256"] for r in replay["results"]} == {sha}
    assert replay["audit_id"] == "SYS-001-20261115-1200"
    assert replay["results"][0]["obligation_id"] == "OBL.G"
    tags = logger.runs[0]["tags"]
    assert tags["obligation_id"] == "OBL.G" and tags["predictions_sha256"] == sha
    assert tags["audit_id"] == "SYS-001-20261115-1200" and tags["kb_version"] == "kb-1"
    assert "predictions_sha256" not in live and "inference" not in live


def test_missing_prediction_is_an_error_row(case, inferred, tmp_path):
    out, _, _ = inferred
    preds = pd.read_parquet(out / "predictions.parquet")
    partial = tmp_path / "partial"
    partial.mkdir()
    # drop one base row; no run.json next to it, so no sha cross-check applies
    base_ids = preds.loc[preds["_test"] == "base", "_row_id"]
    preds[preds["_row_id"] != base_ids.iloc[0]].to_parquet(partial / "predictions.parquet")
    report = run_tests(
        case / "plan.yaml",
        case / "plugin.yaml",
        case / "data",
        tmp_path / "res",
        target_factory=_no_model,
        run_logger=_off(),
        seed=1,
        predictions_path=partial / "predictions.parquet",
    )
    by_test = {}
    for r in report["results"]:
        by_test.setdefault(r["test_id"], []).append(r)
    (group,) = by_test["G"]
    assert group["status"] == "error" and "no saved prediction" in group["details"]["error"]
    assert all(r["status"] != "error" for r in by_test["E"])  # edge rows still there


def test_eval_set_accuracy_cannot_replay(case, inferred, tmp_path):
    out, _, _ = inferred
    pd.DataFrame({"x": [0.1, 0.9], "label": [0, 1]}).to_csv(case / "eval.csv", index=False)
    plan = _write(
        case / "plan-eval.yaml",
        {
            "system": "SYS-001",
            "tests": [{"id": "A", "template": "TT.accuracy.subgroup", "eval_set": "eval.csv"}],
        },
    )
    report = run_tests(
        plan,
        case / "plugin.yaml",
        case / "data",
        tmp_path / "res",
        target_factory=_no_model,
        run_logger=_off(),
        predictions_path=out / "predictions.parquet",
    )
    (row,) = report["results"]
    assert row["status"] == "error" and "cannot be replayed" in row["details"]["error"]


def test_replay_refuses_a_changed_predictions_file(case, inferred, tmp_path):
    out, _, _ = inferred
    preds = pd.read_parquet(out / "predictions.parquet")
    preds.iloc[:-1].to_parquet(out / "predictions.parquet")  # run.json still has the old sha
    code = main(
        [
            "metrics",
            "--plan",
            str(case / "plan.yaml"),
            "--target",
            str(case / "plugin.yaml"),
            "--data",
            str(case / "data"),
            "--predictions",
            str(out / "predictions.parquet"),
            "--no-mlflow",
            "--out",
            str(tmp_path / "res"),
        ]
    )
    assert code == 2


def test_cli_run_inference_then_metrics(case, model_pickle, tmp_path, capsys):
    common = ["--target", str(case / "plugin.yaml"), "--data", str(case / "data"), "--no-mlflow"]
    code = main(
        [
            "run-inference",
            *common,
            "--plan",
            str(case / "plan.yaml"),
            "--model-pickle",
            str(model_pickle),
            "--out",
            str(tmp_path / "inf"),
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["predictions"]["file"] == "predictions.parquet"
    code = main(
        [
            "metrics",
            *common,
            "--plan",
            str(case / "plan.yaml"),
            "--predictions",
            str(tmp_path / "inf" / "predictions.parquet"),
            "--out",
            str(tmp_path / "res"),
        ]
    )
    assert code == 1  # the proxy flip rate fails the org threshold, as in a live run
    saved = json.loads((tmp_path / "res" / "test-results.json").read_text(encoding="utf-8"))
    assert saved["inference"]["predictions_sha256"]
    with pytest.raises(SystemExit):
        main(["metrics", *common, "--plan", str(case / "plan.yaml"), "--out", "x"])


def test_unreachable_model_fails_inference(case, tmp_path):
    def broken():
        raise TargetError("mlflow unreachable")

    with pytest.raises(TargetError):
        run_inference(
            case / "data",
            tmp_path / "inf",
            plugin_path=case / "plugin.yaml",
            target_factory=broken,
            run_logger=_off(),
        )
    assert not (tmp_path / "inf" / "predictions.parquet").exists()
