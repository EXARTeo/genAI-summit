"""API models of the knowledge base: provisions, interpretations, releases, changes,
requirements, test templates. Node models allow extra fields (the YAML schema grows)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Provision(_Open):
    id: str
    instrument: str
    kind: str
    path: list[str]
    text: str
    content_hash: str
    valid_from: str | None = None
    amended_by: list[str] = Field(default_factory=list)
    kb_version: str


class ProvisionList(BaseModel):
    kb_version: str
    total: int
    items: list[dict[str, Any]]


class SearchHit(_Open):
    """One ranked search hit: enough to cite and judge it without another call."""

    id: str
    label: str
    title: str | None = None
    title_inherited: bool = False
    snippet: str
    score: float
    match: str  # text | title | heading
    kind: str | None = None
    instrument: str | None = None
    source: str | None = None
    binding: bool | str = True
    also: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    kb_version: str
    query: str
    total: int
    items: list[SearchHit]


class Interpretation(_Open):
    id: str
    source_id: str
    binding: bool | str
    status: str
    relates_to: list[str]
    content_hash: str
    kb_version: str


class InterpretationList(BaseModel):
    kb_version: str
    total: int
    items: list[dict[str, Any]]


class Release(_Open):
    kb_version: str
    status: str
    created_at: str
    parent: str | None = None
    content_hash: str
    counts: dict[str, int]


class ReleaseList(BaseModel):
    active: str | None
    items: list[Release]


class ReleaseBuild(BaseModel):
    force: bool = False


class Activate(BaseModel):
    # Who accepted the release (HITL); free text, logged in the manifest.
    by: str = Field("api", max_length=120)


class ChangeSummary(_Open):
    id: str
    from_kb_version: str | None
    to_kb_version: str
    created_at: str
    summary: str
    counts: dict[str, int]
    change_types: dict[str, int]


class ChangeList(BaseModel):
    items: list[ChangeSummary]


class RequirementList(BaseModel):
    kb_version: str
    query: dict[str, Any]
    total: int
    items: list[dict[str, Any]]


class TestTemplateList(BaseModel):
    kb_version: str
    items: list[dict[str, Any]]
