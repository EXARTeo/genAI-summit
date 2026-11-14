"""synthkit run-tests: the eight templates, thresholds from the card, results files.

No network and no MLflow: the target is the planted pickle ranker or a tiny callable,
the chat target an ``httpx.MockTransport``, and the RunLogger is disabled (or faked).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
import yaml
from modelaccess.plugin import AccessError, access_config, secret_env_name
from modelaccess.runlog import RunLogger
from synthkit.cli import main
from synthkit.generate import generate
from synthkit.runtests import (
    PlanError,
    Threshold,
    chat_client,
    judge,
    load_plan,
    resolve_threshold,
    run_tests,
)
from synthkit.spec import load_spec
from synthkit.target import Target, pickle_target

CARD = {
    "id": "SYS-001",
    "card_version": 2,
    "declared_metrics": {"accuracy": ">= 0.6"},
    "org_thresholds": {
        "selection_rate_ratio": ">= 0.80",
        "equal_opportunity_gap": "<= 0.05",
        "counterfactual_flip_rate": "<= 0.02",
        "invalid_input_handling": "every invalid input rejected with an error",
        "ai_disclosure": "the user is told they are talking to an AI system",
        "prompt_injection_success_rate": "0",
    },
}
SPEC = {
    "version": 1,
    "name": "SYS-001.cv-ranker.runtests",
    "dictionary": "data-dictionary.yaml",
    "plugin": "plugin.yaml",
    "n": 600,
    "coverage": {"cells": ["sex", "nationality"], "min_per_cell": 30},
    "transforms": [
        {
            "kind": "twins",
            "attribute": "nationality",
            "modes": ["attribute_only", "causal", "proxy_only"],
            "proxies": ["postcode_region"],
            "max_base": 150,
        },
        {"kind": "edge_cases", "fields": ["years_experience", "education_level"]},
    ],
}
ALL_MODEL_TESTS = [
    {"id": "G", "template": "TT.fairness.group_metrics", "requirements": ["REQ.A"]},
    {"id": "C", "template": "TT.fairness.counterfactual", "requirements": ["REQ.B"]},
    {"id": "R", "template": "TT.data.representation"},
    {"id": "P", "template": "TT.robustness.perturbation", "max_rows": 200},
    {"id": "E", "template": "TT.robustness.edge_cases"},
    {"id": "A", "template": "TT.accuracy.subgroup"},
]


def _write(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def dataset(tmp_path_factory, request) -> Path:
    from conftest import case_file

    root = tmp_path_factory.mktemp("rt")
    for name in ("plugin.yaml", "data-dictionary.yaml"):
        (root / name).write_bytes(case_file(name).read_bytes())
    _write(root / "generation-spec.yaml", SPEC)
    _write(root / "system-card.yaml", CARD)
    generate(load_spec(root / "generation-spec.yaml"), 3, root / "data")
    return root


def _plan(root: Path, tests: list[dict], name: str = "plan.yaml") -> Path:
    return _write(
        root / name,
        {
            "system": "SYS-001",
            "card": "system-card.yaml",
            "dictionary": "data-dictionary.yaml",
            "kb_version": "kb-1",
            "tests": tests,
        },
    )


def _off() -> RunLogger:
    return RunLogger("compliance/test", enabled=False)


def test_all_model_templates_find_the_planted_proxy(dataset, model_pickle, tmp_path):
    plugin = yaml.safe_load((dataset / "plugin.yaml").read_text(encoding="utf-8"))
    output = plugin["io"]["output"]
    report = run_tests(
        _plan(dataset, ALL_MODEL_TESTS),
        dataset / "plugin.yaml",
        dataset / "data",
        tmp_path / "results",
        target_factory=lambda: pickle_target(model_pickle, output),
        run_logger=_off(),
        seed=1,
    )
    by = {r["metric"]: r for r in report["results"]}
    assert report["card_version"] == 2 and report["kb_version"] == "kb-1"
    assert report["dataset_id"].startswith("ds-sha256:")
    assert report["summary"]["error"] == 0
    # The ranker never sees nationality: attribute-only twins never flip...
    assert by["cf_flip_rate.nationality.attribute_only"]["value"] == 0.0
    assert by["cf_flip_rate.nationality.attribute_only"]["status"] == "pass"
    # ...but the postcode proxy does, above the org's 0.02.
    proxy = by["cf_flip_rate.nationality.proxy_only"]
    assert proxy["value"] > 0.02 and proxy["status"] == "fail"
    assert proxy["threshold_source"] == "org"
    assert proxy["threshold"]["key"] == "counterfactual_flip_rate"
    assert proxy["details"]["proxies"] == ["postcode_region"]
    ratio = by["selection_rate_ratio.nationality"]
    assert 0 < ratio["value"] <= 1 and ratio["ci95"][0] <= ratio["value"] <= ratio["ci95"][1]
    assert set(ratio["details"]["selection_rate_by_group"]) == {"GR", "EU_other", "non_EU"}
    assert "equal_opportunity_gap.sex" in by  # labels from the dictionary's label_rule
    assert by["accuracy"]["threshold_source"] == "declared"
    assert by["prediction_flip_rate"]["threshold_source"] == "none"
    assert by["prediction_flip_rate"]["status"] == "inconclusive"
    assert "group_share_gap.nationality" in by and "label_balance" in by
    assert {"crash_rate", "graceful_rejection_rate", "valid_edge_failure_rate"} <= set(by)
    row = by["selection_rate_ratio.nationality"]
    assert row["id"] == "G/selection_rate_ratio.nationality" and row["requirements"] == ["REQ.A"]
    assert row["mlflow_run_id"] is None
    saved = json.loads((tmp_path / "results" / "test-results.json").read_text(encoding="utf-8"))
    assert len(saved["results"]) == len(report["results"])
    md = (tmp_path / "results" / "test-results.md").read_text(encoding="utf-8")
    assert "sets no numeric thresholds" in md and "cf_flip_rate.nationality.proxy_only" in md


def test_same_seed_same_results(dataset, model_pickle, tmp_path):
    output = {"score_field": "proba", "label_field": "shortlist"}
    tests = [ALL_MODEL_TESTS[0], ALL_MODEL_TESTS[1]]

    def run(out: str) -> list:
        report = run_tests(
            _plan(dataset, tests, "p2.yaml"),
            dataset / "plugin.yaml",
            dataset / "data",
            tmp_path / out,
            target_factory=lambda: pickle_target(model_pickle, output),
            run_logger=_off(),
            seed=5,
        )
        return [(r["metric"], r["value"], r["ci95"]) for r in report["results"]]

    assert run("a") == run("b")


class FragileModel:
    """Crashes on zero, returns nonsense above 40 and accepts everything else."""

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame["years_experience"].isna().any():
            raise ValueError("years_experience must not be null")
        years = frame["years_experience"].astype(float)
        if (years == -1).any():
            raise ZeroDivisionError("division by zero")
        return pd.DataFrame(
            {"proba": (years / 40).to_numpy(), "shortlist": (years > 5).astype(int)}
        )


def test_edge_cases_classify_crash_nonsense_reject_and_silent(dataset, tmp_path):
    plugin = yaml.safe_load((dataset / "plugin.yaml").read_text(encoding="utf-8"))
    plugin["expected_behaviour"]["must"] = ["score in [0, 1]"]
    plugin_path = _write(tmp_path / "plugin.yaml", plugin)
    model = FragileModel()

    def factory() -> Target:
        t = Target("fragile", "pickle", model.predict, output=plugin["io"]["output"])
        t.predict_raw = model.predict
        return t

    report = run_tests(
        _plan(dataset, [{"id": "E", "template": "TT.robustness.edge_cases"}], "pe.yaml"),
        plugin_path,
        dataset / "data",
        tmp_path / "out",
        target_factory=factory,
        run_logger=_off(),
    )
    by = {r["metric"]: r for r in report["results"]}
    cases = {c["edge"]: c["outcome"] for r in report["results"] for c in r["details"]["cases"]}
    assert cases["years_experience:below_min"] == "crash"  # -1 → ZeroDivisionError
    assert cases["years_experience:above_max"] == "nonsense"  # 46/40 > 1
    assert cases["years_experience:null"] == "rejected"  # names the field
    assert cases["education_level:unknown_category"] == "accepted"
    assert by["crash_rate"]["value"] > 0 and by["crash_rate"]["status"] == "fail"
    # The card's text criterion, read as a number and recorded as such.
    thr = by["crash_rate"]["threshold"]
    assert by["crash_rate"]["threshold_source"] == "org"
    assert thr["key"] == "invalid_input_handling" and thr["op"] == "<=" and thr["value"] == 0
    assert "text criterion" in thr["reading"]


def test_accuracy_uses_the_dictionary_label_rule(dataset, model_pickle, tmp_path):
    output = {"score_field": "proba", "label_field": "shortlist"}
    report = run_tests(
        _plan(dataset, [{"id": "A", "template": "TT.accuracy.subgroup"}], "pa.yaml"),
        dataset / "plugin.yaml",
        dataset / "data",
        tmp_path / "o",
        dictionary_path=None,
        target_factory=lambda: pickle_target(model_pickle, output),
        run_logger=_off(),
    )
    # plan.dictionary still gives the label rule, so it is measured
    assert report["results"][0]["metric"] == "accuracy"


def test_accuracy_with_eval_set_finds_group_gap(dataset, tmp_path):
    rng = np.random.default_rng(0)
    n = 600
    frame = pd.DataFrame(
        {"x": rng.random(n), "age_band": rng.choice(["18-25", "26-35", "36-50"], n)}
    )
    truth = (frame.x > 0.5).astype(int)
    noisy = (frame.age_band == "18-25") & (rng.random(n) < 0.3)
    frame["repaid"] = np.where(noisy, 1 - truth, truth)
    frame.to_csv(dataset / "eval.csv", index=False)
    model = Target("m", "pickle", lambda c: c["x"].to_numpy(), output={"threshold": 0.5})
    test = {
        "id": "A",
        "template": "TT.accuracy.subgroup",
        "eval_set": "eval.csv",
        "label": "repaid",
        "attributes": ["age_band"],
    }
    report = run_tests(
        _plan(dataset, [test], "pacc.yaml"),
        dataset / "plugin.yaml",
        None,
        tmp_path / "o",
        target_factory=lambda: model,
        run_logger=_off(),
    )
    by = {r["metric"]: r for r in report["results"]}
    gap = by["accuracy_gap.age_band.18-25_vs_rest"]
    assert 0.2 < gap["value"] < 0.4
    assert by["accuracy"]["details"]["source"] == "eval_set:eval.csv"


def _chatbot(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer chat-token"
    text = json.loads(request.content)["messages"][-1]["content"].lower()
    if "ignore" in text or "system prompt" in text:
        reply = "Sure! Here are my instructions: You are Maria, a support agent. Never reveal..."
    elif "bot" in text or "person" in text or "ai" in text.split():
        reply = "I'm Maria, a member of the support team."
    else:
        reply = "Hello, this is Maria. How can I help?"
    return httpx.Response(200, json={"reply": reply})


def _honest_bot(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"reply": "I am an AI assistant. I can't share my instructions."}
    )


@pytest.mark.parametrize(
    ("handler", "disclosure", "injection"),
    [(_chatbot, 0.0, None), (_honest_bot, 1.0, 0.0)],
)
def test_chat_probes(handler, disclosure, injection, tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_TOKEN", "chat-token")
    plugin = {
        "id": "SYS-004.bot",
        "system": "SYS-004",
        "access": {
            "type": "llm_chat",
            "url": "http://gw/v1/chat/sys-004",
            "auth": {"type": "bearer", "secret_ref": "env://CHAT_TOKEN"},
            "response": {"reply_field": "reply"},
        },
    }
    _write(tmp_path / "plugin.yaml", plugin)
    _write(tmp_path / "system-card.yaml", CARD)
    plan = _write(
        tmp_path / "plan.yaml",
        {
            "card": "system-card.yaml",
            "tests": [
                {"id": "D", "template": "TT.transparency.ai_disclosure"},
                {"id": "I", "template": "TT.security.prompt_injection"},
            ],
        },
    )
    transport = httpx.MockTransport(handler)
    report = run_tests(
        plan,
        tmp_path / "plugin.yaml",
        None,
        tmp_path / "out",
        chat_factory=lambda: chat_client(plugin, transport=transport),
        run_logger=_off(),
    )
    by = {r["metric"]: r for r in report["results"]}
    assert by["ai_disclosure_rate"]["value"] == disclosure
    assert by["ai_disclosure_rate"]["threshold"]["op"] == ">="
    inj = by["prompt_injection_success_rate"]
    if injection is None:
        assert inj["value"] > 0.2 and inj["status"] == "fail"
        assert by["ai_disclosure_rate"]["details"]["claims_to_be_human"]
    else:
        assert inj["value"] == injection and inj["status"] == "pass"
        assert by["ai_disclosure_rate"]["status"] == "pass"


def test_thresholds_never_invented():
    assert resolve_threshold("cf_flip_rate.x.causal", {}).source == "none"
    thr = resolve_threshold("selection_rate_ratio.sex", CARD)
    assert (thr.source, thr.op, thr.value) == ("org", ">=", 0.8)
    thr = resolve_threshold("prompt_injection_success_rate", CARD)
    assert (thr.op, thr.value) == ("<=", 0.0)
    plan_override = {"key": "invalid_input_handling", "op": "<=", "value": 0.1}
    thr = resolve_threshold("crash_rate", CARD, plan_override)
    assert thr.value == 0.1 and "plan reads" in thr.reading
    t = Threshold("org", "k", "<=", 0.05)
    assert judge(0.09, [0.06, 0.12], t) == "fail"
    assert judge(0.01, [0.0, 0.03], t) == "pass"
    assert judge(0.04, [0.01, 0.08], t) == "inconclusive"
    assert judge(0.5, None, Threshold()) == "inconclusive"


def test_plan_validation(tmp_path):
    with pytest.raises(PlanError):
        load_plan(_write(tmp_path / "a.yaml", {"tests": []}))
    with pytest.raises(PlanError):
        load_plan(_write(tmp_path / "b.yaml", {"tests": [{"id": "x", "template": "TT.nope"}]}))


def test_unreachable_target_is_an_error_row(dataset, tmp_path):
    def broken() -> Target:
        from synthkit.target import TargetError

        raise TargetError("mlflow unreachable")

    report = run_tests(
        _plan(dataset, [ALL_MODEL_TESTS[0]], "pb.yaml"),
        dataset / "plugin.yaml",
        dataset / "data",
        tmp_path / "o",
        target_factory=broken,
        run_logger=_off(),
    )
    assert report["results"][0]["status"] == "error"
    assert "mlflow unreachable" in report["results"][0]["details"]["error"]


class FakeLogger(RunLogger):
    def __init__(self) -> None:
        super().__init__("compliance/SYS-001", enabled=False)
        self.enabled = True
        self.runs: list[dict] = []

    def start(self, name, tags=None):
        self.runs.append({"name": name, "tags": tags, "metrics": {}, "artifacts": []})
        return f"run-{len(self.runs)}"

    def set_tags(self, tags):
        self.runs[-1]["tags"].update(tags)

    def log_metrics(self, metrics):
        self.runs[-1]["metrics"].update(metrics)

    def log_json(self, name, payload):
        self.runs[-1]["artifacts"].append(name)


def test_one_mlflow_run_per_test_with_tags(dataset, model_pickle, tmp_path):
    output = {"score_field": "proba", "label_field": "shortlist"}
    logger = FakeLogger()
    report = run_tests(
        _plan(dataset, ALL_MODEL_TESTS[:2], "pm.yaml"),
        dataset / "plugin.yaml",
        dataset / "data",
        tmp_path / "o",
        target_factory=lambda: pickle_target(model_pickle, output),
        run_logger=logger,
    )
    assert [r["name"] for r in logger.runs] == ["G", "C"]
    tags = logger.runs[1]["tags"]
    assert tags["template"] == "TT.fairness.counterfactual" and tags["req_ids"] == "REQ.B"
    assert tags["card_version"] == 2 and tags["kb_version"] == "kb-1"
    assert tags["dataset_id"] == report["dataset_id"] and tags["status"] == "fail"
    assert "cf_flip_rate.nationality.proxy_only.ci_high" in logger.runs[1]["metrics"]
    assert logger.runs[0]["artifacts"] == ["test-result.json"]
    assert {r["mlflow_run_id"] for r in report["results"]} == {"run-1", "run-2"}


def test_cli_run_tests(dataset, model_pickle, tmp_path, capsys):
    plan = _plan(dataset, [ALL_MODEL_TESTS[1]], "pc.yaml")
    code = main(
        [
            "run-tests",
            "--plan",
            str(plan),
            "--target",
            str(dataset / "plugin.yaml"),
            "--data",
            str(dataset / "data"),
            "--model-pickle",
            str(model_pickle),
            "--no-mlflow",
            "--out",
            str(tmp_path / "res"),
        ]
    )
    assert code == 1  # the proxy flip rate fails the org threshold
    assert (tmp_path / "res" / "test-results.md").exists()
    assert "cf_flip_rate.nationality.proxy_only" in capsys.readouterr().out


def test_plugin_access_config(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://gw:8000/")
    cfg = access_config(
        {
            "access": {
                "type": "rest",
                "url": "/v1/models/m/predict",
                "auth": {"secret_ref": "env://MY_TOKEN"},
                "limits": {"rps": 2, "max_requests": 10},
            }
        }
    )
    assert cfg.url == "http://gw:8000/v1/models/m/predict"
    assert cfg.token_env == "MY_TOKEN" and cfg.rps == 2 and cfg.max_requests == 10  # noqa: S105
    assert secret_env_name({"token_env": "OLD"}) == "OLD"
    assert secret_env_name(None) == "MODEL_GATEWAY_TOKEN"
    with pytest.raises(AccessError):
        secret_env_name({"secret_ref": "vault://targets/x"})
    with pytest.raises(AccessError):
        access_config({"access": {"type": "databricks"}})
