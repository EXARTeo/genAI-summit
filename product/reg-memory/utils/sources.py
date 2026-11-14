from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import HTTPException, status

from core.settings import settings
from engine.watch import proposals
from schema.sources import SourceList, SourceOut
from schema.watch import ProposalList
from utils.state import get_catalog, get_store

_LATEST_KEYS = ("version", "status", "fetched_at", "bytes", "sha256", "error")


def list_sources() -> SourceList:
    manifests = get_store().list_manifests()
    per_source = Counter(m.get("source_id") for m in manifests)
    by_doc = {m["doc_id"]: m for m in manifests}
    items = []
    for src in get_catalog().sources:
        manifest = by_doc.get(src.id)
        latest = None
        if manifest and manifest["versions"]:
            last = manifest["versions"][-1]
            latest = {k: last.get(k) for k in _LATEST_KEYS}
        items.append(SourceOut(**src.model_dump(), latest=latest, documents=per_source[src.id]))
    return SourceList(items=items)


def list_proposals(wanted: str) -> ProposalList:
    items = proposals.load(settings.store.data_dir)
    if wanted != "all":
        items = [p for p in items if p["status"] == wanted]
    items.sort(key=lambda p: (p.get("triage") or {}).get("relevance", 0), reverse=True)
    return ProposalList(items=items)


def decide_proposal(proposal_id: str, accept: bool, by: str) -> dict[str, Any]:
    try:
        return proposals.decide(settings.store.data_dir, get_catalog(), proposal_id, accept, by=by)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
