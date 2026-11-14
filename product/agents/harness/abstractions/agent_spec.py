"""Declarative agent specification — the parsed, validated ``agent.yaml``.

This is the contract the declarative-agent system is built on: a folder
holding an ``agent.yaml`` (this schema) + an ``AGENT.md`` system prompt is
enough to register and run a deep agent, with no Python subclass.

Two layers of validation:

* **Structural (here):** strict Pydantic, ``extra="forbid"`` so a typo or an
  unsupported key fails loudly instead of silently changing behaviour; slug
  shape; and the tool-selector form (MCP vs native).
* **Referential (at load time):** model ids, native tool names, and the
  locked approval gates. Those registries are not imported here, so the check
  lives in the loader (``utils.agents``); see :meth:`AgentSpec.reference_errors`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.tools.builtins import locked_gates

# Kebab-case: lowercase alnum groups joined by single hyphens. Doubles as a
# path-safety guard — a slug is used as an on-disk directory name.
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: How many levels of sub-agents may sit below the main agent: 3 allows
#: main → researcher → fact-checker → source-verifier and no deeper. Every level
#: is a model call chain of its own, so depth multiplies cost and latency, and a
#: deeper tree is harder for a person to follow in the chat. Enforced on every
#: definition (YAML and code; see ``harness.abstractions.subagent_tree``).
MAX_SUBAGENT_DEPTH = 3

# The only agent type expressible in YAML. LangGraph agents are Python classes.
AgentSpecType = Literal["deep_agent"]


class ToolRef(BaseModel):
    """A single entry in an agent's tool list.

    Exactly one of two mutually exclusive forms:

    * **MCP tool** — ``server_id`` + ``tool_name``; resolved against the live
      MCP gateway manifest at build time.
    * **Native tool** — ``native``; resolved by name against the in-image
      native-tool registry.
    """

    model_config = ConfigDict(extra="forbid")

    server_id: str | None = None
    tool_name: str | None = None
    native: str | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> ToolRef:
        is_mcp = bool(self.server_id) and bool(self.tool_name)
        is_native = bool(self.native)
        # XOR: reject both-forms and neither-form.
        if is_mcp == is_native:
            raise ValueError(
                "ToolRef must be either an MCP tool ({server_id, tool_name}) "
                "or a native tool ({native}) — not both, not neither."
            )
        return self

    @property
    def is_native(self) -> bool:
        return self.native is not None

    def key(self) -> str:
        """Stable identity used for dedupe and per-agent disable matching."""
        return f"native::{self.native}" if self.is_native else f"{self.server_id}::{self.tool_name}"


class SubAgentSpec(BaseModel):
    """A sub-agent. Maps 1:1 to ``deepagents.SubAgent``.

    ``prompt`` is a path to a markdown file relative to the agent directory
    (e.g. ``./subagents/researcher.md``) or an inline string. ``model`` falls
    back to ``AgentSpec.model.subagents[name]`` and then the main model when
    omitted.

    ``tools`` empty means **inherit** every tool the agent above it has in the
    run; a non-empty list restricts the sub-agent to exactly those, and must be
    a subset of what the agent above it may use (``AgentSpec`` enforces it).

    ``subagents`` are its own sub-agents, which it delegates to with ``task``
    exactly as the main agent does — at most :data:`MAX_SUBAGENT_DEPTH` levels
    below the main agent in all.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    prompt: str
    model: str | None = None
    tools: list[ToolRef] = Field(default_factory=list)
    subagents: list[SubAgentSpec] = Field(default_factory=list)


class ModelSpec(BaseModel):
    """Models an agent uses: one required main model + optional per-sub-agent
    overrides keyed by sub-agent name (e.g. ``{researcher: openai:gpt-4o}``)."""

    model_config = ConfigDict(extra="forbid")

    main: str
    subagents: dict[str, str] = Field(default_factory=dict)


