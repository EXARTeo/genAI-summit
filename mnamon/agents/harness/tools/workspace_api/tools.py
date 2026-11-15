"""The chat copilot's tools: systems, audits and the regulation, read through the product's APIs.

Each tool is built per run by :func:`build_workspace_tool` and bound to the
run's client id and scope (``system_id`` / ``audit_id`` from the run context,
never from the model). A ``system_id`` argument the model leaves out falls back
to the conversation's scope. Every failure is a string the model can reason
about; nothing raises into the run.

Two tools write, and both are approval-gated by default
(``harness/tools/builtins.py``): ``propose_system_note`` adds a note to the
system folder under ``proposed/`` with ``status: proposed`` (a human makes it
``approved``), and ``start_audit`` starts the audit pipeline through the same
route the UI's "Start audit" uses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from core.logging import get_logger
from harness.memory.entries import is_valid_id
from harness.tools.workspace_api.client import WorkspaceAPI, WorkspaceAPIError

logger = get_logger(__name__)

#: Longest tool result handed to the model, in characters.
MAX_RESULT_CHARS = 12_000

LIST_SYSTEMS = "list_systems"
LIST_SYSTEM_FILES = "list_system_files"
READ_SYSTEM_FILE = "read_system_file"
LIST_AUDITS = "list_audits"
READ_AUDIT = "read_audit"
READ_AUDIT_ARTIFACT = "read_audit_artifact"
LOOKUP_PROVISION = "lookup_provision"
SEARCH_REGULATION = "search_regulation"
PROPOSE_SYSTEM_NOTE = "propose_system_note"
START_AUDIT = "start_audit"

#: Every tool this module builds, in the order an agent lists them.
WORKSPACE_TOOL_NAMES: tuple[str, ...] = (
    LIST_SYSTEMS,
    LIST_SYSTEM_FILES,
    READ_SYSTEM_FILE,
    LIST_AUDITS,
    READ_AUDIT,
    READ_AUDIT_ARTIFACT,
    LOOKUP_PROVISION,
    SEARCH_REGULATION,
    PROPOSE_SYSTEM_NOTE,
    START_AUDIT,
)

_NOTE_NAME_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class WorkspaceScope:
    """Who the run is and what its conversation is about (from the run context)."""

    client_id: str
    agent_slug: str
    system_id: str | None = None
    audit_id: str | None = None


def _dump(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n... [{len(text) - MAX_RESULT_CHARS} more characters]"


def _system(scope: WorkspaceScope, system_id: str | None) -> str | None:
    chosen = (system_id or "").strip() or scope.system_id
    return chosen if is_valid_id(chosen) else None


_NO_SYSTEM = (
    "No system given and this conversation is not scoped to one. "
    "Call list_systems and pass the system_id."
)


class _SystemArgs(BaseModel):
    system_id: str | None = Field(
        None, description="e.g. SYS-001. Defaults to the system this conversation is about."
    )


class _TreeArgs(_SystemArgs):
    prefix: str | None = Field(None, description="Only paths under this folder, e.g. plugins/.")


class _ReadArgs(_SystemArgs):
    path: str = Field(description="Path in the system folder, e.g. system-card.yaml.")


class _AuditArgs(BaseModel):
    audit_id: str | None = Field(
        None, description="e.g. SYS-001-20261115-0930. Defaults to this conversation's audit."
    )


class _ArtifactArgs(_AuditArgs):
    artifact_id: str = Field(description="An artifact id from read_audit.")


class _ProvisionArgs(BaseModel):
    provision_id: str = Field(description="e.g. AIA.10.2.f or AIA.ANNEX_III.4.a")


class _SearchArgs(BaseModel):
    query: str = Field(
        description="A few words to find, e.g. 'data governance' or 'human oversight'."
    )


#: The fields of a search hit handed to the model, in this order.
SEARCH_HIT_KEYS = (
    "id",
    "label",
    "title",
    "title_inherited",
    "snippet",
    "score",
    "match",
    "kind",
    "binding",
    "source",
    "also",
)


def _ref_id(ref: Any) -> str | None:
    """A child / interpretation reference: reg-memory sends ids, older shapes dicts."""
    return ref.get("id") if isinstance(ref, dict) else (str(ref) if ref else None)


def _interp_ref(ref: Any) -> Any:
    if isinstance(ref, dict):
        return {k: ref.get(k) for k in ("id", "summary") if ref.get(k)}
    return _ref_id(ref)


def _search_hit(item: dict[str, Any]) -> dict[str, Any]:
    """One hit, without empty fields (``title_inherited`` only when true)."""
    hit = {k: item.get(k) for k in SEARCH_HIT_KEYS if item.get(k) not in (None, "", [])}
    if not hit.get("title_inherited"):
        hit.pop("title_inherited", None)
    return hit


class _NoteArgs(_SystemArgs):
    kind: Literal["evidence", "gap"] = Field(description="An evidence note or a gap note.")
    name: str = Field(description="Short name, becomes the file name, e.g. postcode-proxy.")
    content: str = Field(description="The note in Markdown, citing its sources.")


class _NoArgs(BaseModel):
    pass


def _audit_summary(body: dict[str, Any]) -> dict[str, Any]:
    """An audit with its artifacts listed (id, kind, name, status), not their data."""
    keep = {k: v for k, v in body.items() if k not in ("artifacts", "approvals")}
    keep["artifacts"] = [
        {k: a.get(k) for k in ("id", "kind", "name", "version", "status", "createdBy")}
        for a in body.get("artifacts") or []
    ]
    keep["approvals"] = body.get("approvals") or []
    return keep


def _builders(scope: WorkspaceScope, api: WorkspaceAPI) -> dict[str, Callable[[], BaseTool]]:
    """One factory per tool name, all sharing the run's API client."""

    async def list_systems() -> str:
        try:
            items = await api.systems()
        except WorkspaceAPIError as exc:
            return f"Could not list systems: {exc.public}."
        rows = []
        for s in items:
            card = (s.get("data") or {}).get("card") or {}
            rows.append(
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "risk_class": card.get("risk_class"),
                    "annex_basis": card.get("annex_basis"),
                }
            )
        return _dump(rows)

    async def list_system_files(system_id: str | None = None, prefix: str | None = None) -> str:
        sid = _system(scope, system_id)
        if sid is None:
            return _NO_SYSTEM
        try:
            tree = await api.tree(sid, prefix)
        except WorkspaceAPIError as exc:
            return f"Could not list {sid}'s folder: {exc.public}."
        lines = [f"{f.get('path')} (v{f.get('version')})" for f in tree]
        return f"/systems/{sid}/\n" + ("\n".join(lines) or "(no files)")

    async def read_system_file(path: str, system_id: str | None = None) -> str:
        sid = _system(scope, system_id)
        if sid is None:
            return _NO_SYSTEM
        clean = path.strip().lstrip("/").removeprefix(f"systems/{sid}/")
        try:
            body = await api.read(sid, clean)
        except WorkspaceAPIError as exc:
            return f"Could not read {clean}: {exc.public}."
        text = body.get("text") if isinstance(body, dict) else None
        if text is None:
            return f"{clean} is a binary file."
        return _dump(text)

    async def list_audits(system_id: str | None = None) -> str:
        sid = _system(scope, system_id)
        try:
            items = await api.audits(sid)
        except WorkspaceAPIError as exc:
            return f"Could not list audits: {exc.public}."
        keys = ("id", "systemId", "status", "stage", "createdAt", "updatedAt")
        return _dump([{k: a.get(k) for k in keys} for a in items[:30]])

    async def read_audit(audit_id: str | None = None) -> str:
        aid = (audit_id or "").strip() or scope.audit_id
        if not is_valid_id(aid):
            return "No audit given and this conversation is not scoped to one; call list_audits."
        try:
            body = await api.audit(aid)
        except WorkspaceAPIError as exc:
            return f"Could not read audit {aid}: {exc.public}."
        return _dump(_audit_summary(body))

    async def read_audit_artifact(artifact_id: str, audit_id: str | None = None) -> str:
        aid = (audit_id or "").strip() or scope.audit_id
        if not is_valid_id(aid):
            return "No audit given and this conversation is not scoped to one; call list_audits."
        try:
            body = await api.artifact(aid, artifact_id)
        except WorkspaceAPIError as exc:
            return f"Could not read artifact {artifact_id}: {exc.public}."
        return _dump(body)

    async def lookup_provision(provision_id: str) -> str:
        try:
            body = await api.provision(provision_id.strip())
        except WorkspaceAPIError as exc:
            return f"Could not read {provision_id}: {exc.public}."
        fields = ("id", "label", "title", "title_inherited", "text", "valid_from", "kb_version")
        keep = {k: body.get(k) for k in fields}
        keep["kb_version"] = keep.get("kb_version") or api._kb_version
        if not keep.get("title_inherited"):
            keep.pop("title_inherited", None)
        keep["children"] = [_ref_id(c) for c in body.get("children") or []][:40]
        keep["interpretations"] = [_interp_ref(i) for i in (body.get("interpretations") or [])[:10]]
        return _dump(keep)

    async def search_regulation(query: str) -> str:
        try:
            items = await api.search(query)
        except WorkspaceAPIError as exc:
            return f"Search failed: {exc.public}."
        hits = [_search_hit(i) for i in items]
        return _dump({"kb_version": api._kb_version, "query": query, "items": hits})

    async def propose_system_note(
        kind: str, name: str, content: str, system_id: str | None = None
    ) -> str:
        sid = _system(scope, system_id)
        if sid is None:
            return _NO_SYSTEM
        slug = _NOTE_NAME_RE.sub("-", name.lower()).strip("-")[:60]
        if not slug or not content.strip():
            return "A note needs a name and some content."
        folder = "evidence" if kind == "evidence" else "gaps"
        path = f"proposed/{folder}/{slug}.md"
        header = (
            f"---\nstatus: proposed\nkind: {kind}\nproposed_by: agent:{scope.agent_slug}\n---\n\n"
        )
        try:
            body = await api.write(
                sid,
                path,
                header + content.strip() + "\n",
                reason=f"{kind} note proposed by {scope.agent_slug} in chat",
                data={"status": "proposed", "kind": kind, "proposedBy": scope.agent_slug},
            )
        except WorkspaceAPIError as exc:
            return f"Could not write the note: {exc.public}."
        version = ((body or {}).get("file") or {}).get("version")
        logger.info(
            "workspace_note_proposed",
            "Chat agent proposed a note in a system folder",
            agent_slug=scope.agent_slug,
            system_id=sid,
            path=path,
            version=version,
        )
        return f"Saved /systems/{sid}/{path} (v{version}) as proposed; a human approves it."

    async def start_audit(system_id: str | None = None) -> str:
        sid = _system(scope, system_id)
        if sid is None:
            return _NO_SYSTEM
        try:
            body = await api.start_audit(sid)
        except WorkspaceAPIError as exc:
            return f"Could not start an audit of {sid}: {exc.public}."
        logger.info(
            "workspace_audit_started",
            "Chat agent started an audit",
            agent_slug=scope.agent_slug,
            system_id=sid,
            audit_id=(body or {}).get("id"),
        )
        return _dump({k: (body or {}).get(k) for k in ("id", "systemId", "status", "stage")})

    def tool(fn: Any, name: str, description: str, schema: type[BaseModel]) -> Callable[[], Any]:
        return lambda: StructuredTool.from_function(
            coroutine=fn, name=name, description=description, args_schema=schema
        )

    return {
        LIST_SYSTEMS: tool(
            list_systems,
            LIST_SYSTEMS,
            "List every AI system in the inventory (id, name, status, risk class). "
            "Use it to find a system the user names.",
            _NoArgs,
        ),
        LIST_SYSTEM_FILES: tool(
            list_system_files,
            LIST_SYSTEM_FILES,
            "List a system's folder (/systems/<id>/: system card, architecture, docs, "
            "evidence, gaps, plugins/<name>/).",
            _TreeArgs,
        ),
        READ_SYSTEM_FILE: tool(
            read_system_file,
            READ_SYSTEM_FILE,
            "Read one file of a system's folder, e.g. system-card.yaml or "
            "plugins/<name>/plugin.yaml.",
            _ReadArgs,
        ),
        LIST_AUDITS: tool(
            list_audits,
            LIST_AUDITS,
            "List audits, newest first (all, or one system's).",
            _SystemArgs,
        ),
        READ_AUDIT: tool(
            read_audit,
            READ_AUDIT,
            "One audit: status, stage, its artifacts (scenarios, datasets, test results, "
            "findings, critic, reports) by id and kind, and the human decisions at its gates.",
            _AuditArgs,
        ),
        READ_AUDIT_ARTIFACT: tool(
            read_audit_artifact,
            READ_AUDIT_ARTIFACT,
            "The full data of one audit artifact (e.g. findings with evidence and "
            "counter-evidence, the critic report, the engineer report).",
            _ArtifactArgs,
        ),
        LOOKUP_PROVISION: tool(
            lookup_provision,
            LOOKUP_PROVISION,
            "Verbatim text of one regulation provision at the active kb_version, with its "
            "children and related guidance. Cite it as <id> (kb_version).",
            _ProvisionArgs,
        ),
        SEARCH_REGULATION: tool(
            search_regulation,
            SEARCH_REGULATION,
            "Find regulation provisions by words at the active kb_version. Ranked, one hit per "
            "article: id, label (Art. 10(2)), title (its own or, with title_inherited, the "
            "article's), a snippet of the matching text, score, match (text | title | "
            "heading), binding, and also (other matching ids in that article). Quote only "
            "after lookup_provision.",
            _SearchArgs,
        ),
        PROPOSE_SYSTEM_NOTE: tool(
            propose_system_note,
            PROPOSE_SYSTEM_NOTE,
            "Draft an evidence or gap note into a system's folder under proposed/, with "
            "status: proposed. A human approves it; the user is asked before it is written.",
            _NoteArgs,
        ),
        START_AUDIT: tool(
            start_audit,
            START_AUDIT,
            "Start a new audit of a system (the audit pipeline with its human gates). "
            "The user is asked before it starts.",
            _SystemArgs,
        ),
    }


def build_workspace_tool(
    name: str, scope: WorkspaceScope, api: WorkspaceAPI | None = None
) -> BaseTool | None:
    """The bound tool called ``name``, or None for an unknown name or a run with no client."""
    if not scope.client_id:
        return None
    bound = api or WorkspaceAPI(client_id=scope.client_id, agent_slug=scope.agent_slug)
    factory = _builders(scope, bound).get(name)
    return factory() if factory is not None else None


__all__ = [
    "MAX_RESULT_CHARS",
    "PROPOSE_SYSTEM_NOTE",
    "START_AUDIT",
    "WORKSPACE_TOOL_NAMES",
    "WorkspaceScope",
    "build_workspace_tool",
]
