"""The layered prompt of a pipeline step, and its brief.

System prompt, in order of authority and stability (prompt-engineering plan
§6): ``<platform_rules>`` (precedence + invariants, ``prompts/rules.md``) →
``<step_instructions>`` (one short file per step) → ``<platform_defaults>``
(the Socratic loop adapted to a gated pipeline step + the result contract,
``prompts/method.md``) → ``<system_memory>`` (this system's ``MEMORY.md``) →
the date. deepagents appends its own tool notes after the defaults.

The brief (the user message) carries the step's data as YAML: the pipeline's
facts, never instructions. A reviewer's reason or a verifier's report rides in
its ``feedback`` block.
"""

from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

#: Step -> its instructions file (each ≤ ~200 words).
STEP_PROMPTS = {
    "plan_scenarios": "plan_scenarios.md",
    "draft_spec": "draft_spec.md",
    "analyse": "analyse.md",
    "critic": "critic.md",
    "report": "write_reports.md",
    "change_judge": "change_judge.md",
}

#: Longest text value kept in a brief (a dictionary, a profile note); the
#: rest stays readable through the step's file tools.
MAX_BRIEF_TEXT = 12_000


@cache
def _read(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def compose_step_prompt(step: str, *, memory_index: str | None, today: date) -> str:
    """The step's system prompt (raises ``KeyError`` for an unknown step)."""
    parts = [
        f"<platform_rules>\n{_read('rules.md')}\n</platform_rules>",
        f"<step_instructions>\n{_read(STEP_PROMPTS[step])}\n</step_instructions>",
        f"<platform_defaults>\n{_read('method.md')}\n</platform_defaults>",
    ]
    if memory_index and memory_index.strip():
        parts.append(
            "<system_memory>\nLessons recorded for this system (read an entry with "
            f"`read_memory` before you rely on it):\n{memory_index.strip()}\n</system_memory>"
        )
    parts.append(f"Today is {today:%A, %d %B %Y}.")
    return "\n\n".join(parts)


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_BRIEF_TEXT:
        return value[:MAX_BRIEF_TEXT] + f"\n... [{len(value) - MAX_BRIEF_TEXT} more characters]"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


def render_brief(step: str, brief: dict[str, Any], feedback: dict[str, Any] | None = None) -> str:
    """The user message of a step: its data as YAML, then any feedback to act on."""
    body = yaml.safe_dump(_clip(brief), sort_keys=False, allow_unicode=True, width=100)
    text = f"Step: {step}\n\n<brief>\n{body}</brief>"
    if feedback:
        source = feedback.get("source", "human")
        lead = (
            "A human reviewer rejected the previous attempt. Record the lesson with "
            "`remember`, then redo the step taking it into account."
            if source == "human"
            else "An automatic check failed on the previous attempt. Fix what it reports."
        )
        fb = yaml.safe_dump(_clip(feedback), sort_keys=False, allow_unicode=True, width=100)
        text += f"\n\n<feedback>\n{lead}\n{fb}</feedback>"
    return text


__all__ = ["STEP_PROMPTS", "compose_step_prompt", "render_brief"]
