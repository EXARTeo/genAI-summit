"""The audited system's memory: how it works, plus its index, loaded at build time.

Only on a run bound to a system (``system_id`` in the context): the same flag
that mounts ``/memory/`` and attaches ``remember`` / ``forget``. The index
(``MEMORY.md``) is read once when the agent is built and injected here, so every
step starts with every lesson recorded for the system; the entries themselves
are read on demand with ``read_file``.
"""

from __future__ import annotations

from harness.prompt_engineering.context import PromptContext

_HEADER = "## System Memory"

_BODY = """\
You share one memory with every agent and pipeline step that works on audits of
this system. Humans never read it directly; it is how the next run avoids the
mistakes of the last one.

- `/memory/MEMORY.md` — the index below: one line per entry, grouped by audit,
  newest first. Generated; writing to it changes nothing.
- `/memory/audits/<audit_id>/<name>.md` — one entry. When a line looks relevant
  to what you are about to do, `read_file` it before acting, and say in your
  output which entry you applied (by its path)."""

_WRITE = """\
- Call `remember(name, summary, content)` to record a durable lesson for this
  system: a human rejection or change request (with its reason) you were handed,
  a quirk of the system or its endpoints, a decision that should hold next time.
  It lands in `/memory/audits/{audit_id}/<name>.md`; reusing a name updates it.
  When you are given a reviewer's reason for rejecting earlier work, record the
  lesson before you redo the work.
- `forget(name, audit_id?)` deletes a wrong or obsolete entry (a human approves
  it). To correct an entry, `remember` it again under the same name."""

_READ_ONLY = """\
- This run is not part of an audit: the memory is read-only for you."""


def memory_prompt(context: PromptContext) -> str:
    """The memory block for this run. Empty when the run is not bound to a system."""
    if context.memory_index is None:
        return ""
    rules = (
        _WRITE.format(audit_id=context.memory_audit_id) if context.memory_audit_id else _READ_ONLY
    )
    index = context.memory_index.strip()
    return f"{_HEADER}\n\n{_BODY}\n{rules}\n\nCurrent `/memory/MEMORY.md`:\n\n{index}"


__all__ = ["memory_prompt"]
