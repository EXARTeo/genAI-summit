"""Resolve a model in the local MLflow registry into a :class:`ModelHandle`.

``models:/<name>@<alias>``, ``models:/<name>/<version>`` or ``runs:/<id>/model``.
The handle carries the loaded pyfunc model, its input signature and what the
registry knows about it (version, flavor, run metrics/tags, dataset lineage), so
synthkit, run-tests and the model gateway all read the same facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_MODELS_URI = re.compile(r"^models:/(?P<name>[^/@]+)(?:@(?P<alias>[^/]+)|/(?P<version>\d+))?$")


@dataclass(frozen=True, slots=True)
class InputColumn:
    name: str
    type: str  # MLflow DataType name: string, long, integer, double, float, boolean, ...
    required: bool = True


@dataclass(slots=True)
class ModelHandle:
    uri: str
    name: str
    version: str | None
    model: Any  # anything with .predict(pandas.DataFrame)
    input_columns: list[InputColumn] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def predict(self, frame):
        return self.model.predict(frame)

    @property
    def input_types(self) -> dict[str, str]:
        return {c.name: c.type for c in self.input_columns or []}


def input_columns(pyfunc_model: Any) -> list[InputColumn] | None:
    """The model's named input signature, or None when it was logged without one."""
    meta = getattr(pyfunc_model, "metadata", None)
    schema = meta.get_input_schema() if meta is not None else None
    if schema is None or not schema.has_input_names():
        return None
    cols = []
    for spec in schema.inputs:
        dtype = getattr(spec, "type", None)
        type_name = getattr(dtype, "name", None) or str(dtype).split(".")[-1]
        cols.append(InputColumn(spec.name, type_name.lower(), getattr(spec, "required", True)))
    return cols


def _registry_metadata(client: Any, name: str, version: Any) -> dict[str, Any]:
    """Version, tags, run metrics and dataset lineage; best effort (never raises)."""
    meta: dict[str, Any] = {"version": str(version.version), "tags": dict(version.tags or {})}
    run_id = getattr(version, "run_id", None)
    meta["run_id"] = run_id
    if not run_id:
        return meta
    try:
        run = client.get_run(run_id)
    except Exception:  # noqa: BLE001 - lineage is optional
        return meta
    meta["metrics"] = dict(run.data.metrics)
    meta["params"] = dict(run.data.params)
    meta["datasets"] = [
        {
            "name": d.dataset.name,
            "digest": d.dataset.digest,
            "context": next((t.value for t in d.tags if t.key == "mlflow.data.context"), None),
        }
        for d in (run.inputs.dataset_inputs if run.inputs else [])
    ]
    return meta


def load_mlflow_model(uri: str, *, tracking_uri: str | None = None) -> ModelHandle:
    """Load a pyfunc model and resolve its registry version (if it is a ``models:/`` uri)."""
    # Imported here: mlflow is heavy and only this adapter needs it.
    import mlflow  # noqa: PLC0415
    import mlflow.pyfunc  # noqa: PLC0415
    from mlflow.tracking import MlflowClient  # noqa: PLC0415

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    name, version, metadata = uri, None, {}
    match = _MODELS_URI.match(uri)
    if match:
        client = MlflowClient()
        name = match["name"]
        if match["alias"]:
            mv = client.get_model_version_by_alias(name, match["alias"])
        elif match["version"]:
            mv = client.get_model_version(name, match["version"])
        else:
            mv = None
        if mv is not None:
            version = str(mv.version)
            metadata = _registry_metadata(client, name, mv)
    model = mlflow.pyfunc.load_model(uri)
    info = getattr(model, "metadata", None)
    if info is not None:
        metadata["flavors"] = sorted((getattr(info, "flavors", None) or {}).keys())
        metadata["model_uuid"] = getattr(info, "model_uuid", None)
    return ModelHandle(uri, name, version, model, input_columns(model), metadata)


def list_versions(name: str, *, tracking_uri: str | None = None) -> list[dict[str, Any]]:
    """All registry versions of ``name`` with aliases and tags, newest first."""
    import mlflow  # noqa: PLC0415
    from mlflow.tracking import MlflowClient  # noqa: PLC0415

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    versions = MlflowClient().search_model_versions(f"name = '{name}'")
    out = [
        {
            "version": str(v.version),
            "aliases": list(getattr(v, "aliases", []) or []),
            "run_id": v.run_id,
            "tags": dict(v.tags or {}),
        }
        for v in versions
    ]
    return sorted(out, key=lambda v: int(v["version"]), reverse=True)