class AgentSpec(BaseModel):
    """Top-level declarative agent definition — the parsed ``agent.yaml``.

    Field → runtime mapping (``BaseAgent`` class attributes and ``manifest()``):

    ==========  ===========================================
    spec field  runtime attribute (today)
    ==========  ===========================================
    ``id``      ``agent_id``
    ``slug``    ``name``   (registry key + folder name)
    ``name``    ``label``  (display name)
    ``version`` ``version``
    ``type``    ``AgentType``
    ``prompt``  ``instructions`` / ``system_prompt``
    ``model``   ``create_deep_agent(model=..., subagents=...)``
    ``tools``   the agent's declared tool set (native ∪ MCP)
    ``all_mcp_tools``  every tool the MCP gateway serves, besides ``tools``
    ``hitl``    ``interrupt_on={...}``
    ==========  ===========================================
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    name: str
    version: str
    type: AgentSpecType
    description: str = ""
    icon: str = ""
    # Path to the markdown system prompt (``./AGENT.md``) or an inline string.
    prompt: str
    model: ModelSpec
    # The agent's declared tools. Empty = the native builtins and sub-agents only.
    tools: list[ToolRef] = Field(default_factory=list)
    # Attach every tool the MCP gateway serves (beside the declared ones), so
    # a server added to the gateway reaches the agent without a definition edit.
    all_mcp_tools: bool = False
    subagents: list[SubAgentSpec] = Field(default_factory=list)
    # Tools gated behind human approval, e.g. {"write_file": true, "start_async_task": true}.
    hitl: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_slug(self) -> AgentSpec:
        if not SLUG_RE.match(self.slug):
            raise ValueError(
                f"Invalid agent slug {self.slug!r}: must be kebab-case matching {SLUG_RE.pattern}."
            )
        return self

    @model_validator(mode="after")
    def _subagent_tree_is_valid(self) -> AgentSpec:
        """The sub-agent tree: bounded, unambiguous, and least-privilege.

        * at most :data:`MAX_SUBAGENT_DEPTH` levels below the main agent;
        * sibling names are unique — the model picks a sub-agent by name;
        * no sub-agent shares a name with one above it — ``researcher`` under
          ``researcher`` reads as a loop to the model, and to a person;
        * a sub-agent may only narrow the tools of the agent above it, never
          add to them. Delegating must not be a way to reach a tool the agent
          itself was never given. An empty list means "inherit" and is always
          valid; what it inherits is whatever the agent above may use. With
          ``all_mcp_tools`` any MCP tool is the agent's to hand down.
        """

        def check(
            subagents: list[SubAgentSpec], *, allowed: set[str], above: tuple[str, ...]
        ) -> None:
            depth = len(above) + 1
            names = [sa.name for sa in subagents]
            duplicates = sorted({n for n in names if names.count(n) > 1})
            if duplicates:
                where = f"under {above[-1]!r}" if above else "of the agent"
                raise ValueError(f"Sub-agents {where} share a name: {', '.join(duplicates)}.")
            for sa in subagents:
                path = " > ".join((*above, sa.name))
                if depth > MAX_SUBAGENT_DEPTH:
                    raise ValueError(
                        f"Sub-agent {path!r} is {depth} levels below the agent; "
                        f"at most {MAX_SUBAGENT_DEPTH} are allowed."
                    )
                if sa.name in above:
                    raise ValueError(
                        f"Sub-agent {path!r} repeats a name above it; sub-agents cannot loop."
                    )
                own = {ref.key() for ref in sa.tools}
                extra = sorted(
                    key
                    for key in own - allowed
                    if not (mcp_open and not key.startswith("native::"))
                )
                if extra:
                    shown = ", ".join(k.replace("native::", "").replace("::", "/") for k in extra)
                    if above:
                        raise ValueError(
                            f"Sub-agent {path!r} lists tools sub-agent {above[-1]!r} "
                            f"does not have: {shown}. "
                            "A sub-agent can only use a subset of the tools of the agent above it."
                        )
                    raise ValueError(
                        f"Sub-agent {sa.name!r} lists tools the agent itself does not "
                        f"declare: {shown}. "
                        "A sub-agent can only use a subset of its agent's tools."
                    )
                check(sa.subagents, allowed=own or allowed, above=(*above, sa.name))

        mcp_open = self.all_mcp_tools
        check(self.subagents, allowed={ref.key() for ref in self.tools}, above=())
        return self

    def walk_subagents(self) -> Iterator[tuple[tuple[str, ...], SubAgentSpec]]:
        """Every sub-agent at every depth, parents first, with its name path
        (``("researcher", "fact-checker")``)."""

        def walk(subagents: list[SubAgentSpec], above: tuple[str, ...]):
            for sa in subagents:
                path = (*above, sa.name)
                yield path, sa
                yield from walk(sa.subagents, path)

        yield from walk(self.subagents, ())

    def all_model_ids(self) -> list[str]:
        """Every model id referenced (main + per-name + sub-agent overrides).

        Used by the loader to validate against the model registry."""
        ids = {self.model.main, *self.model.subagents.values()}
        ids.update(sa.model for _, sa in self.walk_subagents() if sa.model)
        return sorted(i for i in ids if i)

    def native_tool_names(self) -> list[str]:
        """Every native-tool name referenced (agent + sub-agent tool lists).

        Used by the loader to validate against the native-tool registry."""
        names = {t.native for t in self.tools if t.is_native}
        for _, sa in self.walk_subagents():
            names.update(t.native for t in sa.tools if t.is_native)
        return sorted(n for n in names if n)

    def reference_errors(
        self,
        *,
        is_known_model: Callable[[str], bool],
        is_known_native_tool: Callable[[str], bool],
    ) -> list[str]:
        """Referential validation hook run by the loader once the registries
        exist. Returns a list of human-readable errors (empty = valid), so the
        discoverer can reject an agent with a clear message instead of failing
        deep inside ``build_deep_agent``.
        """
        errors: list[str] = []
        for model_id in self.all_model_ids():
            if not is_known_model(model_id):
                errors.append(f"unknown model id: {model_id!r}")
        for tool_name in self.native_tool_names():
            if not is_known_native_tool(tool_name):
                errors.append(f"unknown native tool: {tool_name!r}")
        # A mandated gate (``execute``) cannot be cleared from YAML: the run
        # would force it back on anyway, so a definition saying otherwise is
        # refused at load time rather than silently overridden.
        locked = locked_gates()
        for tool_name, asks in self.hitl.items():
            if tool_name in locked and not asks:
                errors.append(
                    f"hitl.{tool_name}: {tool_name!r} always asks for approval and "
                    "cannot be set to false"
                )
        return errors


SubAgentSpec.model_rebuild()

__all__ = [
    "MAX_SUBAGENT_DEPTH",
    "AgentSpec",
    "AgentSpecType",
    "ModelSpec",
    "SubAgentSpec",
    "ToolRef",
]
