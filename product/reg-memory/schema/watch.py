"""API models of the watcher, discovery (proposed sources), webhooks and the demo mirror."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CheckRequest(BaseModel):
    # None = every enabled source (and discovery); a list = just those sources.
    source_ids: list[str] | None = Field(None, max_length=100)
    # Await the result (demo) instead of 202 + polling.
    wait: bool = False
    # Force discovery on/off; None = only on full checks.
    discovery: bool | None = None


class CheckAccepted(BaseModel):
    check_id: str
    status: str


class CheckRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    check_id: str
    status: str


class ProposalList(BaseModel):
    items: list[dict[str, Any]]


class Decision(BaseModel):
    by: str = Field("api", max_length=120)


class WebhookAccepted(BaseModel):
    accepted: bool
    event: str | None = None
    matched_sources: list[str] = Field(default_factory=list)
    check_id: str | None = None


class MirrorEdit(BaseModel):
    """One of: html (replace all), find + replace, append_html, reset."""

    html: str | None = Field(None, max_length=200_000)
    find: str | None = Field(None, max_length=20_000)
    replace: str | None = Field(None, max_length=20_000)
    append_html: str | None = Field(None, max_length=20_000)
    reset: bool = False


class MirrorOut(BaseModel):
    url: str
    bytes: int
    html: str
