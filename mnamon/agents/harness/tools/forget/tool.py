"""Agent tool: delete one entry from the audited system's memory.

The counterpart to ``remember``, bound per run to the run's system. Approval-
gated by default (``harness/tools/builtins.py``): a delete has no tombstone, so
a human confirms it. ``audit_id`` defaults to the run's audit; another audit of
the same system can be named, never another system. Idempotent and never raises.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.logging import get_logger
from harness.memory.entries import entry_path, is_valid_id, slugify_name
from harness.memory.store import MemoryBinding, MemoryStoreProtocol

logger = get_logger(__name__)

FORGET_TOOL_NAME = "forget"


class _ForgetArgs(BaseModel):
    name: str = Field(description="The entry's name, as it appears in MEMORY.md.")
    audit_id: str | None = Field(
        default=None,
        description="The audit the entry was recorded in (its folder under /memory/audits/). "
        "Defaults to the current audit.",
    )


def build_forget_tool(*, binding: MemoryBinding, store: MemoryStoreProtocol) -> StructuredTool:
    """A ``forget`` tool bound to this run's system."""

    async def _forget(name: str, audit_id: str | None = None) -> str:
        slug = slugify_name(name)
        if not slug:
            return "Could not forget: 'name' must contain letters or digits."
        audit = (audit_id or "").strip() or binding.audit_id
        if not audit:
            return "Could not forget: name the 'audit_id' the entry was recorded in."
        if not is_valid_id(audit):
            return "Could not forget: 'audit_id' is not a valid audit id."
        try:
            removed = await store.delete(binding.system_id, audit, slug)
        except Exception as exc:
            logger.warning(
                "forget_tool_delete_failed",
                "Failed to delete a system memory entry",
                system_id=binding.system_id,
                memory_name=slug,
                failure_reason=type(exc).__name__,
            )
            return "Could not delete the memory right now."
        if not removed:
            return f"No memory at {entry_path(audit, slug)}; nothing to forget."
        logger.info(
            "system_memory_forgotten",
            "Deleted a system memory entry",
            system_id=binding.system_id,
            audit_id=audit,
            memory_name=slug,
        )
        return f"Forgot {entry_path(audit, slug)}. It is gone permanently."

    return StructuredTool.from_function(
        coroutine=_forget,
        name=FORGET_TOOL_NAME,
        description=(
            "Permanently delete one entry from this system's memory when it is wrong or "
            "obsolete. Pass its 'name' (and 'audit_id' if it was recorded in another audit). "
            "To correct an entry instead, call 'remember' again with the same name."
        ),
        args_schema=_ForgetArgs,
    )


__all__ = ["FORGET_TOOL_NAME", "build_forget_tool"]
