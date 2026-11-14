from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    source_ids: list[str] | None = Field(None, max_length=200)
    force: bool = False


class IngestAccepted(BaseModel):
    run_id: str


class IngestRun(BaseModel):
    run_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    force: bool = False
    source_ids: list[str] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    extract: dict[str, int] | None = None
    diff: dict[str, int] | None = None
    error: str | None = None
    catalog_snapshot: str | None = None
