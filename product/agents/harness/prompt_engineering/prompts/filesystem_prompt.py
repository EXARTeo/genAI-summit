"""What the agent's workspace is, described only where it exists.

Without it an agent with a thin prompt tells the user it "cannot browse the
local filesystem": it has every mount and every file tool, but was never told.

Deliberately not a tool manual. The file tools carry their own descriptions, so
restating them burns context for nothing; what the model cannot infer is the
*layout* — which route holds what, and which ones refuse writes.
"""

from __future__ import annotations

from harness.prompt_engineering.context import PromptContext

_HEADER = "## Your Workspace"

_INTRO = (
    "You have a real filesystem. Use `ls`, `read_file`, `glob` and `grep` on it "
    "rather than assuming you cannot reach files — these paths exist for this "
    "run:"
)

_CONVERSATION = """\
- `/conversation/input/` — files the user attached to THIS conversation
  (an image small enough to arrive inline in the message is not copied here).
  **Read-only.**
- `/conversation/output/` — where you write anything the user should end up
  with. Writing here does not show it to them; see below.
- `/conversation/` — the rest of this conversation's files. Every agent and
  sub-agent working in this conversation sees the same files, and nothing you
  write here is visible in another chat.
- Any other path (e.g. `/notes.md`) — scratch space for this branch of the
  conversation, shared with your sub-agents."""

_REFERENCE = """\
- `/reference/` — your own definition folder: the notes, checklists and
  examples bundled with your instructions. **Read-only.** Worth an `ls` when a
  task sounds like something you were set up for."""

_OUTRO = (
    "Before starting a task, `ls /conversation/input/` to see what the user "
    "gave you, and `ls /conversation/output/` for work already done in this "
    "chat."
)


def filesystem_prompt(context: PromptContext) -> str:
    """Describe the mounts this run has. Empty when it has none."""
    lines: list[str] = []
    if context.has_conversation:
        lines.append(_CONVERSATION)
    if context.has_reference:
        lines.append(_REFERENCE)
    if not lines:
        return ""

    body = "\n".join(lines)
    outro = f"\n\n{_OUTRO}" if context.has_conversation else ""
    return f"{_HEADER}\n\n{_INTRO}\n\n{body}{outro}"


__all__ = ["filesystem_prompt"]
