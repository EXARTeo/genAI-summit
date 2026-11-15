"""model-gateway API: auth, rate limit, predict, pipeline, 503, health."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from core.settings import settings

ROW = {"income": 50_000.0, "age": 40}
SCORER = "/v1/models/sys-002-credit-scorer/predict"


async def test_health_needs_no_auth_and_reports_models(api, auth):
    resp = await api.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["models"]["sys-002-credit-scorer"] == {"loaded": False, "version": None}
    assert body["simulated"] == []

    await api.post(SCORER, json={"inputs": [ROW]}, headers=auth)
    body = (await api.get("/health")).json()
    assert body["models"]["sys-002-credit-scorer"] == {"loaded": True, "version": "1"}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}],
)
async def test_predict_requires_bearer_token(api, headers):
    resp = await api.post(SCORER, json={"inputs": [ROW]}, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_fail_closed_without_token_outside_development(api, monkeypatch):
    monkeypatch.setattr(settings.security, "token", SecretStr(""))
    monkeypatch.setattr(settings.app, "env", "production")
    resp = await api.post(SCORER, json={"inputs": [ROW]})
    assert resp.status_code == 503


async def test_rate_limit_per_token(api, auth):
    statuses = []
    for _ in range(7):
        resp = await api.post(SCORER, json={"inputs": [ROW]}, headers=auth)
        statuses.append(resp.status_code)
    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.headers["x-ratelimit-limit"] == "5"


async def test_predict_happy_path(api, auth, loader):
    resp = await api.post(SCORER, json={"inputs": [ROW, {"income": 200_000}]}, headers=auth)
    assert resp.status_code == 200
    assert resp.headers["x-request-id"]
    assert resp.json() == {
        "predictions": [0.5, 1.0],
        "model": "sys-002-credit-scorer",
        "version": "1",
    }
    # Cached after the first load.
    await api.post(SCORER, json={"inputs": [ROW]}, headers=auth)
    assert loader.calls == ["sys-002-credit-scorer"]


@pytest.mark.parametrize(
    ("row", "field", "error"),
    [
        ({"age": 40}, "income", "missing"),
        ({"income": "lots"}, "income", "expected double"),
        ({"income": 1.0, "age": 4.5}, "age", "expected long"),
        ({"income": 1.0, "postcode": "11523"}, "postcode", "unknown field"),
    ],
)
async def test_predict_validates_against_signature(api, auth, row, field, error):
    resp = await api.post(SCORER, json={"inputs": [row]}, headers=auth)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert {"row": 0, "field": field, "error": error} in detail["errors"]


@pytest.mark.parametrize("body", [{"inputs": []}, {"rows": [ROW]}, {"inputs": "x"}])
async def test_predict_rejects_malformed_body(api, auth, body):
    resp = await api.post(SCORER, json=body, headers=auth)
    assert resp.status_code == 422


async def test_unknown_model_is_404(api, auth):
    resp = await api.post("/v1/models/nope/predict", json={"inputs": [ROW]}, headers=auth)
    assert resp.status_code == 404


async def test_missing_model_is_503_and_retried(api, auth, loader):
    for _ in range(2):
        resp = await api.post(
            "/v1/models/sys-003-benefits-triage/predict",
            json={"inputs": [{"x": 1}]},
            headers=auth,
        )
        assert resp.status_code == 503
        assert "not available yet" in resp.json()["detail"]
        assert resp.headers["retry-after"]
    assert loader.calls == ["sys-003-benefits-triage"] * 2


async def test_sys001_pipeline_chains_parser_and_ranker(api, auth):
    resp = await api.post(
        "/v1/systems/sys-001/screen",
        json={
            "inputs": [
                {"years_experience": 10, "education": "msc"},
                {"years_experience": 1, "education": "none"},
            ]
        },
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["features"] == [
        {"years_experience": 10.0, "has_degree": 1},
        {"years_experience": 1.0, "has_degree": 0},
    ]
    assert body["predictions"] == [
        {"shortlist": 1, "proba": 1.0},
        {"shortlist": 0, "proba": 0.08},
    ]
    assert body["stages"] == [
        {"model": "sys-001-cv-parser", "version": "3"},
        {"model": "sys-001-cv-ranker", "version": "7"},
    ]

    # The ranker alone, on the intermediate features: same answer.
    alone = await api.post(
        "/v1/models/sys-001-cv-ranker/predict", json={"inputs": body["features"]}, headers=auth
    )
    assert alone.json()["predictions"] == body["predictions"]


async def test_sys001_pipeline_validates_raw_fields(api, auth):
    resp = await api.post(
        "/v1/systems/sys-001/screen", json={"inputs": [{"education": "msc"}]}, headers=auth
    )
    assert resp.status_code == 422
