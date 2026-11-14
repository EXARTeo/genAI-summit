"""HTTP API: auth gate, rate limit, ingest runs and document reads."""

from __future__ import annotations

import httpx
import pytest

from core.security.rate_limit import backend as rate_limit_backend
from core.settings import settings
from utils.ingest import wait_all

CATALOG = """
sources:
  - id: act
    title: Act
    kind: regulation
    binding: true
    fetcher: cellar
    celex: 32024R1689
    formats: [xhtml]
"""
CELLAR = "https://publications.europa.eu/resource/celex/32024R1689"


async def test_health_needs_no_secret(api):
    resp = await api.get("/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"


async def test_secret_gate(api, monkeypatch, write_catalog):
    write_catalog(CATALOG)
    monkeypatch.setattr(settings.security, "internal_secret", _secret("s3cret"))
    assert (await api.get("/v1/sources")).status_code == 401
    bad = await api.get("/v1/sources", headers={"X-Internal-Secret": "nope"})
    assert bad.status_code == 401
    ok = await api.get("/v1/sources", headers={"X-Internal-Secret": "s3cret"})
    assert ok.status_code == 200 and ok.json()["items"][0]["id"] == "act"


async def test_fail_closed_outside_development(api, monkeypatch, write_catalog):
    write_catalog(CATALOG)
    monkeypatch.setattr(settings.app, "env", "production")
    assert (await api.get("/v1/sources")).status_code == 503


async def test_ingest_run_and_documents(api, web, write_catalog):
    write_catalog(CATALOG)
    web.add(
        CELLAR,
        lambda r: httpx.Response(200, content=b"<html><body><p>Article 1 text</p></body></html>"),
    )
    resp = await api.post("/v1/ingest", json={"source_ids": ["act"]})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    await wait_all()

    run = (await api.get(f"/v1/ingest/{run_id}")).json()
    assert run["status"] == "done" and run["results"][0]["status"] == "new"

    sources = (await api.get("/v1/sources")).json()["items"]
    assert sources[0]["latest"]["status"] == "new"
    docs = (await api.get("/v1/documents")).json()["items"]
    assert docs[0]["doc_id"] == "act" and docs[0]["has_text"] is True
    detail = (await api.get("/v1/documents/act")).json()
    assert detail["versions"][0]["version"] == 1
    text = (await api.get("/v1/documents/act/text", params={"version": 1})).json()
    assert "Article 1 text" in text["text"]

    assert (await api.get("/v1/documents/nope")).status_code == 404
    assert (await api.get("/v1/documents/act/text", params={"version": 9})).status_code == 404
    assert (await api.get("/v1/ingest/unknown-run")).status_code == 404


async def test_ingest_unknown_source_is_422(api, write_catalog):
    write_catalog(CATALOG)
    resp = await api.post("/v1/ingest", json={"source_ids": ["nope"]})
    assert resp.status_code == 422


async def test_ingest_rate_limited(api, write_catalog, web, monkeypatch):
    write_catalog(CATALOG)
    web.add(CELLAR, lambda r: httpx.Response(200, content=b"<html><body>x</body></html>"))
    rate_limit_backend.reset()
    codes = []
    for _ in range(settings.rate_limit.ingest_max_attempts + 1):
        codes.append((await api.post("/v1/ingest", json={})).status_code)
    await wait_all()
    assert codes[-1] == 429 and set(codes[:-1]) == {202}


def _secret(value: str):
    from pydantic import SecretStr

    return SecretStr(value)


@pytest.fixture(autouse=True)
def _reset_limits():
    rate_limit_backend.reset()
