from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DocumentSummary(BaseModel):
    doc_id: str
    source_id: str
    parent_id: str | None = None
    url: str
    label: str | None = None
    latest_version: int | None = None
    sha256: str | None = None
    bytes: int = 0
    content_type: str | None = None
    last_status: str | None = None
    last_fetched_at: str | None = None
    has_text: bool = False


class DocumentList(BaseModel):
    items: list[DocumentSummary]


class DocumentDetail(BaseModel):
    doc_id: str
    source_id: str
    parent_id: str | None = None
    url: str
    label: str | None = None
    versions: list[dict[str, Any]]


class DocumentText(BaseModel):
    doc_id: str
    version: int
    sha256: str
    text: str
