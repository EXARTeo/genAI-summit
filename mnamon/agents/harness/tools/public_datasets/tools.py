"""LangChain tools over the backend's internal API (one audit = one system).

* ``search_public_datasets(audit_id, plugin?)`` reads the system folder, searches,
  scores, and writes a ``public_dataset_candidates`` artifact (``name`` = plugin,
  ``status: proposed``). It fetches nothing.
* ``fetch_public_dataset(audit_id, candidate_id, plugin?)`` only runs when that
  artifact is **approved** by a human (and, if the human set ``data.selected``,
  only for that id); it stores ``datasets/public/<slug>/`` in the system folder.

Not registered here: the pipeline wires them into the registry
(``build_public_dataset_tools()`` returns the tool objects).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from harness.tools.public_datasets.context import load_contexts
from harness.tools.public_datasets.fetch import BackendStore, fetch_from_result
from harness.tools.public_datasets.search import ARTIFACT_KIND, search_public_datasets

CONTEXT_FILES = ("system-card.yaml", "plugin.yaml", "data-dictionary.yaml", "training-data.md")


class InternalAPI:
    """Minimal client for ``/internal/audits/{id}/...`` (shared secret)."""

    def __init__(
        self,
        base_url: str | None = None,
        secret: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base = (
            base_url or os.environ.get("BACKEND_INTERNAL_URL") or "http://backend:8000"
        ).rstrip("/")
        self.secret = (
            secret if secret is not None else os.environ.get("INTERNAL_SERVICE_SECRET", "")
        )
        self.client = client or httpx.Client(timeout=60)
        self.headers = {"X-Internal-Secret": self.secret, "X-Agent-Name": "public-datasets"}

    def _get(self, path: str, **params: Any) -> Any:
        r = self.client.get(f"{self.base}{path}", params=params or None, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def audit(self, audit_id: str) -> dict[str, Any]:
        return self._get(f"/internal/audits/{audit_id}")

    def system_files(self, audit_id: str) -> dict[str, str]:
        tree = self._get(f"/internal/audits/{audit_id}/files")
        out: dict[str, str] = {}
        for f in tree:
            path = f["path"]
            if path.split("/")[-1] in CONTEXT_FILES:
                body = self._get(f"/internal/audits/{audit_id}/files/{path}")
                if body.get("text") is not None:
                    out[path] = body["text"]
        return out

    def post_artifact(self, audit_id: str, kind: str, name: str, data: dict) -> dict[str, Any]:
        r = self.client.post(
            f"{self.base}/internal/audits/{audit_id}/artifacts",
            json={"kind": kind, "name": name, "data": data, "status": "proposed"},
            headers=self.headers,
        )
        r.raise_for_status()
        return r.json()


def _summary(result: dict[str, Any], top: int = 5) -> dict[str, Any]:
    return {
        "plugin": result["plugin"],
        "sources": result["sources"],
        "candidates": [
            {
                k: c.get(k)
                for k in ("id", "name", "url", "score", "licence", "n_rows", "gaps", "flags")
            }
            | {"mapped": {f: m["column"] for f, m in c["mapping"].items()}}
            for c in result["candidates"][:top]
        ],
    }


def run_search(
    audit_id: str, plugin: str | None = None, *, api: InternalAPI | None = None, **kwargs: Any
) -> dict[str, Any]:
    api = api or InternalAPI()
    detail = api.audit(audit_id)
    system_id = (detail.get("system") or {}).get("id", "")
    contexts = load_contexts(api.system_files(audit_id), system_id)
    if plugin:
        contexts = [c for c in contexts if c.plugin == plugin]
    if not contexts:
        return {"error": f"no plugin with a data dictionary{f' named {plugin}' if plugin else ''}"}
    out = []
    for ctx in contexts:
        result = search_public_datasets(ctx, **kwargs)
        artifact = api.post_artifact(audit_id, ARTIFACT_KIND, ctx.plugin, result)
        out.append({"artifact_id": artifact.get("id"), **_summary(result)})
    return {"status": "proposed: a human picks one candidate per plugin", "results": out}


def run_fetch(
    audit_id: str,
    candidate_id: str,
    plugin: str | None = None,
    *,
    api: InternalAPI | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    api = api or InternalAPI()
    audit = api.audit(audit_id)["audit"]
    artifacts = [
        a
        for a in audit.get("artifacts") or []
        if a["kind"] == ARTIFACT_KIND and (plugin is None or a["name"] == plugin)
    ]
    approved = [a for a in artifacts if a["status"] == "approved"]
    if not approved:
        return {"error": "the public_dataset_candidates artifact is not approved yet (HITL)"}
    artifact = max(approved, key=lambda a: a["version"])
    selected = (artifact.get("data") or {}).get("selected")
    if selected and selected != candidate_id:
        return {"error": f"the human selected {selected}, not {candidate_id}"}
    approval = next(
        (
            p
            for p in reversed(audit.get("approvals") or [])
            if p.get("artifactId") == artifact["id"] and p.get("decision") == "approved"
        ),
        {},
    )
    approved_by = approval.get("decidedBy") or "human (artifact approved)"
    result = artifact["data"]
    store = BackendStore(
        api.base,
        audit_id,
        next(c["slug"] for c in result["candidates"] if c["id"] == candidate_id),
        api.secret,
        client=api.client,
    )
    return fetch_from_result(result, candidate_id, store=store, approved_by=approved_by, **kwargs)


class SearchArgs(BaseModel):
    audit_id: str = Field(..., description="The audit whose system to find public data for.")
    plugin: str | None = Field(
        None, description="One plugin (default: every plugin with a data dictionary)."
    )
    top: int = Field(8, ge=1, le=20, description="Candidates kept per plugin.")


class FetchArgs(BaseModel):
    audit_id: str
    candidate_id: str = Field(
        ..., description="e.g. openml:31, from the approved candidates artifact."
    )
    plugin: str | None = None
    max_rows: int = Field(5000, ge=100, le=50000)


def build_public_dataset_tools() -> list[StructuredTool]:
    def _search(audit_id: str, plugin: str | None = None, top: int = 8) -> str:
        return json.dumps(run_search(audit_id, plugin, top=top), default=str)

    def _fetch(
        audit_id: str, candidate_id: str, plugin: str | None = None, max_rows: int = 5000
    ) -> str:
        return json.dumps(run_fetch(audit_id, candidate_id, plugin, max_rows=max_rows), default=str)

    return [
        StructuredTool.from_function(
            func=_search,
            name="search_public_datasets",
            description=(
                "Find public datasets (OpenML, UCI, Hugging Face, web via Firecrawl) that match "
                "the audited system's data dictionary. Scores schema overlap, protected fields, "
                "label, task, size, licence, recency; writes a public_dataset_candidates artifact "
                "for the human to approve. Fetches nothing."
            ),
            args_schema=SearchArgs,
        ),
        StructuredTool.from_function(
            func=_fetch,
            name="fetch_public_dataset",
            description=(
                "After a human approved the candidates artifact: download the chosen dataset "
                "(row cap, PII columns dropped) into datasets/public/<slug>/ of the system folder "
                "with data.csv, mapping.yaml, datasheet.md. Use it as synthkit reference_sample."
            ),
            args_schema=FetchArgs,
        ),
    ]
