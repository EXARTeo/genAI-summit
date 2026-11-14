"""The shapes of system memory: records, paths, entry bodies and the derived index.

Pure functions, no I/O, so the store, the ``/memory/`` mount, the tools and the
prompt all agree on one answer for "what does an entry look like":

    /memory/MEMORY.md                      derived on every read (never stored)
    /memory/audits/<audit_id>/<name>.md    one row of ``system_memories``

Inside the mount (the ``CompositeBackend`` strips ``/memory``) the keys are
``/MEMORY.md`` and ``/audits/<audit_id>/<name>.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: The route the memory is mounted at, as the agent sees it.
MEMORY_ROOT = "/memory/"
#: The derived index, inside the mount.
INDEX_KEY = "/MEMORY.md"
#: Every entry lives under one audit's folder, inside the mount.
AUDITS_PREFIX = "/audits/"
ENTRY_SUFFIX = ".md"

#: Caps on what one entry may hold (characters). The summary is the index line.
MAX_NAME = 80
MAX_SUMMARY = 200
MAX_CONTENT = 8000

#: System and audit ids become path segments and store namespace components.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def is_valid_id(value: object) -> bool:
    """Whether ``value`` can be a system or audit id (one safe path segment)."""
    return isinstance(value, str) and bool(_ID_RE.match(value))


def slugify_name(name: str) -> str:
    """A memory name as its key: ``[a-z0-9-]``, at most ``MAX_NAME`` characters.

    The slug is the last part of the primary key and the file name, so both
    tools (and a ``write_file``) must reduce a name the same way.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:MAX_NAME].strip("-")


def entry_key(audit_id: str, name: str) -> str:
    """The mount-relative key of one entry."""
    return f"{AUDITS_PREFIX}{audit_id}/{name}{ENTRY_SUFFIX}"


def entry_path(audit_id: str, name: str) -> str:
    """The path the agent sees for one entry."""
    return f"{MEMORY_ROOT.rstrip('/')}{entry_key(audit_id, name)}"


def normalise_key(key: str) -> str:
    return key if key.startswith("/") else "/" + key


def parse_entry_key(key: str) -> tuple[str, str] | None:
    """``(audit_id, name)`` for an entry key, or None for anything else."""
    key = normalise_key(key)
    if not key.startswith(AUDITS_PREFIX) or not key.endswith(ENTRY_SUFFIX):
        return None
    parts = key[len(AUDITS_PREFIX) : -len(ENTRY_SUFFIX)].split("/")
    if len(parts) != 2:
        return None
    audit_id, name = parts
    if not is_valid_id(audit_id) or not name or slugify_name(name) != name:
        return None
    return audit_id, name


@dataclass
class MemoryRecord:
    """One row of ``system_memories``.

    ``content_md`` is the file the agent reads back, byte for byte. Provenance
    (step, agent, run, thread, trust) lives in the other columns only, never in
    the body, so the agent cannot rewrite its own audit trail with the file tools.
    """

    system_id: str
    audit_id: str
    name: str
    summary: str
    content_md: str
    step: str | None = None
    agent_name: str | None = None
    source_run_id: str | None = None
    source_thread_id: str | None = None
    created_by: str = "agent"
    trust_level: str = "unknown"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def key(self) -> str:
        return entry_key(self.audit_id, self.name)


def render_entry(name: str, summary: str, content: str) -> str:
    """The markdown body ``remember`` stores: a heading, the summary, the detail."""
    return f"# {name}\n\n{summary.strip()}\n\n{content.strip()}\n"


def summary_of(body: str) -> str:
    """The summary of an entry body written with the file tools.

    The first non-empty line that is not the heading, capped. Best effort: the
    body is stored verbatim whatever it holds; only the index line degrades.
    """
    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith("# "):
            continue
        return text.lstrip("#>-* ").strip()[:MAX_SUMMARY]
    return ""


def index_line(record: MemoryRecord) -> str:
    """One line of ``MEMORY.md``: date, step, agent, name, summary."""
    meta = [record.updated_at.date().isoformat()]
    if record.step:
        meta.append(record.step)
    if record.agent_name:
        meta.append(record.agent_name)
    return f"- {' · '.join(meta)} · **{record.name}** — {record.summary}"


def build_index(system_id: str, records: list[MemoryRecord]) -> str:
    """``MEMORY.md`` for one system: every entry, grouped by audit, newest first.

    Derived, never stored: the index can never disagree with the entries.
    """
    lines = [
        f"# System memory: {system_id}",
        "",
        "Lessons recorded by the agents working on audits of this system (one line per entry,",
        "newest first). Read an entry with `read_file /memory/audits/<audit_id>/<name>.md`.",
        "This file is generated from the entries; writing to it changes nothing.",
    ]
    if not records:
        lines += ["", "_No entries yet._"]
        return "\n".join(lines) + "\n"
    ordered = sorted(records, key=lambda r: r.updated_at, reverse=True)
    groups: dict[str, list[MemoryRecord]] = {}
    for record in ordered:
        groups.setdefault(record.audit_id, []).append(record)
    for audit_id, group in groups.items():
        lines += ["", f"## Audit {audit_id}", ""]
        lines += [index_line(record) for record in group]
    return "\n".join(lines) + "\n"


def newest(records: list[MemoryRecord]) -> datetime:
    return max((r.updated_at for r in records), default=_EPOCH)


__all__ = [
    "AUDITS_PREFIX",
    "ENTRY_SUFFIX",
    "INDEX_KEY",
    "MAX_CONTENT",
    "MAX_NAME",
    "MAX_SUMMARY",
    "MEMORY_ROOT",
    "MemoryRecord",
    "build_index",
    "entry_key",
    "entry_path",
    "index_line",
    "is_valid_id",
    "newest",
    "normalise_key",
    "parse_entry_key",
    "render_entry",
    "slugify_name",
    "summary_of",
]
