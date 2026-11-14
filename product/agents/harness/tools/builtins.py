"""The prebuilt-tool roster: every tool a deep agent has that is not an MCP tool.

Two origins, one roster. The **framework** tools are constructed inside
``create_deep_agent``, downstream of the tool list we hand it, so only
``interrupt_on`` reaches them. The **native** tools are ours
(``harness/tools/registry.py`` builds them). The roster is also the
reserved-name list live MCP tools are filtered against, so a gateway tool can
never shadow one of these and slip past its approval gate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinTool:
    """One prebuilt tool and how it gates."""

    name: str
    hitl_default: bool = False
    #: Approval cannot be turned off by anyone. Enforced last in the merge.
    locked: bool = False
    #: Approval can never be turned on: the call is itself a pause for the user.
    gateable: bool = True


#: deepagents' tool that starts a background sub-agent; it owns the delegation
#: gate the blocking ``task`` has.
START_ASYNC_TASK_TOOL_NAME = "start_async_task"

#: ``task`` (blocking delegation) and ``start_async_task`` (async) are one gate
#: under two names: a run has only one of them, depending on
#: ``ASYNC_SUBAGENTS_ENABLED``, so whichever spelling a definition uses must
#: gate whichever tool the run has.
GATE_ALIASES: dict[str, str] = {
    "task": START_ASYNC_TASK_TOOL_NAME,
    START_ASYNC_TASK_TOOL_NAME: "task",
}

#: deepagents' sandbox tool, named once so the approval merge can force its gate.
EXECUTE_TOOL_NAME = "execute"

BUILTIN_TOOLS: tuple[BuiltinTool, ...] = (
    BuiltinTool("write_todos"),
    BuiltinTool("ls"),
    BuiltinTool("read_file"),
    BuiltinTool("glob"),
    BuiltinTool("grep"),
    BuiltinTool("write_file", hitl_default=True),
    BuiltinTool("edit_file", hitl_default=True),
    BuiltinTool(EXECUTE_TOOL_NAME, hitl_default=True, locked=True),
    BuiltinTool("task", hitl_default=True),
    BuiltinTool(START_ASYNC_TASK_TOOL_NAME, hitl_default=True),
    BuiltinTool("check_async_task"),
    BuiltinTool("update_async_task"),
    BuiltinTool("cancel_async_task"),
    BuiltinTool("list_async_tasks"),
    BuiltinTool("view_image"),
    BuiltinTool("render_chart"),
    BuiltinTool("present_artifact"),
    BuiltinTool("ask_user", gateable=False),
)

BUILTIN_BY_NAME: dict[str, BuiltinTool] = {t.name: t for t in BUILTIN_TOOLS}


def builtin_hitl_defaults() -> dict[str, bool]:
    """Approval gates every deep agent starts with, before its own definition's."""
    return {t.name: True for t in BUILTIN_TOOLS if t.hitl_default or t.locked}


def locked_gates() -> dict[str, bool]:
    """Gates no layer may clear. Merged last."""
    return {t.name: True for t in BUILTIN_TOOLS if t.locked}


def ungateable_tools() -> frozenset[str]:
    """Tools no layer may gate. Removed after the merge, locked gates included."""
    return frozenset(t.name for t in BUILTIN_TOOLS if not t.gateable)


__all__ = [
    "BUILTIN_BY_NAME",
    "BUILTIN_TOOLS",
    "EXECUTE_TOOL_NAME",
    "GATE_ALIASES",
    "START_ASYNC_TASK_TOOL_NAME",
    "BuiltinTool",
    "builtin_hitl_defaults",
    "locked_gates",
    "ungateable_tools",
]
