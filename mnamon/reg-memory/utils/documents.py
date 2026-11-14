from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from schema.documents import DocumentDetail, DocumentList, DocumentSummary, DocumentText
from utils.state import get_store


def list_documents(source_id: str | None = None) -> DocumentList:
    store = get_store()
    items = []
    for m in store.list_manifests():
        if source_id and m.get("source_id") != source_id:
            continue
        latest = store.latest(m) or {}
        last = m["versions"][-1] if m["versions"] else {}
        items.append(
            DocumentSummary(
                doc_id=m["doc_id"],
                source_id=m["source_id"],
                parent_id=m.get("parent_id"),
                url=m["url"],
                label=m.get("label"),
                latest_version=latest.get("version"),
                sha256=latest.get("sha256"),
                bytes=latest.get("bytes") or 0,
                content_type=latest.get("content_type"),
                last_status=last.get("status"),
                last_fetched_at=last.get("fetched_at"),
                has_text=bool(latest.get("text_path")),
            )
        )
    return DocumentList(items=items)


def _manifest(doc_id: str) -> dict[str, Any]:
    try:
        manifest = get_store().load_manifest(doc_id)
    except ValueError:  # not a valid doc id
        manifest = None
    if not manifest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return manifest


def get_document(doc_id: str) -> DocumentDetail:
    m = _manifest(doc_id)
    return DocumentDetail(
        doc_id=m["doc_id"],
        source_id=m["source_id"],
        parent_id=m.get("parent_id"),
        url=m["url"],
        label=m.get("label"),
        versions=m["versions"],
    )


def get_text(doc_id: str, version: int | None) -> DocumentText:
    _manifest(doc_id)
    found = get_store().read_text(doc_id, version)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no extracted text for that version")
    text, entry = found
    return DocumentText(doc_id=doc_id, version=entry["version"], sha256=entry["sha256"], text=text)
