"""Plugins: the system graph from architecture.yaml, form defaults from the graph + a mocked
MLflow registry, and saving plugin.yaml (validation, no inline secrets, architecture link)."""

from __future__ import annotations

import httpx
import pytest
import yaml

from utils import plugins as plugins_util

BASE = "/v1/systems/SYS-001"

ARCH = """
system: SYS-001
components:
  - id: SYS-001.cv-parser
    plugin: plugins/cv-parser
    kind: rule_based_parser
    model: models:/sys-001-cv-parser@champion
  - id: SYS-001.cv-ranker
    kind: ml_classifier
    model: models:/sys-001-cv-ranker@champion
  - id: SYS-001.recruiter-ui
    kind: human_review
edges:
  - {from: SYS-001.cv-parser, to: SYS-001.cv-ranker}
  - {from: SYS-001.cv-ranker, to: SYS-001.recruiter-ui}
end_to_end_entry: SYS-001.cv-parser
"""

PARSER = """
id: SYS-001.cv-parser
name: CV parser
access: {type: mlflow_model, uri: "models:/sys-001-cv-parser@champion"}
"""

MLMODEL = """
flavors: {python_function: {}}
signature:
  inputs: >-
    [{"type": "string", "name": "postcode_region"},
    {"type": "long", "name": "years_experience"}]
  outputs: '[{"type": "long", "name": "shortlist"}, {"type": "double", "name": "proba"}]'
"""


def _registry(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/2.0/mlflow/registered-models/alias":
        if request.url.params["name"] != "sys-001-cv-ranker":
            return httpx.Response(404, json={"error_code": "RESOURCE_DOES_NOT_EXIST"})
        return httpx.Response(
            200,
            json={
                "model_version": {
                    "version": "3",
                    "run_id": "run-1",
                    "description": "Rank applicants for engineering roles",
                    "tags": [{"key": "system_id", "value": "SYS-001"}],
                }
            },
        )
    if path == "/api/2.0/mlflow/model-versions/get-download-uri":
        return httpx.Response(
            200, json={"artifact_uri": "mlflow-artifacts:/1/models/m-abc/artifacts"}
        )
    if path == "/api/2.0/mlflow-artifacts/artifacts/1/models/m-abc/artifacts/MLmodel":
        return httpx.Response(200, text=MLMODEL)
    return httpx.Response(404)


@pytest.fixture
def mlflow(monkeypatch):
    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://mlflow:5000", transport=httpx.MockTransport(_registry)
        )

    monkeypatch.setattr(plugins_util, "mlflow_client", client)


async def _seed(client) -> None:
    assert (
        await client.post("/v1/systems", json={"id": "SYS-001", "name": "CV"})
    ).status_code == 201
    for path, text in (("architecture.yaml", ARCH), ("plugins/cv-parser/plugin.yaml", PARSER)):
        assert (await client.put(f"{BASE}/files/{path}", json={"content": text})).status_code == 201


async def test_graph_joins_components_and_plugins(client):
    await _seed(client)
    graph = (await client.get(f"{BASE}/plugins")).json()
    comps = {c["id"]: c for c in graph["components"]}
    assert comps["SYS-001.cv-parser"]["configured"] is True
    assert comps["SYS-001.cv-parser"]["name"] == "CV parser"
    assert comps["SYS-001.cv-ranker"]["configured"] is False
    assert comps["SYS-001.cv-ranker"]["testable"] is True
    assert comps["SYS-001.recruiter-ui"]["testable"] is False
    assert len(graph["edges"]) == 2
    assert graph["edges"][0] == {
        "source": "SYS-001.cv-parser",
        "target": "SYS-001.cv-ranker",
        "data": None,
    }
    assert "cv-parser" in graph["plugins"]
    assert (await client.get("/v1/systems/SYS-404/plugins")).status_code == 404


