"""synthkit profile on a tiny sklearn model with the SYS-001 planted issue, and
the twin gaps the profile predicts. No network: a local pickle and a mock REST
transport."""

from __future__ import annotations

import json

import httpx
import numpy as np
import pandas as pd
import yaml
from conftest import RANKER_FEATURES
from synthkit.analyze import run_analysis
from synthkit.cli import main
from synthkit.generate import generate
from synthkit.profile import run_profile
from synthkit.spec import Dictionary, load_spec
from synthkit.target import pickle_target, rest_target


def _profile(case_dir, model_pickle):
    plugin = yaml.safe_load((case_dir / "plugin.yaml").read_text(encoding="utf-8"))
    target = pickle_target(model_pickle, plugin["io"]["output"])
    dictionary = Dictionary.load(case_dir / "data-dictionary.yaml")
    return run_profile(target, dictionary, plugin, seed=0, n_probe=160, n_oat=32)


def test_profile_finds_the_proxies(case_dir, model_pickle):
    p = _profile(case_dir, model_pickle)
    assert p["signature"]["inputs"] == RANKER_FEATURES
    assert p["output"]["in_unit_interval"]
    assert p["determinism"]["holds"]
    assert p["proxies"]["postcode_region"]["moves_output"]
    assert p["proxies"]["career_gap_months"]["moves_output"]
    assert p["proxies"]["postcode_region"]["association_cramers_v"]["nationality"] > 0.1
    for attr in ("sex", "nationality"):
        assert p["protected"][attr]["model_input"] is False
    assert p["monotonicity"]["years_experience"]["holds"]
    assert p["decision_boundary"]["surrogate"]["numeric"]
    assert any("postcode_region" in n and "causal" in n for n in p["notes"])
    assert p["calls"]["errors"] == 0


def test_cli_profile_writes_json(case_dir, model_pickle):
    out = case_dir / "model-profile.json"
    code = main(
        [
            "profile",
            "--plugin",
            str(case_dir / "plugin.yaml"),
            "--dictionary",
            str(case_dir / "data-dictionary.yaml"),
            "--model-pickle",
            str(model_pickle),
            "--n-probe",
            "80",
            "--n-oat",
            "16",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["sensitivity_ranking"]


def test_twin_gaps_show_the_planted_proxy(case_dir, model_pickle, planted_model):
    """(a) attribute-only: no gap; (b) causal and (c) proxy-only: a gap."""
    profile = _profile(case_dir, model_pickle)
    (case_dir / "model-profile.json").write_text(json.dumps(profile), encoding="utf-8")
    spec = {
        "name": "twins",
        "dictionary": "data-dictionary.yaml",
        "plugin": "plugin.yaml",
        "model_profile": "model-profile.json",
        "n": 150,
        "strata": {"by": ["nationality"]},
        "boundary": {"share": 0.3, "pool": 5},
        "transforms": [{"kind": "twins", "attribute": "nationality"}],
    }
    (case_dir / "spec.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    loaded = load_spec(case_dir / "spec.yaml")
    card = generate(loaded, 11, case_dir / "out")
    assert card["generation"]["boundary_aware"] is True
    assert card["composition"]["boundary_rows"] > 0
    df = pd.read_parquet(case_dir / "out" / "dataset.parquet")
    x = df[RANKER_FEATURES].astype({"years_experience": float, "career_gap_months": float})
    df["score"] = planted_model.predict_proba(x)[:, 1]
    base = df.set_index("_row_id")["score"]
    twins = df[df._test == "twin"].copy()
    twins["gap"] = twins.score.to_numpy() - base.loc[twins._twin_of].to_numpy()
    gap = twins.groupby("_twin_mode").gap.apply(lambda g: float(np.abs(g).mean()))
    assert gap["attribute_only"] < 1e-9
    assert gap["causal"] > 0.03
    assert gap["proxy_only"] > 0.03
    analysis = run_analysis(df.drop(columns="score"), loaded)
    assert analysis["informativeness"]["available"]


def test_rest_target_respects_429_and_reads_predictions(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_TOKEN", "tok")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["Authorization"] == "Bearer tok"
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        rows = json.loads(request.content)["inputs"]
        preds = [{"shortlist": int(r["x"] > 1), "proba": r["x"] / 4} for r in rows]
        return httpx.Response(200, json={"predictions": preds, "model": "m", "version": "1"})

    access = {"url": "http://gw/v1/models/m/predict", "limits": {"rps": 1000}}
    output = {"score_field": "proba", "label_field": "shortlist"}
    target = rest_target(access, output, transport=httpx.MockTransport(handler))
    scores, decisions = target.score(pd.DataFrame({"x": [0, 1, 2, 3]}))
    assert scores.tolist() == [0, 0.25, 0.5, 0.75]
    assert decisions.tolist() == [0, 0, 1, 1]
    assert calls["n"] == 2
