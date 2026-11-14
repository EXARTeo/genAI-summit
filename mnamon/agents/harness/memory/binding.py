"""A run's memory binding, read from its context (never from the model).

The backend (or the audit pipeline) puts ``system_id``, ``audit_id`` and ``step``
in ``config.context``; a background task inherits them from the run that
started it. No ``system_id`` means no memory at all: no ``/memory/`` mount, no
``remember`` / ``forget``, no memory prompt, exactly as a plain chat run today.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harness.memory.entries import is_valid_id
from harness.memory.store import MemoryBinding

#: Optional run-context keys that scope memory (contract § Config).
MEMORY_CONTEXT_KEYS = ("system_id", "audit_id", "step")
MAX_STEP = 64


def validate_memory_context(context: dict[str, Any]) -> None:
    """Strip and check the optional memory keys in place; raise ``ValueError`` on a bad one."""
    for key in MEMORY_CONTEXT_KEYS:
        value = context.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Agent config 'context.{key}' must be a non-empty string.")
        value = value.strip()
        if key == "step":
            if len(value) > MAX_STEP:
                raise ValueError(f"Agent config 'context.step' is longer than {MAX_STEP}.")
        elif not is_valid_id(value):
            raise ValueError(f"Agent config 'context.{key}' is not a valid id.")
        context[key] = value
    if context.get("audit_id") and not context.get("system_id"):
        raise ValueError("Agent config 'context.audit_id' needs 'context.system_id'.")


def memory_binding_from_context(
    context: Mapping[str, Any], *, agent_name: str, thread_id: str | None = None
) -> MemoryBinding | None:
    """This run's binding, or None when the run is not about a system."""
    system_id = context.get("system_id")
    if not is_valid_id(system_id):
        return None
    audit_id = context.get("audit_id")
    step = context.get("step")
    return MemoryBinding(
        system_id=system_id,
        audit_id=audit_id if is_valid_id(audit_id) else None,
        step=step if isinstance(step, str) and step else None,
        agent_name=agent_name,
        run_id=context.get("run_id"),
        thread_id=thread_id,
    )


__all__ = ["MEMORY_CONTEXT_KEYS", "memory_binding_from_context", "validate_memory_context"]