async def test_defaults_come_from_graph_and_mlflow(client, mlflow):
    await _seed(client)
    out = (
        await client.get(f"{BASE}/plugins/defaults", params={"component": "SYS-001.cv-ranker"})
    ).json()
    assert out["name"] == "cv-ranker"
    assert out["existing"] is None
    assert out["mlflow"]["status"] == "ok"
    assert out["mlflow"]["version"] == "3"
    d = out["defaults"]
    assert d["access"]["uri"] == "models:/sys-001-cv-ranker@champion"
    assert d["access"]["rest_url"] == "/v1/models/sys-001-cv-ranker/predict"
    assert d["access"]["auth"]["secret_ref"] == "env://MODEL_GATEWAY_TOKEN"  # noqa: S105
    assert d["placement"]["position"] == "2 of 3"
    assert d["placement"]["upstream"] == ["SYS-001.cv-parser"]
    assert d["placement"]["downstream"] == ["SYS-001.recruiter-ui"]
    assert d["io"]["output"] == {
        "type": "binary_classification",
        "positive_label": 1,
        "label_field": "shortlist",
        "score_field": "proba",
    }
    assert [f["name"] for f in d["io"]["input_fields"]] == ["postcode_region", "years_experience"]
    assert d["expected_behaviour"]["task"] == "Rank applicants for engineering roles"


async def test_defaults_survive_an_unknown_model(client, mlflow):
    await _seed(client)
    out = (
        await client.get(f"{BASE}/plugins/defaults", params={"component": "SYS-001.cv-parser"})
    ).json()
    assert out["mlflow"]["status"] == "not_found"
    assert out["existing"]["name"] == "CV parser"
    missing = await client.get(f"{BASE}/plugins/defaults", params={"component": "SYS-001.nope"})
    assert missing.status_code == 404


