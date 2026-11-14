"""Load and validate the source catalog (``sources.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Kind = Literal[
    "regulation",
    "amendment",
    "consolidated",
    "guideline",
    "faq",
    "code_of_practice",
    "standard",
    "national_law",
    "internal_policy",
    "other",
]
Fetcher = Literal["cellar", "http", "firecrawl"]
Format = Literal["xhtml", "html", "pdf", "docx"]

# A label ending in a parenthesised single word other than "English", e.g.
# "... (AI Act) (Greek)": the Commission's per-language copies of a document.
DEFAULT_EXCLUDE_LABEL = r"\((?!English\b)[A-Z][a-z]+\)+\.?\s*$"


class FollowLinks(BaseModel):
    """Download linked documents (e.g. attached PDFs) as children of a page."""

    pattern: str  # regex matched against the absolute link URL
    max: int = 10
    hosts: list[str] = Field(default_factory=list)  # allowlist; empty = the page's host
    # Regexes on the link's label (the text just before / inside the link).
    include_label: str | None = None
    exclude_label: str | None = DEFAULT_EXCLUDE_LABEL
    # Links are documents (PDF/DOCX): an HTML answer is an error page -> failed.
    binary: bool = True


class Discover(BaseModel):
    """Index page watched for new documents: links matching ``pattern`` that are not
    yet in the catalog become proposed sources (the page itself is the source)."""

    pattern: str
    hosts: list[str] = Field(default_factory=list)  # allowlist; empty = the page's host
    max: int = 200


class Source(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str
    kind: Kind
    binding: bool | Literal["internal"]
    status: Literal["final", "draft"] = "final"
    publisher: str = ""
    fetcher: Fetcher
    celex: str | None = None
    url: str | None = None
    formats: list[Format] = Field(default_factory=lambda: ["html"])
    follow_links: FollowLinks | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    enabled: bool = True
    # Firecrawl change tracking on every scheduled check (when FIRECRAWL_API_KEY is set).
    monitor: bool = False
    discover: Discover | None = None

    @model_validator(mode="after")
    def _target(self) -> Source:
        if self.fetcher == "cellar" and not self.celex:
            raise ValueError(f"{self.id}: cellar sources need `celex`")
        if self.fetcher != "cellar" and not self.url:
            raise ValueError(f"{self.id}: {self.fetcher} sources need `url`")
        return self


class Catalog(BaseModel):
    sources: list[Source]

    @model_validator(mode="after")
    def _unique(self) -> Catalog:
        ids = [s.id for s in self.sources]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate source ids: {sorted(dupes)}")
        return self

    def get(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)


def load_catalog(
    path: Path, overlay: Path | None = None, url_overrides: dict[str, str] | None = None
) -> Catalog:
    """The git catalog, plus the data-side ``overlay`` (accepted proposals) and per-id
    URL overrides (e.g. the demo mirror's public copy)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = list(raw.get("sources") or [])
    if overlay and overlay.exists():
        ids = {s.get("id") for s in sources}
        extra = (yaml.safe_load(overlay.read_text(encoding="utf-8")) or {}).get("sources") or []
        sources += [s for s in extra if s.get("id") not in ids]
    for s in sources:
        if url_overrides and s.get("id") in url_overrides and url_overrides[s["id"]]:
            s["url"] = url_overrides[s["id"]]
    return Catalog.model_validate({"sources": sources})
