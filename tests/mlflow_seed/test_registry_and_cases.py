"""Registration against a local sqlite MLflow store, idempotency hash, case folders."""

import shutil

import mlflow
import pytest
import yaml
from conftest import built
from mlflow import MlflowClient

import seed
from seedlib import registry

CONTRACT = {
    "sys-001-cv-parser",
    "sys-001-cv-ranker",
    "sys-002-credit-scorer",
    "sys-003-benefits-triage",
}
REQUIRED = ["system-card.yaml", "architecture.yaml", "gaps.yaml", "evidence/README.md"]
PLUGIN_FILES = [
    "plugin.yaml",
    "README.md",
    "data/data-dictionary.yaml",
    "data/training-data.md",
    "data/business-rules.md",
]


def test_seed_hash_is_stable_and_line_ending_insensitive(tmp_path, cases_dir):
    case = tmp_path / "SYS-003"
    shutil.copytree(cases_dir / "SYS-003", case)
    first = registry.seed_hash(case)
    assert registry.seed_hash(case) == first
    card = case / "system-card.yaml"
    card.write_bytes(card.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert registry.seed_hash(case) == first
    card.write_text(card.read_text(encoding="utf-8") + "# change\n", encoding="utf-8")
    assert registry.seed_hash(case) != first


def test_register_load_and_idempotency(tmp_path, cases_dir, monkeypatch):
    tracking = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", tracking)
    mlflow.set_tracking_uri(tracking)
    result = built("SYS-003")
    client = MlflowClient()
    # Keep artifacts in tmp_path (the default would be ./mlruns in the working directory).
    client.create_experiment("seed/SYS-003", artifact_location=(tmp_path / "art").as_uri())
    assert not registry.is_up_to_date(client, ["sys-003-benefits-triage"], "abc")
    versions = registry.register_case(cases_dir / "SYS-003", result, "abc")
    assert versions == {"sys-003-benefits-triage": "1"}
    assert registry.is_up_to_date(client, ["sys-003-benefits-triage"], "abc")
    assert not registry.is_up_to_date(client, ["sys-003-benefits-triage"], "other")

    mv = client.get_model_version_by_alias("sys-003-benefits-triage", "champion")
    assert mv.tags["system_id"] == "SYS-003"
    assert mv.tags["annex_basis"] == "Annex III 5(a)"
    assert mv.tags["seed_hash"] == "abc"
    run = client.get_run(mv.run_id)
    assert run.data.metrics["robustness.crash_rate"] > 0
    assert {i.dataset.name for i in run.inputs.dataset_inputs} >= {"sys-003-train", "sys-003-test"}
    model = mlflow.pyfunc.load_model("models:/sys-003-benefits-triage@champion")
    assert model.metadata.signature is not None
    out = model.predict(result.models[0].input_example)
    assert list(out.columns) == ["eligible", "triage", "priority_score", "estimated_benefit_eur"]


@pytest.mark.parametrize("system_id", ["SYS-001", "SYS-002", "SYS-003", "SYS-004"])
def test_case_folder_is_complete(cases_dir, system_id):
    case = cases_dir / system_id
    for rel in REQUIRED:
        assert (case / rel).is_file(), rel
    assert (case / "_answer-key" / "expected-findings.yaml").is_file()
    card = yaml.safe_load((case / "system-card.yaml").read_text(encoding="utf-8"))
    assert card["id"] == system_id
    plugins = [p for p in (case / "plugins").iterdir() if p.is_dir()]
    assert plugins
    for plugin in plugins:
        for rel in PLUGIN_FILES:
            assert (plugin / rel).is_file(), f"{plugin.name}/{rel}"
        access = yaml.safe_load((plugin / "plugin.yaml").read_text(encoding="utf-8"))["access"]
        if access["type"] == "mlflow_model":
            name = access["uri"].removeprefix("models:/").removesuffix("@champion")
            assert name in CONTRACT
            assert f"http://model-gateway:8000/v1/models/{name}/predict" in (
                plugin / "plugin.yaml"
            ).read_text(encoding="utf-8")
        else:
            assert access["type"] == "llm_chat"
            assert access["url"] == "http://model-gateway:8000/v1/chat/sys-004"


def test_findings_cite_requirements(cases_dir):
    for key in cases_dir.glob("SYS-*/_answer-key/expected-findings.yaml"):
        findings = yaml.safe_load(key.read_text(encoding="utf-8"))["findings"]
        assert findings
        for f in findings:
            assert all(r.startswith("REQ.AIA.") for r in f["requirements"]), f["id"]


def test_export_hides_answer_keys(tmp_path, cases_dir):
    dirs = seed.case_dirs(cases_dir, None)
    seed.export_cases(cases_dir, tmp_path, dirs)
    assert (tmp_path / "systems" / "SYS-001" / "system-card.yaml").is_file()
    assert not list((tmp_path / "systems").rglob("_answer-key"))
    assert not list((tmp_path / "systems").rglob("expected-findings.yaml"))
    assert (tmp_path / "answer-keys" / "SYS-001" / "expected-findings.yaml").is_file()
