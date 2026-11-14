"""Per-request logging context (request id, client id, conversation id, ...)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# None, not {}: a mutable default would be one dict shared by every context.
_REQUEST_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "backend_request_context", default=None
)


def get_context() -> dict[str, Any]:
    """A copy of the current request's context (empty outside a request)."""
    return dict(_REQUEST_CONTEXT.get() or {})


def set_context(**values: Any) -> dict[str, Any]:
    """Merge ``values`` into the context; a ``None`` value removes its key."""
    current = get_context()
    for key, value in values.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    _REQUEST_CONTEXT.set(current)
    return current


def clear_context() -> None:
    """Drop every key (the end of a request)."""
    _REQUEST_CONTEXT.set({})
