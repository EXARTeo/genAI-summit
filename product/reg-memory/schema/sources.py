from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SourceOut(BaseModel):
    id: str
    title: str
    kind: str
    binding: bool | str
    status: str
    publisher: str
    fetcher: str
    celex: str | None = None
    url: str | None = None
    formats: list[str]
    tags: list[str]
    notes: str
    enabled: bool
    follow_links: dict[str, Any] | None = None
    # Latest fetch of the source's main document (None = never fetched).
    latest: dict[str, Any] | None = None
    documents: int = 0


class SourceList(BaseModel):
    items: list[SourceOut]
