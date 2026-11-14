"""Which tools a run has, and which of them stop for approval.

The counterpart to ``builtins.py`` (what the prebuilt tools *are*) and
``registry.py`` (how a native tool is built). Nothing here touches an agent
instance: every function takes what it needs and returns a value, so the rules
can be driven directly in tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from core.logging import get_logger
from harness.tools.builtins import (
    BUILTIN_BY_NAME,
    EXECUTE_TOOL_NAME,
    GATE_ALIASES,
    builtin_hitl_defaults,
    locked_gates,
    ungateable_tools,
)

logger = get_logger(__name__)


class NamedTool(Protocol):
    """The only thing this module needs of a tool: what it is called."""

    name: str


def strip_reserved_names(tools: Sequence[NamedTool], *, agent_slug: str) -> list[NamedTool]:
    """Drop live MCP tools whose name collides with a prebuilt one.

    A gateway is free to expose a tool called ``write_file``. If one reached the
    agent it would shadow the framework's, and every approval gate keyed on that
    name would point at the wrong tool: an approval control that looks armed
    and guards nothing.
    """
    reserved = {name.lower() for name in BUILTIN_BY_NAME}
    kept: list[NamedTool] = []
    excluded: list[str] = []
    for tool in tools:
        raw = getattr(tool, "name", "")
        name = raw.strip() if isinstance(raw, str) else str(raw or "").strip()
        if name.lower() in reserved:
            excluded.append(name)
            continue
        kept.append(tool)
    if excluded:
        logger.info(
            "deep_agent_reserved_tools_excluded",
            "Excluded MCP tools that collide with prebuilt tool names",
            agent_slug=agent_slug,
            excluded_tools=sorted(set(excluded)),
        )
    return kept


def with_gate_aliases(gates: Mapping[str, bool] | None) -> dict[str, bool]:
    """``gates`` with each aliased key's value copied onto its other name.

    ``task`` and ``start_async_task`` are one delegation gate; copying the value
    both ways makes either spelling gate whichever tool the run has. A key
    stated under *both* names keeps each value as stated.
    """
    out = dict(gates or {})
    for name, alias in GATE_ALIASES.items():
        if name in out and alias not in out:
            out[alias] = out[name]
    return out


def resolve_interrupt_on(own_gates: Mapping[str, bool] | None) -> dict[str, bool]:
    """Merge the approval layers into one ``interrupt_on`` map.

    Lowest priority first: the platform's baseline for prebuilt tools, then
    what the agent declares (spec ``hitl:``, which may add or clear a gate),
    then the locked gates, applied last so nothing can clear them. ``execute``
    is forced once more by name: a code-execution tool that runs unapproved is
    the one failure this merge must never produce, at any depth. Ungateable
    tools (``ask_user``, itself the pause) are dropped from the result.
    """
    resolved = {**builtin_hitl_defaults(), **with_gate_aliases(own_gates)}
    resolved.update(locked_gates())
    resolved[EXECUTE_TOOL_NAME] = True
    for name in ungateable_tools():
        resolved.pop(name, None)
    return resolved


__all__ = [
    "NamedTool",
    "resolve_interrupt_on",
    "strip_reserved_names",
    "with_gate_aliases",
]
