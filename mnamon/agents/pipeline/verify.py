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
#: The spec keys code owns: the model may never move them (paths synthkit resolves).
FIXED_SPEC_KEYS = {
    "version": 1,
    "dictionary": "data/data-dictionary.yaml",
    "plugin": "plugin.yaml",
    "model_profile": "model-profile.json",
}
#: synthkit's transforms and twin modes (synthkit/spec.py).
TRANSFORMS = ("twins", "edge_cases", "perturbation")
TWIN_MODES = ("attribute_only", "causal", "proxy_only")
#: Dictionary field types that form coverage / strata cells.
CATEGORICAL_TYPES = {"category", "categorical", "boolean", "bool", "enum"}


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


def _dictionary_fields(dictionary_yaml: str | None) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(dictionary_yaml or "")
    except yaml.YAMLError:
        return None
    fields = (data or {}).get("fields") if isinstance(data, dict) else None
    return fields if isinstance(fields, dict) else None


def _categorical(dictionary_yaml: str | None) -> set[str] | None:
    fields = _dictionary_fields(dictionary_yaml)
    if fields is None:
        return None
    return {
        name
        for name, f in fields.items()
        if isinstance(f, dict) and str(f.get("type", "")).lower() in CATEGORICAL_TYPES
    }


def _sanitise(spec: dict[str, Any], known: set[str], notes: list[str]) -> None:
    """What synthkit would reject and code can fix without changing the intent."""
    rules = spec.get("rules")
    if isinstance(rules, list):
        seen: set[str] = set()
        clean = []
        for n, rule in enumerate(rules, start=1):
            if not isinstance(rule, dict) or not rule.get("expr"):
                notes.append(f"rules[{n}] dropped: no expr")
                continue
            rid = str(rule.get("id") or "")
            if not rid or rid in seen:
                new = next(f"R{k}" for k in range(n, n + len(rules) + 100) if f"R{k}" not in seen)
                notes.append(f"rule id {rid or '(none)'} -> {new} (ids must be unique)")
                rule = {**rule, "id": new}
                rid = new
            if rule.get("severity", "hard") not in ("hard", "soft"):
                rule = {**rule, "severity": "soft"}
            seen.add(rid)
            clean.append(rule)
        spec["rules"] = clean
    overrides = spec.get("fields")
    if isinstance(overrides, dict):
        unknown = [f for f in overrides if f not in known]
        for f in unknown:
            overrides.pop(f)
        if unknown:
            notes.append(f"fields: dropped overrides of unknown fields {unknown}")
    transforms = spec.get("transforms")
    if isinstance(transforms, list):
        kept = []
        for t in transforms:
            if not isinstance(t, dict) or t.get("kind") not in TRANSFORMS:
                notes.append(f"transform dropped: {t!r:.80}")
                continue
            if t["kind"] == "twins":
                if t.get("attribute") not in known:
                    notes.append(f"twins dropped: unknown attribute {t.get('attribute')!r}")
                    continue
                if t.get("modes"):
                    t["modes"] = [m for m in t["modes"] if m in TWIN_MODES] or list(TWIN_MODES)
                if t.get("proxies"):
                    t["proxies"] = [p for p in t["proxies"] if p in known]
            if t.get("fields"):
                bad = [f for f in t["fields"] if f not in known]
                t["fields"] = [f for f in t["fields"] if f in known]
                if bad:
                    notes.append(f"{t['kind']}: dropped unknown fields {bad}")
                if not t["fields"]:
                    notes.append(f"{t['kind']} dropped: no known field left")
                    continue
            kept.append(t)
        spec["transforms"] = kept


def normalise_spec(
    spec_yaml: str, dictionary_yaml: str | None, *, has_profile: bool = True
) -> tuple[str, list[str]]:
    """Code-owned keys overwritten, numeric fields out of coverage/strata cells.

    Returns the spec YAML to use and what code changed (for the artifact). A spec
    that does not parse comes back unchanged (``parse_spec`` reports it).
    """
    try:
        spec = yaml.safe_load(spec_yaml)
    except yaml.YAMLError:
        return spec_yaml, []
    if not isinstance(spec, dict):
        return spec_yaml, []
    notes: list[str] = []
    for key, value in FIXED_SPEC_KEYS.items():
        if key == "model_profile" and not has_profile:
            if spec.pop(key, None) is not None:
                notes.append("model_profile removed: no profile in this audit")
            continue
        if spec.get(key) != value:
            notes.append(f"{key} set to {value!r} (was {spec.get(key)!r})")
            spec[key] = value
    fields = _dictionary_fields(dictionary_yaml)
    if fields is not None:
        _sanitise(spec, set(fields), notes)
    categorical = _categorical(dictionary_yaml)
    if categorical is not None:
        for block, list_key in (("coverage", "cells"), ("strata", "by")):
            part = spec.get(block)
            if not isinstance(part, dict) or not isinstance(part.get(list_key), list):
                continue
            keep = [f for f in part[list_key] if f in categorical or f == "_test"]
            dropped = [f for f in part[list_key] if f not in keep]
            if dropped:
                notes.append(f"{block}.{list_key}: dropped non-categorical {dropped}")
                part[list_key] = keep
            if not keep:
                spec.pop(block, None)
    if not notes:
        return spec_yaml, []
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), notes


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
            if name == "coverage":
                out.append(coverage_feedback(gate))
                continue
            detail = "; ".join(str(p) for p in (gate.get("problems") or [])[:5])
            out.append(f"gate {name} failed" + (f": {detail}" if detail else ""))
    return out


def coverage_feedback(gate: dict[str, Any]) -> str:
    """The coverage failure as a fix the spec writer can act on (cells, counts, the min)."""
    low = gate.get("below_min") or {}
    need = gate.get("min_per_cell")
    worst = sorted(low.items(), key=lambda kv: kv[1])[:6]
    shown = ", ".join(f"{cell} ({n})" for cell, n in worst)
    return (
        f"gate coverage failed: {len(low)} of {len(gate.get('counts') or {})} cells over "
        f"{gate.get('cells')} have fewer than min_per_cell={need} base rows: {shown}. "
        "Fix: use only categorical fields in coverage.cells, fewer cells, a lower "
        "min_per_cell, or a larger n."
    )


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
    "FIXED_SPEC_KEYS",
    "coverage_feedback",
    "dataset_problems",
    "normalise_spec",
    "evidence_problems",
    "parse_spec",
    "scenario_problems",
    "spec_problems",
]
