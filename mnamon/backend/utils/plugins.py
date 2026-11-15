"""Plugins: the wrapper around one model of a system (docs/services/backend-systems.md § Plugins).

* ``system_graph``: the system's components and edges from ``architecture.yaml``, each joined
  with its plugin (``plugins/<name>/plugin.yaml``); a plugin no component names is shown as a
  standalone box.
* ``plugin_defaults``: a complete plugin card for one component, built from the graph
  (placement) and the local MLflow registry (version, description, signature). The form shows
  these values in grey; the engineer overrides only what differs.
* ``save_plugin``: validates a card (no inline secrets, a known access type, a target) and
  writes it as a new version of ``plugin.yaml``; links the component in ``architecture.yaml``.

The plugin stays a file in the system folder because the agents read it from there
(``load_context``, ``pin``, synthkit's target); the Folder tab just does not show ``plugins/``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import httpx
import yaml
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.settings import settings
from schema.plugins import PLUGIN_NAME_PATTERN, MlflowModelInfo
from utils.workspace import get_file, list_tree, put_file, system_namespace

logger = get_logger(__name__)

ARCHITECTURE = "architecture.yaml"
ACCESS_TYPES = ("mlflow_model", "rest", "llm_chat", "batch_file", "dataset_only")
#: Used when the card says nothing: the model gateway's limits are 5 rps per token.
DEFAULT_LIMITS = {"rps": 5, "max_requests": 500, "timeout_s": 10}
DEFAULT_SECRET_REF = "env://MODEL_GATEWAY_TOKEN"  # noqa: S105 - an env var name, not a secret
DEFAULT_ENVIRONMENT = "staging"

_NAME = re.compile(PLUGIN_NAME_PATTERN)
_MODEL_URI = re.compile(r"^models:/([^@/]+)(?:@([\w-]+)|/(\d+))?$")
_ENV_REF = re.compile(r"^env://[A-Z_][A-Z0-9_]{0,63}$")
_PLUGIN_FILE = re.compile(r"^plugins/([^/]+)/plugin\.ya?ml$")
#: Keys that would put a credential into the dossier.
_SECRET_KEYS = re.compile(r"(token|password|passwd|secret|api[_-]?key|bearer)$", re.I)
_SCORE = re.compile(r"(proba|prob|score|probability)", re.I)
_INT_TYPES = {"long", "integer", "int", "boolean", "bool"}
_FLOAT_TYPES = {"double", "float"}


def _short(component_id: str) -> str:
    return component_id.split(".", 1)[1] if "." in component_id else component_id


def _humanize(slug: str) -> str:
    words = re.sub(r"[-_]+", " ", slug).strip()
    return words[:1].upper() + words[1:]


def _yaml(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


async def _read(db: AsyncSession, system_id: str, path: str) -> str | None:
    try:
        _, content = await get_file(db, system_namespace(system_id), path)
    except HTTPException:
        return None
    return content.decode("utf-8", errors="replace")


async def read_plugins(db: AsyncSession, system_id: str) -> dict[str, dict[str, Any]]:
    """Every plugin.yaml of the system, parsed, keyed by folder name."""
    out: dict[str, dict[str, Any]] = {}
    for row in await list_tree(db, system_namespace(system_id), "plugins"):
        match = _PLUGIN_FILE.match(row.path)
        if match:
            out[match.group(1)] = _yaml(await _read(db, system_id, row.path))
    return out


def _plugin_folder(ref: Any) -> str | None:
    """``plugins/cv-ranker`` → ``cv-ranker``."""
    if not ref:
        return None
    parts = str(ref).strip("/").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "plugins" else parts[-1]


async def system_graph(db: AsyncSession, system_id: str) -> dict[str, Any]:
    arch = _yaml(await _read(db, system_id, ARCHITECTURE))
    plugins = await read_plugins(db, system_id)
    by_plugin_id = {str(card.get("id") or ""): name for name, card in plugins.items()}
    components: list[dict[str, Any]] = []
    linked: set[str] = set()
    for raw in arch.get("components") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        cid = str(raw["id"])
        folder = _plugin_folder(raw.get("plugin")) or by_plugin_id.get(cid)
        configured = bool(folder and folder in plugins)
        if configured:
            linked.add(folder)
        card = plugins.get(folder or "", {})
        components.append(
            {
                "id": cid,
                "name": str(card.get("name") or _humanize(_short(cid))),
                "kind": str(raw.get("kind") or ""),
                "model": raw.get("model") or (card.get("access") or {}).get("uri"),
                "note": raw.get("note"),
                "plugin": folder if configured else (folder or None),
                "configured": configured,
                "testable": bool(raw.get("model") or raw.get("plugin") or configured),
            }
        )
    for folder, card in plugins.items():
        if folder in linked:
            continue
        cid = str(card.get("id") or f"{system_id}.{folder}")
        components.append(
            {
                "id": cid,
                "name": str(card.get("name") or _humanize(folder)),
                "kind": "plugin",
                "model": (card.get("access") or {}).get("uri"),
                "note": None,
                "plugin": folder,
                "configured": True,
                "testable": True,
            }
        )
    known = {c["id"] for c in components}
    edges = [
        {"from": str(e["from"]), "to": str(e["to"]), "data": e.get("data")}
        for e in arch.get("edges") or []
        if isinstance(e, dict) and e.get("from") in known and e.get("to") in known
    ]
    return {
        "system": system_id,
        "components": components,
        "edges": edges,
        "entry": arch.get("end_to_end_entry"),
        "plugins": plugins,
    }


def _order(components: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """Components in pipeline order (longest path from a source, then file order)."""
    ids = [c["id"] for c in components]
    level = dict.fromkeys(ids, 0)
    for _ in ids:
        for e in edges:
            level[e["to"]] = max(level[e["to"]], level[e["from"]] + 1)
    return sorted(ids, key=lambda i: (level[i], ids.index(i)))


def _placement(graph: dict[str, Any], component_id: str | None) -> dict[str, Any]:
    if not component_id or component_id not in {c["id"] for c in graph["components"]}:
        return {"kind": "standalone"}
    names = {c["id"]: c["name"] for c in graph["components"]}
    order = _order(graph["components"], graph["edges"])
    placement: dict[str, Any] = {
        "kind": "pipeline_stage" if len(order) > 1 else "standalone",
        "position": f"{order.index(component_id) + 1} of {len(order)}",
        "upstream": [e["from"] for e in graph["edges"] if e["to"] == component_id],
        "downstream": [e["to"] for e in graph["edges"] if e["from"] == component_id],
        "pipeline_summary": " → ".join(names[i] for i in order),
    }
    if graph.get("entry"):
        placement["end_to_end_entry"] = graph["entry"]
    return placement


def _signature(raw: Any) -> list[dict[str, Any]]:
    """MLmodel's ``signature.inputs`` (a JSON string) → ``[{name, type}]``."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return [
        {"name": str(col["name"]), "type": str(col.get("type") or "")}
        for col in raw
        if isinstance(col, dict) and col.get("name")
    ]


