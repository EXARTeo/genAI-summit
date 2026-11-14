"""Agent tool: record a durable lesson in the audited system's memory.

Bound **per run** to the run's :class:`~harness.memory.MemoryBinding`: the system
and audit come from the run context, never from the model, so a run can only
write ``/memory/audits/<its audit>/<name>.md`` of its own system. Provenance
(step, agent, run, thread) goes into columns, not into the body the agent reads.

Idempotent by name: the same name in the same audit updates the entry in place,
which is what a node re-entered after an approval pause or a restart needs.
Never raises: every failure is a string the model can reason about.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.settings import settings
from harness.memory.entries import (
    MAX_CONTENT,
    MAX_SUMMARY,
    entry_path,
    render_entry,
    slugify_name,
)
from harness.memory.store import MemoryBinding, MemoryStoreProtocol, save_memory

logger = get_logger(__name__)

REMEMBER_TOOL_NAME = "remember"


def _unescape(text: str) -> str:
    """Undo double-escaped line breaks some models send (``\\n`` as two characters)."""
    return text.replace("\\r\\n", "\n").replace("\\n", "\n") if "\n" not in text else text


class _RememberArgs(BaseModel):
    name: str = Field(
        description="Short identifier, e.g. 'postcode-is-a-nationality-proxy'. Becomes the "
        "file name; reusing a name in this audit updates that entry."
    )
    summary: str = Field(
        description="One self-contained line: the lesson. It is what every later agent "
        "sees in MEMORY.md."
    )
    content: str = Field(
        description="The detail: what happened, why, what to do differently, and the "
        "source (gate, reviewer reason, file or test id)."
    )


def build_remember_tool(*, binding: MemoryBinding, store: MemoryStoreProtocol) -> StructuredTool:
    """A ``remember`` tool bound to this run's system and audit."""

    async def _remember(name: str, summary: str, content: str) -> str:
        slug = slugify_name(name)
        if not slug:
            return "Could not save: 'name' must contain letters or digits."
        summary = " ".join(_unescape(summary or "").split())[:MAX_SUMMARY]
        content = _unescape(content or "").strip()[:MAX_CONTENT]
        if not summary or not content:
            return "Could not save: both 'summary' and 'content' are required."
        cap = settings.memory.max_entries_per_system
        try:
            outcome = await save_memory(
                store,
                binding,
                name=slug,
                summary=summary,
                content_md=render_entry(slug, summary, content),
                max_entries=cap,
            )
        except Exception as exc:  # the agent is mid-thought: a result, never a failed run
            logger.warning(
                "remember_tool_write_failed",
                "Failed to persist a system memory entry",
                system_id=binding.system_id,
                memory_name=slug,
                failure_reason=type(exc).__name__,
            )
            return "Could not save the memory right now."
        if outcome == "read_only":
            return "Could not save: this run is not part of an audit, so memory is read-only."
        if outcome == "full":
            return (
                f"Memory for {binding.system_id} is full ({cap} entries). Update an existing "
                "entry (same name) instead."
            )
        path = entry_path(binding.audit_id or "", slug)
        logger.info(
            "system_memory_saved",
            "Saved a system memory entry",
            system_id=binding.system_id,
            audit_id=binding.audit_id,
            step=binding.step,
            memory_name=slug,
            outcome=outcome,
        )
        verb = "Updated" if outcome == "updated" else "Saved"
        return f"{verb} memory '{slug}' at {path}; later agents on {binding.system_id} will see it."

    return StructuredTool.from_function(
        coroutine=_remember,
        name=REMEMBER_TOOL_NAME,
        description=(
            "Record a durable lesson about THIS audited system in its shared memory, so every "
            "later step and audit of the system can apply it: a human correction at a gate "
            "(with its reason), a system quirk, a decision that should hold next time. Give a "
            "short 'name' (reuse it to update), a one-line 'summary' and the full 'content'. "
            "Not for transient notes."
        ),
        args_schema=_RememberArgs,
    )


__all__ = ["REMEMBER_TOOL_NAME", "build_remember_tool"]
