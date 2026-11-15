"""Deterministic glue around synthkit: the sandbox commands, the test plan, the results.

The commands follow ``docs/services/sandbox.md``: the audit's files go to
``input/`` (``plugin.yaml``, ``data/data-dictionary.yaml``, ``data/sample.csv``,
``generation-spec.yaml``, ``model-profile.json``, ``test-plan.yaml``, an approved
public dataset under ``datasets/public/<slug>/``), commands run in ``output/``.
``generate`` writes the dataset to ``generated/`` in ``output/``; the pipeline
keeps the parquet (and its sha256) and hands the SAME file to every later call
as ``input/data/generated/`` (:data:`DATA_DIR`) instead of regenerating it.

Raw before analysis (plan 01 P4): ``synthkit run-inference`` only calls the
model and saves ``inference/predictions.parquet`` + ``run.json`` (hashed, one
MLflow run); ``synthkit metrics --predictions`` then computes every metric from
those saved predictions without calling the model (one MLflow run per test) and
writes ``results/test-results.json``; :func:`normalise_results` reads it
defensively.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

#: Where a regenerated dataset lives inside one sandbox call (not returned).
TMP_DATA = "../tmp/data"
#: Where the saved dataset is handed to a sandbox call (input-relative and absolute).
DATA_REL = "data/generated"
DATA_DIR = f"../input/{DATA_REL}"
#: Where the saved predictions are handed to a sandbox call.
INFERENCE_REL = "inference"

#: Scenario template -> the reg-memory / synthkit run-tests template id.
TEMPLATE_IDS = {
    "counterfactual_twins": "TT.fairness.counterfactual",
    "group_fairness": "TT.fairness.group_metrics",
    "perturbation": "TT.robustness.perturbation",
    "monotonicity": "TT.robustness.perturbation",
    "edge_cases": "TT.robustness.edge_cases",
    "accuracy_per_subgroup": "TT.accuracy.subgroup",
}
#: run-tests status -> passed flag.
PASSED = {"pass": True, "fail": False}


def profile_command(has_sample: bool) -> str:
    sample = " --sample ../input/data/sample.csv" if has_sample else ""
    return (
        "synthkit profile --plugin ../input/plugin.yaml "
        f"--dictionary ../input/data/data-dictionary.yaml{sample} --out model-profile.json"
    )


def scenarios_check_command(has_profile: bool) -> str:
    profile = " --profile ../input/model-profile.json" if has_profile else ""
    return (
        "synthkit scenarios-check --scenarios ../input/scenarios.yaml "
        f"--plugin ../input/plugin.yaml --dictionary ../input/data/data-dictionary.yaml"
        f"{profile} --out-dir ."
    )


def generate_saved_command(seed: int) -> str:
    """Generate into ``generated/`` (returned): parquet + DataCard + 20 sample rows."""
    return (
        "synthkit generate --spec ../input/generation-spec.yaml "
        f"--seed {int(seed)} --out-dir generated --format both"
        " && head -n 21 generated/dataset.csv > sample-rows.csv && rm -f generated/dataset.csv"
    )


def analyze_saved_command(seed: int, has_profile: bool) -> str:
    profile = " --profile ../input/model-profile.json" if has_profile else ""
    return (
        f"synthkit analyze --dataset {DATA_DIR}/dataset.parquet "
        f"--spec ../input/generation-spec.yaml{profile} --seed {int(seed)} --out-dir ."
    )


def run_inference_command(seed: int) -> str:
    """Only the model calls: ``inference/predictions.parquet`` + ``inference/run.json``."""
    return (
        f"synthkit run-inference --data {DATA_DIR} --target ../input/plugin.yaml "
        f"--plan ../input/test-plan.yaml --seed {int(seed)} --out inference"
    )


def metrics_command(seed: int) -> str:
    """Every metric from the saved predictions (no model call): ``results/test-results.json``."""
    return (
        "synthkit metrics --plan ../input/test-plan.yaml --target ../input/plugin.yaml "
        f"--data {DATA_DIR} --predictions ../input/{INFERENCE_REL}/predictions.parquet "
        f"--seed {int(seed)} --out results; code=$?; "
        'if [ "$code" -le 1 ]; then exit 0; else exit "$code"; fi'
    )


def generate_command(seed: int, *, keep_card: bool = True) -> str:
    cmd = (
        f"mkdir -p {TMP_DATA} && synthkit generate --spec ../input/generation-spec.yaml "
        f"--seed {int(seed)} --out-dir {TMP_DATA}"
    )
    if keep_card:
        cmd += (
            f" && cp {TMP_DATA}/DataCard.yaml ."
            f" && head -n 21 {TMP_DATA}/dataset.csv > sample-rows.csv"
        )
    return cmd


def analyze_command(seed: int, has_profile: bool) -> str:
    profile = " --profile ../input/model-profile.json" if has_profile else ""
    return (
        generate_command(seed, keep_card=False)
        + f" && synthkit analyze --dataset {TMP_DATA}/dataset.parquet "
        f"--spec ../input/generation-spec.yaml{profile} --seed {int(seed)} --out-dir ."
    )


def run_tests_command(seed: int) -> str:
    return (
        generate_command(seed, keep_card=False)
        + " && synthkit run-tests --plan ../input/test-plan.yaml --target ../input/plugin.yaml "
        f"--data {TMP_DATA} --seed {int(seed)} --out results; code=$?; "
        # exit 1 = a test failed: results exist, the run is still good evidence.
        'if [ "$code" -le 1 ]; then exit 0; else exit "$code"; fi'
    )


def build_test_plan(state: dict[str, Any], seed: int) -> dict[str, Any]:
    """The ``synthkit run-tests`` plan: one test per approved scenario.

    Thresholds are not in the plan: run-tests reads them from the system card
    (``card:``), ``org_thresholds`` first, and says so in every result.
    """
    data_card = (state.get("dataset") or {}).get("data_card") or {}
    tests = []
    for n, sc in enumerate((state.get("scenarios") or {}).get("scenarios") or [], start=1):
        needs = sc.get("data_needs") or {}
        template = sc.get("test_template") or TEMPLATE_IDS.get(str(sc.get("template")), "")
        test: dict[str, Any] = {
            "id": f"T-{n:02d}",
            "template": template,
            "requirements": [sc.get("requirement")] if sc.get("requirement") else [],
            "scenario": sc.get("id"),
        }
        if sc.get("obligation_id"):
            test["obligation_id"] = sc["obligation_id"]
        attributes = [a for a in [needs.get("attribute"), *(sc.get("protected") or [])] if a]
        if attributes and template in (
            "TT.fairness.group_metrics",
            "TT.accuracy.subgroup",
            "TT.data.representation",
            "TT.fairness.counterfactual",
        ):
            test["attributes"] = list(dict.fromkeys(attributes))
        tests.append(test)
    return {
        "version": 1,
        "system": state.get("system_id"),
        "plugin": state.get("target"),
        "card": "system-card.yaml",
        "dictionary": "data/data-dictionary.yaml",
        "kb_version": state.get("kb_version"),
        "audit_id": state.get("audit_id"),
        "seed": seed,
        "dataset_id": data_card.get("dataset_id"),
        "tests": tests,
    }


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _ci(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        value = [value.get("low", value.get("lo")), value.get("high", value.get("hi"))]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return None
    return None


def _threshold_text(threshold: Any, source: Any) -> dict[str, Any] | None:
    if not isinstance(threshold, dict):
        return None
    where = {
        "org": "system-card org_thresholds (organisational policy, not an AI Act number)",
        "declared": "system-card declared_metrics (the provider's own claim, not an AI Act number)",
    }.get(str(source), "none: no criterion on the card")
    return {**threshold, "source": where}


def normalise_results(raw: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """``results/test-results.json`` (synthkit run-tests) in the shape the findings step reads.

    One row per (test, metric): ``id`` is ``<test>/<metric>``. A plan test with
    no row at all becomes an ``error`` row, so every planned test is accounted for.
    """
    items = raw.get("results", raw.get("tests", [])) if isinstance(raw, dict) else raw
    by_id = {t["id"]: t for t in plan.get("tests") or []}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        test_id = str(_first(item, "test_id") or str(_first(item, "id") or "").split("/")[0])
        seen.add(test_id)
        planned = by_id.get(test_id, {})
        reqs = item.get("requirements") or planned.get("requirements") or []
        status = str(item.get("status") or "error")
        value = item.get("value")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        rows.append(
            {
                "id": str(_first(item, "id") or f"{test_id}/{item.get('metric')}"),
                "test_id": test_id,
                "scenario": planned.get("scenario"),
                "template": item.get("template") or planned.get("template"),
                "requirement": reqs[0] if reqs else None,
                "requirements": reqs,
                "obligation_id": item.get("obligation_id") or planned.get("obligation_id"),
                "metric": item.get("metric"),
                "value": value,
                "ci95": _ci(_first(item, "ci95", "ci")),
                "n": item.get("n"),
                "threshold": _threshold_text(item.get("threshold"), item.get("threshold_source")),
                "threshold_source": item.get("threshold_source"),
                "status": status,
                "passed": PASSED.get(status),
                "mlflow_run_id": item.get("mlflow_run_id"),
                "details": item.get("details") if isinstance(item.get("details"), dict) else None,
            }
        )
    for test_id, planned in by_id.items():
        if test_id not in seen:
            rows.append(
                {
                    "id": f"{test_id}/none",
                    "test_id": test_id,
                    "scenario": planned.get("scenario"),
                    "template": planned.get("template"),
                    "requirement": (planned.get("requirements") or [None])[0],
                    "requirements": planned.get("requirements") or [],
                    "obligation_id": planned.get("obligation_id"),
                    "metric": None,
                    "value": None,
                    "ci95": None,
                    "threshold": None,
                    "threshold_source": "none",
                    "status": "error",
                    "passed": None,
                    "mlflow_run_id": None,
                    "details": {"error": "run-tests returned no result for this test"},
                }
            )
    summary = raw.get("summary") if isinstance(raw, dict) else None
    context = (
        {
            k: raw.get(k)
            for k in (
                "system",
                "plugin",
                "target",
                "target_version",
                "dataset_id",
                "kb_version",
                "mlflow",
                "inference",
                "predictions_sha256",
            )
        }
        if isinstance(raw, dict)
        else {}
    )
    return {"tests": rows, "summary": summary, "n_tests": len(rows), "run": context}


def dumps_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def loads_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


__all__ = [
    "DATA_DIR",
    "DATA_REL",
    "INFERENCE_REL",
    "analyze_command",
    "analyze_saved_command",
    "generate_saved_command",
    "metrics_command",
    "run_inference_command",
    "build_test_plan",
    "dumps_yaml",
    "generate_command",
    "loads_json",
    "normalise_results",
    "profile_command",
    "run_tests_command",
    "scenarios_check_command",
]