def mlflow_client() -> httpx.AsyncClient:
    """The registry client (a seam for tests)."""
    return httpx.AsyncClient(
        base_url=settings.mlflow.tracking_uri.rstrip("/"), timeout=settings.mlflow.timeout_seconds
    )


async def mlflow_model_info(uri: str | None) -> MlflowModelInfo:
    """Resolve ``models:/<name>@<alias>`` (or ``/<version>``) in the local registry: version,
    description, tags and the signature from the MLmodel artifact. Never raises."""
    match = _MODEL_URI.match(uri or "")
    if not match:
        return MlflowModelInfo(status="not_mlflow")
    name, alias, version = match.group(1), match.group(2), match.group(3)
    info = MlflowModelInfo(status="ok", name=name, alias=alias, version=version)
    try:
        async with mlflow_client() as client:
            if version:
                response = await client.get(
                    "/api/2.0/mlflow/model-versions/get", params={"name": name, "version": version}
                )
            else:
                response = await client.get(
                    "/api/2.0/mlflow/registered-models/alias",
                    params={"name": name, "alias": alias or "champion"},
                )
            if response.status_code >= 400:
                info.status = "not_found"
                info.error = f"MLflow answered {response.status_code} for {uri}"
                return info
            mv = response.json().get("model_version") or {}
            info.version = str(mv.get("version") or version or "") or None
            info.run_id = mv.get("run_id") or None
            info.description = mv.get("description") or None
            info.tags = {
                str(t.get("key")): str(t.get("value"))
                for t in mv.get("tags") or []
                if isinstance(t, dict) and t.get("key")
            }
            await _read_signature(client, info)
    except httpx.HTTPError as exc:
        info.status = "unreachable"
        info.error = f"MLflow unreachable ({type(exc).__name__})"
    return info


