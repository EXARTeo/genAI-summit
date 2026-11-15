"""What every copilot tool shares: the run's scope, the result cap and the scope fallbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from harness.memory.entries import is_valid_id

#: Longest tool result handed to the model, in characters.
MAX_RESULT_CHARS = 12_000

NO_SYSTEM = (
    "No system given and this conversation is not scoped to one. "
    "Call list_systems and pass the system_id."
)
NO_AUDIT = "No audit given and this conversation is not scoped to one; call list_audits."


@dataclass(frozen=True)
class WorkspaceScope:
    """Who the run is and what its conversation is about (from the run context)."""

    client_id: str
    agent_slug: str
    system_id: str | None = None
    audit_id: str | None = None


def dump(value: Any) -> str:
    """JSON for the model, capped at :data:`MAX_RESULT_CHARS`."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n... [{len(text) - MAX_RESULT_CHARS} more characters]"


def pick_system(scope: WorkspaceScope, system_id: str | None) -> str | None:
    """The given system id, else the conversation's; None when neither is a valid id."""
    chosen = (system_id or "").strip() or scope.system_id
    return chosen if is_valid_id(chosen) else None


def pick_audit(scope: WorkspaceScope, audit_id: str | None) -> str | None:
    """The given audit id, else the conversation's; None when neither is a valid id."""
    chosen = (audit_id or "").strip() or scope.audit_id
    return chosen if is_valid_id(chosen) else None


def clip(text: Any, limit: int = 300) -> str | None:
    """A string cut to ``limit`` characters (None for empty)."""
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


__all__ = [
    "MAX_RESULT_CHARS",
    "NO_AUDIT",
    "NO_SYSTEM",
    "WorkspaceScope",
    "clip",
    "dump",
    "pick_audit",
    "pick_system",
]
