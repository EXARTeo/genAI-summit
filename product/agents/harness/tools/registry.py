"""Native-tool registry: the in-code catalog of the service's own tools.

Native tools are Python tools that ship in the image (as opposed to MCP tools,
which arrive as a live manifest from the gateway). Each registers a **builder**
that produces the per-run, context-bound LangChain tool, so that

* a declarative ``agent.yaml`` can select one by name (``{native: <name>}``,
  :func:`resolve_native_tool`), and the spec loader can validate such a ref
  (:func:`is_known_native_tool`);
* ``DeepAgent`` attaches the always-on ones from one place
  (:func:`build_auto_attach_tools`).

Adding a native tool is a code change here, never an upload.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from harness.conversation_files import ConversationFiles
from harness.tools.ask_user import build_ask_user_tool
from harness.tools.charts import build_render_chart_tool
from harness.tools.present_artifact import PresentedFiles, build_present_artifact_tool
from harness.tools.view_image import build_view_image_tool


@dataclass(frozen=True)
class NativeToolContext:
    """Per-run binding a native-tool builder needs, read from the agent's context.

    Safe to hold identity: every request builds its own agent instance, so
    nothing here is shared between conversations.
    """

    agent_slug: str
    conversation_id: str | None
    #: The run's conversation files, shared with its filesystem mounts.
    files: ConversationFiles | None = None
    #: The run's accepted presentations, shared with its stream normalizer.
    presented: PresentedFiles | None = None
    #: A background task's run never asks the user anything: only the
    #: orchestrator may pause on a question.
    async_task_id: str | None = None


@dataclass(frozen=True)
class NativeToolDef:
    """A registered native tool: a context-bound builder.

    ``builder(ctx)`` returns the LangChain tool, or ``None`` when this run does
    not satisfy the tool's gate (e.g. no conversation to present into).
    """

    name: str
    builder: Callable[[NativeToolContext], Any | None]
    #: Given to every deep agent (subject to its gate) rather than selected in
    #: ``agent.yaml``.
    auto_attach: bool = False


#: Registration order is the order auto-attach tools are appended to an agent.
NATIVE_TOOLS: dict[str, NativeToolDef] = {}


def register_native_tool(defn: NativeToolDef) -> NativeToolDef:
    """Register a native tool. Raises on a duplicate name (fail-closed)."""
    if defn.name in NATIVE_TOOLS:
        raise ValueError(f"Native tool {defn.name!r} is already registered.")
    NATIVE_TOOLS[defn.name] = defn
    return defn


# render_chart: drawn inline in the reply; not gated, it has no side effect.
register_native_tool(
    NativeToolDef(
        name="render_chart",
        auto_attach=True,
        builder=lambda ctx: (
            build_render_chart_tool(agent_slug=ctx.agent_slug, conversation_id=ctx.conversation_id)
            if ctx.conversation_id
            else None
        ),
    )
)

# view_image: look at an image from input/ or output/.
register_native_tool(
    NativeToolDef(
        name="view_image",
        auto_attach=True,
        builder=lambda ctx: build_view_image_tool(files=ctx.files) if ctx.files else None,
    )
)

# present_artifact: hand a finished output/ file to the user.
register_native_tool(
    NativeToolDef(
        name="present_artifact",
        auto_attach=True,
        builder=lambda ctx: (
            build_present_artifact_tool(files=ctx.files, presented=ctx.presented)
            if ctx.files is not None and ctx.presented is not None
            else None
        ),
    )
)

# ask_user: the call is itself the human-in-the-loop pause, so it is never
# gated; it needs a conversation and a run someone is watching.
register_native_tool(
    NativeToolDef(
        name="ask_user",
        auto_attach=True,
        builder=lambda ctx: (
            build_ask_user_tool() if ctx.conversation_id and not ctx.async_task_id else None
        ),
    )
)


def is_known_native_tool(name: str) -> bool:
    """Whether ``name`` is a registered native tool (used to validate specs)."""
    return name in NATIVE_TOOLS


def resolve_native_tool(name: str, ctx: NativeToolContext) -> Any | None:
    """The bound tool an agent selected (``{native: name}``), or None when gated off."""
    defn = NATIVE_TOOLS.get(name)
    return defn.builder(ctx) if defn is not None else None


def build_auto_attach_tools(ctx: NativeToolContext) -> list[Any]:
    """The always-on native tools every deep agent gets, each subject to its gate."""
    tools: list[Any] = []
    for defn in NATIVE_TOOLS.values():
        if not defn.auto_attach:
            continue
        tool = defn.builder(ctx)
        if tool is not None:
            tools.append(tool)
    return tools


__all__ = [
    "NATIVE_TOOLS",
    "NativeToolContext",
    "NativeToolDef",
    "build_auto_attach_tools",
    "is_known_native_tool",
    "register_native_tool",
    "resolve_native_tool",
]