async def test_save_plugin_links_the_component(client):
    await _seed(client)
    card = {
        "name": "Candidate ranker",
        "access": {
            "type": "mlflow_model",
            "uri": "models:/sys-001-cv-ranker@champion",
            "auth": {"type": "bearer", "secret_ref": "env://MODEL_GATEWAY_TOKEN"},
            "limits": {"rps": 5, "timeout_s": 10},
        },
    }
    res = await client.put(
        f"{BASE}/plugins/cv-ranker", json={"card": card, "component": "SYS-001.cv-ranker"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"] == "plugins/cv-ranker/plugin.yaml"
    assert body["architecture_updated"] is True
    saved = (
        await client.get(f"{BASE}/files/plugins/cv-ranker/plugin.yaml", params={"format": "json"})
    ).json()
    parsed = yaml.safe_load(saved["text"])
    assert parsed["id"] == "SYS-001.cv-ranker"
    assert parsed["system"] == "SYS-001"
    graph = (await client.get(f"{BASE}/plugins")).json()
    ranker = next(c for c in graph["components"] if c["id"] == "SYS-001.cv-ranker")
    assert ranker["configured"] is True and ranker["plugin"] == "cv-ranker"

    again = await client.put(
        f"{BASE}/plugins/cv-ranker", json={"card": card, "component": "SYS-001.cv-ranker"}
    )
    assert again.json()["changed"] is False
    assert again.json()["architecture_updated"] is False


@pytest.mark.parametrize(
    ("access", "needle"),
    [
        ({"type": "magic"}, "access.type"),
        ({"type": "mlflow_model", "uri": "s3://x"}, "access.uri"),
        ({"type": "rest"}, "access.url"),
        ({"type": "rest", "url": "/v1/x", "auth": {"token": "abc"}}, "never put a secret"),
        ({"type": "rest", "url": "/v1/x", "auth": {"secret_ref": "vault://x"}}, "secret_ref"),
        ({"type": "rest", "url": "/v1/x", "limits": {"rps": -1}}, "access.limits"),
    ],
)
async def test_save_plugin_rejects_bad_cards(client, access, needle):
    await _seed(client)
    res = await client.put(f"{BASE}/plugins/x", json={"card": {"name": "X", "access": access}})
    assert res.status_code == 422
    assert needle in res.text, res.text


async def test_save_plugin_rejects_a_bad_name(client):
    await _seed(client)
    card = {"name": "X", "access": {"type": "rest", "url": "/v1/x"}}
    assert (await client.put(f"{BASE}/plugins/Bad_Name", json={"card": card})).status_code == 422


async def test_engineer_builds_the_pipeline_from_an_empty_system(client):
    """A PM registers a system with docs only; the engineer adds the graph and the plugins."""
    assert (
        await client.post("/v1/systems", json={"id": "SYS-009", "name": "New"})
    ).status_code == 201
    base = "/v1/systems/SYS-009"
    assert (await client.get(f"{base}/plugins")).json()["components"] == []

    step = await client.post(
        f"{base}/plugins/components", json={"name": "Intake form", "kind": "upstream_system"}
    )
    assert step.status_code == 201, step.text
    assert step.json()["components"][0]["id"] == "SYS-009.intake-form"
    assert step.json()["components"][0]["testable"] is False
    dup = await client.post(f"{base}/plugins/components", json={"name": "Intake form"})
    assert dup.status_code == 409

    card = {
        "name": "Scorer",
        "access": {"type": "mlflow_model", "uri": "models:/sys-009-scorer@champion"},
    }
    res = await client.put(
        f"{base}/plugins/scorer", json={"card": card, "upstream": ["SYS-009.intake-form"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["architecture_updated"] is True
    assert res.json()["card"]["placement"]["upstream"] == ["SYS-009.intake-form"]
    assert res.json()["card"]["placement"]["position"] == "2 of 2"

    review = await client.post(
        f"{base}/plugins/components",
        json={"name": "Officer review", "kind": "human_review", "upstream": ["SYS-009.scorer"]},
    )
    graph = review.json()
    assert {(e["source"], e["target"]) for e in graph["edges"]} == {
        ("SYS-009.intake-form", "SYS-009.scorer"),
        ("SYS-009.scorer", "SYS-009.officer-review"),
    }
    scorer = next(c for c in graph["components"] if c["id"] == "SYS-009.scorer")
    assert scorer["configured"] is True

    gone = await client.delete(f"{base}/plugins/components/SYS-009.officer-review")
    assert gone.status_code == 200
    assert len(gone.json()["edges"]) == 1
    assert (await client.delete(f"{base}/plugins/components/SYS-009.nope")).status_code == 404


async def test_fill_example_from_the_seed_case_copies_its_files(client, tmp_path, monkeypatch):
    """A model with a seed plugin: the defaults carry it as `example`; saving with
    copy_example_files copies its data dictionary and docs into the new plugin."""
    seed = tmp_path / "systems" / "SYS-001" / "plugins" / "cv-ranker"
    (seed / "data").mkdir(parents=True)
    (seed / "plugin.yaml").write_text(
        "id: SYS-001.cv-ranker\nname: Candidate ranker\n"
        "access: {type: mlflow_model, uri: 'models:/sys-001-cv-ranker@champion'}\n"
        "expected_behaviour: {task: Rank applicants, must: [score in 0..1]}\n",
        encoding="utf-8",
    )
    (seed / "data" / "data-dictionary.yaml").write_text(
        "version: 2\nfields: {}\n", encoding="utf-8"
    )
    monkeypatch.setattr(plugins_util.settings.workspace, "seed_cases_dir", str(tmp_path))
    await _seed(client)

    out = (
        await client.get(f"{BASE}/plugins/defaults", params={"component": "SYS-001.cv-ranker"})
    ).json()
    assert out["example"]["name"] == "Candidate ranker"
    assert out["example_files"] == ["data/data-dictionary.yaml"]

    card = {**out["example"], "access": out["example"]["access"]}
    res = await client.put(
        f"{BASE}/plugins/ranker",
        json={"card": card, "component": "SYS-001.cv-ranker", "copy_example_files": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["files_copied"] == ["plugins/ranker/data/data-dictionary.yaml"]
    copied = await client.get(f"{BASE}/files/plugins/ranker/data/data-dictionary.yaml")
    assert copied.status_code == 200
    again = await client.put(
        f"{BASE}/plugins/ranker",
        json={"card": card, "component": "SYS-001.cv-ranker", "copy_example_files": True},
    )
    assert again.json()["files_copied"] == []
    none = (
        await client.get(f"{BASE}/plugins/defaults", params={"model": "models:/other@champion"})
    ).json()
    assert none["example"] is None and none["example_files"] == []
