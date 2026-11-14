"""Hashing (idempotency) and MLflow logging/registration of a case's models."""

import hashlib
import tempfile
from pathlib import Path

import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.models import infer_signature

from seedlib.spec import CaseResult, ModelSpec, system_card

ALIAS = "champion"
SEED_ROOT = Path(__file__).resolve().parent.parent
CODE_PATHS = ["seedlib", "seedmodels", "seed.py", "requirements.txt"]
MODEL_CODE = SEED_ROOT / "seedmodels"

# Pinned to the model gateway's versions (product/model-gateway/requirements.txt).
PIP_REQUIREMENTS = [
    "mlflow-skinny==3.18.0",
    "scikit-learn==1.9.1",
    "pandas==3.1.1",
    "numpy==2.5.4",
    "scipy==1.18.1",
    "cloudpickle==3.1.2",
]


def _files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def seed_hash(case_dir: Path) -> str:
    """sha256 over the case folder and the seed code (line endings normalised, so Windows
    and Linux checkouts hash the same)."""
    digest = hashlib.sha256()
    roots = [(case_dir, case_dir)] + [(SEED_ROOT / p, SEED_ROOT) for p in CODE_PATHS]
    for root, base in roots:
        for path in _files(root):
            digest.update(path.relative_to(base).as_posix().encode())
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def is_up_to_date(client: MlflowClient, names: list[str], expected: str) -> bool:
    for name in names:
        try:
            version = client.get_model_version_by_alias(name, ALIAS)
        except MlflowException:
            return False
        if version.tags.get("seed_hash") != expected:
            return False
    return True


def _log_model(spec: ModelSpec, card: dict, digest: str, client: MlflowClient) -> str:
    signature = infer_signature(spec.input_example, spec.output_example)
    tags = {
        "system_id": card["id"],
        "annex_basis": card.get("annex_basis", ""),
        "intended_purpose": " ".join(str(card.get("intended_purpose", "")).split()),
        "risk_class": card.get("risk_class", ""),
        "plugin": f"{card['id']}.{spec.plugin}",
        "seed_hash": digest,
        "data_policy": "synthetic_only",
    }
    with mlflow.start_run(run_name=spec.name) as run:
        mlflow.set_tags(tags)
        mlflow.log_params(spec.params)
        mlflow.log_metrics({k: float(v) for k, v in spec.metrics.items() if pd.notna(v)})
        for ds in spec.datasets:
            dataset = mlflow.data.from_pandas(ds.frame, name=ds.name, targets=ds.targets)
            mlflow.log_input(dataset, context=ds.context)
        with tempfile.TemporaryDirectory() as tmp:
            for fname, text in spec.artifacts.items():
                (Path(tmp) / fname).write_text(text, encoding="utf-8")
            if spec.artifacts:
                mlflow.log_artifacts(tmp, artifact_path="evaluation")
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=spec.python_model,
            signature=signature,
            input_example=spec.input_example,
            code_paths=[str(MODEL_CODE)],
            pip_requirements=PIP_REQUIREMENTS,
            registered_model_name=spec.name,
        )
        version = str(info.registered_model_version)
    client.update_registered_model(spec.name, description=spec.description)
    client.set_registered_model_tag(spec.name, "system_id", card["id"])
    client.update_model_version(spec.name, version, description=spec.description)
    for key, value in tags.items():
        client.set_model_version_tag(spec.name, version, key, value)
    client.set_model_version_tag(spec.name, version, "run_id", run.info.run_id)
    client.set_registered_model_alias(spec.name, ALIAS, version)
    return version


def register_case(case_dir: Path, result: CaseResult, digest: str) -> dict[str, str]:
    """Log every model of a case into experiment ``seed/<SYS>``; return name -> version."""
    client = MlflowClient()
    card = system_card(case_dir)
    mlflow.set_experiment(f"seed/{result.system_id}")
    return {spec.name: _log_model(spec, card, digest, client) for spec in result.models}