async def _read_signature(client: httpx.AsyncClient, info: MlflowModelInfo) -> None:
    """Fill ``inputs`` / ``outputs`` from the version's MLmodel file (proxied artifacts)."""
    response = await client.get(
        "/api/2.0/mlflow/model-versions/get-download-uri",
        params={"name": info.name, "version": info.version},
    )
    artifact_uri = (response.json() or {}).get("artifact_uri", "") if response.is_success else ""
    if not artifact_uri.startswith("mlflow-artifacts:"):
        return
    path = artifact_uri.removeprefix("mlflow-artifacts:").strip("/")
    response = await client.get(f"/api/2.0/mlflow-artifacts/artifacts/{quote(path)}/MLmodel")
    if not response.is_success:
        return
    mlmodel = _yaml(response.text)
    signature = mlmodel.get("signature") or {}
    info.inputs = _signature(signature.get("inputs"))
    info.outputs = _signature(signature.get("outputs"))


def _output(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """A guess at ``io.output`` from the signature's outputs."""
    if not outputs:
        return {"type": "table"}
    score = next(
        (o["name"] for o in outputs if o["type"] in _FLOAT_TYPES and _SCORE.search(o["name"])),
        None,
    )
    label = next(
        (o["name"] for o in outputs if o["type"] in _INT_TYPES and o["name"] != score), None
    )
    if score and label:
        return {
            "type": "binary_classification",
            "positive_label": 1,
            "label_field": label,
            "score_field": score,
        }
    if len(outputs) == 1 and outputs[0]["type"] in _FLOAT_TYPES:
        return {"type": "regression", "value_field": outputs[0]["name"]}
    return {"type": "table", "columns": [o["name"] for o in outputs]}


def build_defaults(
    system_id: str,
    name: str,
    component: dict[str, Any] | None,
    graph: dict[str, Any],
    model_uri: str | None,
    info: MlflowModelInfo,
) -> dict[str, Any]:
    """A complete plugin card: graph placement + registry facts + safe defaults."""
    cid = component["id"] if component else f"{system_id}.{name}"
    access: dict[str, Any] = {"type": "mlflow_model" if model_uri else "rest"}
    if model_uri:
        access["uri"] = model_uri
    model_name = info.name or (_MODEL_URI.match(model_uri or "") or [None, None])[1]
    if model_name:
        access["rest_url"] = f"/v1/models/{model_name}/predict"
    access.update(
        environment=DEFAULT_ENVIRONMENT,
        auth={"type": "bearer", "secret_ref": DEFAULT_SECRET_REF},
        limits=dict(DEFAULT_LIMITS),
    )
    io: dict[str, Any] = {
        "input_schema": "data/data-dictionary.yaml",
        "output": _output(info.outputs),
    }
    if info.inputs:
        io["input_fields"] = info.inputs
    task = info.description or info.tags.get("intended_purpose") or ""
    return {
        "id": cid,
        "system": system_id,
        "name": component["name"] if component else _humanize(name),
        "card_version": 1,
        "placement": _placement(graph, component["id"] if component else None),
        "access": access,
        "io": io,
        "expected_behaviour": {"task": task, "must": [], "must_not": [], "known_limitations": []},
        "scenarios": {
            "data_policy": "synthetic_only",
            "generation": {"mode": "zero_shot", "seed": 42},
        },
    }


async def plugin_defaults(
    db: AsyncSession,
    system_id: str,
    *,
    component_id: str | None = None,
    model: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    graph = await system_graph(db, system_id)
    component = next((c for c in graph["components"] if c["id"] == component_id), None)
    if component_id and component is None:
        raise HTTPException(status_code=404, detail="Component not found in architecture.yaml.")
    plugin_name = name or (component and component.get("plugin")) or None
    if not plugin_name and component:
        plugin_name = _slug(_short(component["id"]))
    if not plugin_name and model:
        match = _MODEL_URI.match(model)
        plugin_name = _slug(match.group(1)) if match else None
    if not plugin_name or not _NAME.match(plugin_name):
        raise HTTPException(status_code=422, detail="Give a component, a model or a plugin name.")
    existing = graph["plugins"].get(plugin_name)
    model_uri = (
        model or (component or {}).get("model") or ((existing or {}).get("access") or {}).get("uri")
    )
    info = await mlflow_model_info(model_uri)
    return {
        "name": plugin_name,
        "component": component["id"] if component else None,
        "defaults": build_defaults(system_id, plugin_name, component, graph, model_uri, info),
        "existing": existing,
        "mlflow": info,
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:63]


def _secret_paths(node: Any, path: str = "") -> list[str]:
    """Keys that look like an inline credential (``secret_ref`` is the allowed form)."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key != "secret_ref" and _SECRET_KEYS.search(str(key)) and value not in (None, ""):
                found.append(here)
            found.extend(_secret_paths(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_secret_paths(value, f"{path}[{i}]"))
    return found


def validate_card(card: dict[str, Any]) -> list[str]:
    """Problems that would stop the agent from reaching the model; empty = valid."""
    errors: list[str] = []
    access = card.get("access")
    if not isinstance(access, dict):
        return ["access: missing"]
    kind = access.get("type")
    if kind not in ACCESS_TYPES:
        errors.append(f"access.type: one of {', '.join(ACCESS_TYPES)}")
    if kind == "mlflow_model" and not _MODEL_URI.match(str(access.get("uri") or "")):
        errors.append("access.uri: an MLflow model URI, models:/<name>@<alias> or /<version>")
    if kind in ("rest", "llm_chat") and not access.get("url"):
        errors.append("access.url: the endpoint (a /v1/... path joins MODEL_GATEWAY_URL)")
    auth = access.get("auth") or {}
    ref = auth.get("secret_ref") if isinstance(auth, dict) else None
    if ref and not _ENV_REF.match(str(ref)):
        errors.append("access.auth.secret_ref: env://NAME (the runner's environment)")
    limits = access.get("limits") or {}
    if not isinstance(limits, dict) or any(
        not isinstance(v, int | float) or isinstance(v, bool) or v < 0 for v in limits.values()
    ):
        errors.append("access.limits: non-negative numbers")
    errors.extend(
        f"{p}: never put a secret in the plugin, use auth.secret_ref" for p in _secret_paths(card)
    )
    if not str(card.get("name") or "").strip():
        errors.append("name: required")
    return errors


def _dump(card: dict[str, Any]) -> bytes:
    header = (
        "# Plugin: how the audit agent reaches this model (written by the Plugins tab).\n"
        "# Secrets are only named (auth.secret_ref: env://NAME), never stored here.\n"
    )
    body = yaml.safe_dump(card, sort_keys=False, allow_unicode=True, width=100)
    return (header + body).encode("utf-8")


async def save_plugin(
    db: AsyncSession,
    system_id: str,
    name: str,
    card: dict[str, Any],
    *,
    actor: str,
    component_id: str | None = None,
    reason: str | None = None,
    upstream: list[str] | None = None,
    downstream: list[str] | None = None,
) -> dict[str, Any]:
    if not _NAME.match(name):
        raise HTTPException(status_code=422, detail="Plugin name: lowercase letters, digits, '-'.")
    card = {k: v for k, v in card.items() if v is not None}
    card["system"] = system_id
    card.setdefault("id", component_id or f"{system_id}.{name}")
    errors = validate_card(card)
    if errors:
        raise HTTPException(status_code=422, detail="Invalid plugin: " + "; ".join(errors))
    # Link first, so a new model's placement reflects the edges it was just given.
    linked = await _link_component(
        db, system_id, name, card, component_id, actor, upstream, downstream
    )
    placement = card.get("placement") or {}
    if not placement or (
        linked and (upstream or downstream or placement.get("kind") == "standalone")
    ):
        graph = await system_graph(db, system_id)
        for comp in graph["components"]:
            if comp["id"] == card["id"]:
                comp["name"] = str(card.get("name") or comp["name"])
        card["placement"] = _placement(graph, str(card["id"]))
    path = f"plugins/{name}/plugin.yaml"
    row, changed = await put_file(
        db,
        namespace=system_namespace(system_id),
        path=path,
        content=_dump(card),
        actor=actor,
        reason=reason or "plugin configured in the Plugins tab",
    )
    return {
        "name": name,
        "path": row.path,
        "version": row.version,
        "changed": changed,
        "card": card,
        "architecture_updated": linked,
    }


async def _load_arch(db: AsyncSession, system_id: str) -> dict[str, Any]:
    arch = _yaml(await _read(db, system_id, ARCHITECTURE)) or {"system": system_id}
    arch.setdefault("system", system_id)
    if not isinstance(arch.get("components"), list):
        arch["components"] = []
    if not isinstance(arch.get("edges"), list):
        arch["edges"] = []
    return arch


async def _write_arch(
    db: AsyncSession, system_id: str, arch: dict[str, Any], actor: str, reason: str
) -> None:
    body = yaml.safe_dump(arch, sort_keys=False, allow_unicode=True, width=100)
    await put_file(
        db,
        namespace=system_namespace(system_id),
        path=ARCHITECTURE,
        content=(
            "# System graph: components, their plugins and the data between them.\n" + body
        ).encode(),
        actor=actor,
        reason=reason,
    )


def _connect(
    arch: dict[str, Any], cid: str, upstream: list[str] | None, downstream: list[str] | None
) -> bool:
    """Add ``upstream → cid`` and ``cid → downstream`` edges (known components only)."""
    known = {c.get("id") for c in arch["components"] if isinstance(c, dict)}
    have = {(e.get("from"), e.get("to")) for e in arch["edges"] if isinstance(e, dict)}
    added = False
    pairs = [(u, cid) for u in upstream or []] + [(cid, d) for d in downstream or []]
    for a, b in pairs:
        if a == b or a not in known or b not in known or (a, b) in have:
            continue
        arch["edges"].append({"from": a, "to": b})
        have.add((a, b))
        added = True
    if added and not arch.get("end_to_end_entry"):
        targets = {b for _, b in have}
        sources = [c["id"] for c in arch["components"] if c.get("id") not in targets]
        if sources:
            arch["end_to_end_entry"] = sources[0]
    return added


async def _link_component(
    db: AsyncSession,
    system_id: str,
    name: str,
    card: dict[str, Any],
    component_id: str | None,
    actor: str,
    upstream: list[str] | None = None,
    downstream: list[str] | None = None,
) -> bool:
    """Point the component at ``plugins/<name>`` in architecture.yaml (add it when missing)
    and add its edges."""
    arch = await _load_arch(db, system_id)
    components = arch["components"]
    ref = f"plugins/{name}"
    uri = (card.get("access") or {}).get("uri")
    target = component_id or card.get("id")
    changed = False
    for comp in components:
        if isinstance(comp, dict) and comp.get("id") == target:
            if comp.get("plugin") != ref or (uri and comp.get("model") != uri):
                comp["plugin"] = ref
                if uri:
                    comp["model"] = uri
                changed = True
            break
    else:
        existing = next(
            (
                c
                for c in components
                if isinstance(c, dict) and _plugin_folder(c.get("plugin")) == name
            ),
            None,
        )
        if existing is None:
            entry: dict[str, Any] = {"id": target, "plugin": ref, "kind": "ml_model"}
            if uri:
                entry["model"] = uri
            components.append(entry)
            changed = True
        else:
            target = existing["id"]
    changed = _connect(arch, str(target), upstream, downstream) or changed
    if changed:
        await _write_arch(db, system_id, arch, actor, f"plugin {name} linked")
    return changed


async def add_component(
    db: AsyncSession,
    system_id: str,
    *,
    name: str,
    kind: str,
    actor: str,
    model: str | None = None,
    note: str | None = None,
    upstream: list[str] | None = None,
    downstream: list[str] | None = None,
) -> dict[str, Any]:
    """Add a box to the system graph (a model without a plugin yet, an upstream system or a
    human step) with its edges."""
    slug = _slug(name)
    if not slug:
        raise HTTPException(status_code=422, detail="Give the step a name.")
    if model and not _MODEL_URI.match(model):
        raise HTTPException(status_code=422, detail="model: models:/<name>@<alias> or /<version>.")
    arch = await _load_arch(db, system_id)
    cid = f"{system_id}.{slug}"
    if any(isinstance(c, dict) and c.get("id") == cid for c in arch["components"]):
        raise HTTPException(status_code=409, detail=f"{cid} is already in the graph.")
    entry: dict[str, Any] = {"id": cid, "kind": kind}
    if model:
        entry["model"] = model
    if note:
        entry["note"] = note
    arch["components"].append(entry)
    _connect(arch, cid, upstream, downstream)
    await _write_arch(db, system_id, arch, actor, f"{cid} added to the graph")
    return await system_graph(db, system_id)


async def remove_component(
    db: AsyncSession, system_id: str, component_id: str, *, actor: str
) -> dict[str, Any]:
    """Drop a box and its edges from the graph. Its plugin files stay in the folder."""
    arch = await _load_arch(db, system_id)
    before = len(arch["components"])
    arch["components"] = [
        c for c in arch["components"] if not (isinstance(c, dict) and c.get("id") == component_id)
    ]
    if len(arch["components"]) == before:
        raise HTTPException(status_code=404, detail="Component not found in architecture.yaml.")
    arch["edges"] = [
        e
        for e in arch["edges"]
        if isinstance(e, dict) and component_id not in (e.get("from"), e.get("to"))
    ]
    if arch.get("end_to_end_entry") == component_id:
        arch.pop("end_to_end_entry")
    await _write_arch(db, system_id, arch, actor, f"{component_id} removed from the graph")
    return await system_graph(db, system_id)
