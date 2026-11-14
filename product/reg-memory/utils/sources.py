from __future__ import annotations

from collections import Counter

from schema.sources import SourceList, SourceOut
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
