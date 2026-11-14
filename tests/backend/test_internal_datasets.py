"""``PUT /internal/audits/{id}/datasets/public/{slug}/{name}``: the agent stores a
human-approved public reference dataset in the system folder, nothing else."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from core.settings import settings


@pytest.fixture
def internal_secret(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr("s3cret"))
    return {"X-Internal-Secret": "s3cret", "X-Agent-Name": "data", "X-Run-Id": "run-1"}


async def _audit(client) -> dict:
    assert (
        await client.post("/v1/systems", json={"id": "SYS-002", "name": "x"})
    ).status_code == 201
    response = await client.post("/v1/systems/SYS-002/audits", json={})
    assert response.status_code == 201, response.text
    return response.json()


async def test_stores_public_dataset_files_under_the_prefix(client, internal_secret):
    audit = await _audit(client)
    base = f"/internal/audits/{audit['id']}/datasets/public/openml-31-credit-g"
    put = await client.put(
        f"{base}/data.csv", json={"content": "a,b\n1,2\n"}, headers=internal_secret
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["changed"] is True
    assert body["file"]["path"] == "datasets/public/openml-31-credit-g/data.csv"
    assert body["file"]["createdBy"] == "agent:data"
    again = await client.put(
        f"{base}/data.csv", json={"content": "a,b\n1,2\n"}, headers=internal_secret
    )
    assert again.json()["changed"] is False

    tree = await client.get("/v1/systems/SYS-002/files?prefix=datasets/public")
    assert [f["path"] for f in tree.json()] == ["datasets/public/openml-31-credit-g/data.csv"]


async def test_refuses_other_names_slugs_and_callers(client, internal_secret):
    audit = await _audit(client)
    base = f"/internal/audits/{audit['id']}/datasets/public"
    bad_name = await client.put(f"{base}/ok/run.py", json={"content": "x"}, headers=internal_secret)
    assert bad_name.status_code == 400
    bad_slug = await client.put(
        f"{base}/..%2Fx/data.csv", json={"content": "x"}, headers=internal_secret
    )
    assert bad_slug.status_code in {400, 404}
    upper = await client.put(f"{base}/Bad/data.csv", json={"content": "x"}, headers=internal_secret)
    assert upper.status_code == 400
    no_secret = await client.put(f"{base}/ok/data.csv", json={"content": "x"})
    assert no_secret.status_code == 401
    missing = await client.put(
        "/internal/audits/nope/datasets/public/ok/data.csv",
        json={"content": "x"},
        headers=internal_secret,
    )
    assert missing.status_code == 404
