"""``YamlDeepAgent``: one generic ``DeepAgent`` built from an ``AgentSpec``.

This is what makes agents declarative: a folder's ``agent.yaml`` is parsed
into an :class:`~harness.abstractions.agent_spec.AgentSpec` and handed to this
class, which reads its identity, prompt, models, tools, sub-agents and HITL
gates from it and feeds them into the same ``build_deep_agent()`` every Python
deep agent uses. No per-agent Python.

Identity (``name``/``agent_id``/``label``/…) is set per **instance** (one class
serves every YAML agent), so ``self.name`` resolves to the spec's slug
wherever the base reads it. The registry manifest is built from the spec by
``utils.declarative.manifest_from_spec``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deepagents import SubAgent

from core.logging import get_logger
from harness.abstractions.agent_spec import AgentSpec, SubAgentSpec, ToolRef
from harness.abstractions.deep_agent import DeepAgent
from harness.abstractions.subagent_tree import SUBAGENTS_KEY
from harness.tools.ask_user import ASK_USER_TOOL_NAME
from harness.tools.registry import resolve_native_tool
from utils.declarative import read_prompt
from utils.mcp_tools import build_tool_cache_key, get_tool_cache_key

logger = get_logger(__name__)


class YamlDeepAgent(DeepAgent):
    """A deep agent whose whole definition comes from an ``AgentSpec`` and its folder."""

    def __init__(
        self,
        spec: AgentSpec,
        source_dir: Path,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(config=config)
        self._spec = spec
        self._source_dir = Path(source_dir)
        # Per-instance identity, so every `self.name`/`self.label` read across
        # the base resolves to this spec.
        self.name = spec.slug
        self.agent_id = spec.id
        self.label = spec.name
        self.version = spec.version
        self.description = spec.description
        self.icon = spec.icon
        self.instructions = read_prompt(spec.prompt, self._source_dir)
        self.hitl_gates = dict(spec.hitl)
        # The declared MCP tools seed the live-tool filter; native refs are
        # resolved at build.
        self.config_tool_names = [
            build_tool_cache_key(t.server_id or "", t.tool_name or "")
            for t in spec.tools
            if not t.is_native
        ]
        self.all_mcp_tools = spec.all_mcp_tools

    @property
    def reference_dir(self) -> Path:
        """``/reference/``: the agent's own folder in the image.

        A declarative agent's definition is prompts and notes, so exposing it
        read-only makes bundled material (checklists, examples the prompt
        refers to) readable on demand instead of inlined into every turn.
        """
        return self._source_dir

    def _resolve_native_tools(self, refs: list[ToolRef]) -> list[Any]:
        """The bound native tools ``refs`` name; none without a client (registry warmup)."""
        if not self.client_id:
            return []
        ctx = self._native_context()
        resolved: list[Any] = []
        for ref in refs:
            if not ref.is_native or not ref.native:
                continue
            tool = resolve_native_tool(ref.native, ctx)
            if tool is not None:
                resolved.append(tool)
        return resolved

    def register_subagents(self) -> list[SubAgent]:
        """One ``SubAgent`` per spec entry, with its own model and tool subset.

        **An empty ``tools`` list means "inherit"**: the key is left out and
        the sub-agent gets the parent's full tool list. A non-empty list is an
        explicit restriction. Approval gates are never set here, so every
        sub-agent inherits the parent's: giving it a tool cannot route around
        its gate. Nested sub-agents come out the same way, under the
        ``subagents`` key of the spec above them.
        """
        # The parent's MCP tools as already filtered for this run, keyed the
        # way a ToolRef keys them. Natives are not in `self.tools` yet.
        parent_mcp = {get_tool_cache_key(tool): tool for tool in self.tools}
        return [self._subagent(sa, parent_mcp) for sa in self._spec.subagents]

    def _subagent(self, sa: SubAgentSpec, parent_mcp: Mapping[str, Any]) -> SubAgent:
        """One sub-agent's spec, with its own sub-agents under it."""
        spec = SubAgent(
            model=self._resolve_subagent_model(sa),
            name=sa.name,
            description=sa.description,
            system_prompt=read_prompt(sa.prompt, self._source_dir),
        )
        if sa.tools:
            spec["tools"] = self._resolve_subagent_tools(sa, parent_mcp)
        if sa.subagents:
            spec[SUBAGENTS_KEY] = [self._subagent(child, parent_mcp) for child in sa.subagents]  # type: ignore[literal-required]
        return spec

    def _resolve_subagent_tools(self, sa: SubAgentSpec, parent_mcp: Mapping[str, Any]) -> list[Any]:
        """A sub-agent's explicit tool subset, never wider than its parent.

        MCP refs are picked from the parent's already-filtered tools, so a tool
        the gateway does not serve right now is simply absent (and stays
        absent rather than widening to "inherit everything"). ``ask_user`` is
        never given to a sub-agent, even when listed.
        """
        tools = self._resolve_native_tools(
            [t for t in sa.tools if t.is_native and t.native != ASK_USER_TOOL_NAME]
        )
        missing: list[str] = []
        for ref in sa.tools:
            if ref.is_native:
                continue
            key = build_tool_cache_key(ref.server_id or "", ref.tool_name or "")
            tool = parent_mcp.get(key)
            if tool is None:
                missing.append(key)
            else:
                tools.append(tool)
        if missing:
            logger.warning(
                "yaml_subagent_tools_unavailable",
                "Sub-agent tools are not available to the parent agent in this run; skipped",
                agent_slug=self.name,
                subagent=sa.name,
                missing_tools=sorted(missing),
            )
        return tools

    def _resolve_subagent_model(self, sa: SubAgentSpec) -> str:
        """Sub-agent model: explicit, then ``model.subagents[name]``, then the main model."""
        return sa.model or self._spec.model.subagents.get(sa.name) or self._spec.model.main

    def definition_fingerprint(self) -> str:
        """A hash of the whole definition: the spec and the prompt it resolved to.

        Any edit that changes what runs changes it, so a task tree stays
        pinned to the definition its root run used.
        """
        payload = {"spec": self._spec.model_dump(mode="json"), "instructions": self.instructions}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def register_agent(self) -> Any:
        """The spec's native tools on top of the filtered MCP ones, then the shared build."""
        self.tools.extend(self._resolve_native_tools([t for t in self._spec.tools if t.is_native]))
        return self.build_deep_agent(
            model=self._spec.model.main,
            system_prompt=self.instructions,
            subagents=self.sub_agents,
            interrupt_on=self._spec.hitl,
        )


__all__ = ["YamlDeepAgent"]
