"""Plain data shapes shared by the discovery module (no I/O here)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Column:
    """One column of a public dataset, as its catalogue describes it."""

    name: str
    type: str = "unknown"  # numeric | integer | category | string | boolean | date | unknown
    description: str = ""
    values: list[str] = field(default_factory=list)
    is_target: bool = False
    demographic: str = ""  # UCI's demographic tag (Age, Sex, Race, ...)


@dataclass
class Candidate:
    """A public dataset found by a source; scored against one plugin's dictionary."""

    source: str  # openml | uci | huggingface | firecrawl
    source_id: str
    name: str
    url: str
    description: str = ""
    licence: str = ""
    n_rows: int | None = None
    columns: list[Column] = field(default_factory=list)
    target: str | None = None
    task: str = ""  # classification | regression | unknown
    updated: str = ""  # ISO date or year
    citation: str = ""
    download: dict[str, Any] = field(default_factory=dict)  # source-specific fetch info
    query: str = ""

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def slug(self) -> str:
        raw = f"{self.source}-{self.source_id}-{self.name}".lower()
        out = "".join(c if c.isalnum() or c in "._-" else "-" for c in raw)
        while "--" in out:
            out = out.replace("--", "-")
        return out.strip("-._")[:80]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.id
        data["slug"] = self.slug
        return data


@dataclass
class Field:
    """One field of our data dictionary (what a public column should map to)."""

    name: str
    type: str
    role: str = "feature"
    values: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    description: str = ""
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SystemContext:
    """What the search needs about one system plugin."""

    system_id: str
    plugin: str
    name: str = ""
    purpose: str = ""
    annex_basis: str = ""
    task: str = ""  # binary_classification | regression | ...
    label_names: list[str] = field(default_factory=list)
    fields: dict[str, Field] = field(default_factory=dict)
    protected: list[str] = field(default_factory=list)
    proxies: list[str] = field(default_factory=list)
    training_data: str = ""

    @property
    def model_fields(self) -> list[str]:
        return [n for n, f in self.fields.items() if f.role not in ("id", "surface")]
