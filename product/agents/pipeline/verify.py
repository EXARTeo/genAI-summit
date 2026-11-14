"""Deterministic verifiers (ἔλεγχος against evidence, never the model's own judgement).

Each returns the problems it found (empty = the output stands). A problem list
goes back to the step that produced the output as an automatic redo, at most
``PIPELINE_MAX_AUTO_REDOS`` times, then the output moves on with the problems
recorded for the human gate and the critic.

* :func:`scenario_problems`: synthkit scenarios-check found a high-ranked gap or
  an incomplete scenario.
* :func:`spec_problems`: the GenerationSpec is not YAML, or misses fixed keys.
* :func:`dataset_problems`: a blocking dataset gate failed.
* :func:`evidence_problems`: a finding quotes a number, a run id or a test that
  is not in the test results (grounding), or cites no provision.
"""

from __future__ import annotations

import math
from typing import Any

import yaml

SPEC_KEYS = {
    "version",
    "name",
    "dictionary",
    "plugin",
    "model_profile",
    "n",
    "fields",
    "rules",
    "strata",
    "boundary",
    "coverage",
    "transforms",
    "custom",
    "output",
    "generation",
}
BLOCKING_GATES = ("schema", "business_rules", "coverage", "privacy")


def scenario_problems(analysis: dict[str, Any] | None) -> list[str]:
    if not analysis:
        return []
    out = [
        f"missing (high): {m.get('what')}: {m.get('why')}"
        for m in analysis.get("missing") or []
        if m.get("priority") == "high"
    ]
    for item in analysis.get("scenarios") or []:
        issues = item.get("issues") or []
        if issues:
            out.append(f"{item.get('id')}: {'; '.join(map(str, issues))}")
    return out


def parse_spec(spec_yaml: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        spec = yaml.safe_load(spec_yaml)
    except yaml.YAMLError as exc:
        return None, [f"spec_yaml is not valid YAML: {exc}"]
    if not isinstance(spec, dict):
        return None, ["spec_yaml must be a YAML mapping"]
    return spec, spec_problems(spec)


def spec_problems(spec: dict[str, Any]) -> list[str]:
    out = [f"unknown top-level key {key!r}" for key in spec if key not in SPEC_KEYS]
    for key in ("version", "name", "dictionary", "n"):
        if key not in spec:
            out.append(f"missing key {key!r}")
    return out


def dataset_problems(analysis: dict[str, Any] | None) -> list[str]:
    if not analysis:
        return []
    gates = analysis.get("gates") or {}
    out = []
    for name in BLOCKING_GATES:
        gate = gates.get(name)
        if isinstance(gate, dict) and gate.get("status") == "fail":
            detail = "; ".join(str(p) for p in (gate.get("problems") or [])[:5])
            out.append(f"gate {name} failed" + (f": {detail}" if detail else ""))
    return out


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=1e-6)


def evidence_problems(findings: list[dict[str, Any]], results: dict[str, Any]) -> list[str]:
    """Every quoted number / run id / test id must be in the test results."""
    tests = {t.get("id"): t for t in results.get("tests") or []}
    run_ids = {t.get("mlflow_run_id") for t in tests.values() if t.get("mlflow_run_id")}
    out: list[str] = []
    for finding in findings:
        fid = finding.get("id")
        if not finding.get("citations") and finding.get("verdict") != "not_assessable_by_testing":
            out.append(f"{fid}: no provision cited")
        for ev in finding.get("evidence") or []:
            test = tests.get(ev.get("test_id"))
            if test is None:
                out.append(f"{fid}: evidence names test {ev.get('test_id')!r}, not in the results")
                continue
            value, real = ev.get("value"), test.get("value")
            if value is not None and real is not None and not _close(float(value), float(real)):
                out.append(f"{fid}: {ev.get('test_id')} value {value} != result {real}")
            run = ev.get("mlflow_run_id")
            if run and run not in run_ids:
                out.append(f"{fid}: MLflow run {run!r} is not in the results")
    return out


__all__ = [
    "dataset_problems",
    "evidence_problems",
    "parse_spec",
    "scenario_problems",
    "spec_problems",
]
