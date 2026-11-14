"""``BaseAgent``: what every agent kind shares, whatever builds its graph.

Identity and manifest, the validated run config (``run_config`` + ``context``),
the selection of live MCP tools, the stream loop that turns the compiled
graph's chunks into AG-UI frames, and the RUN_ERROR encoding. ``DeepAgent``
and ``LangGraphAgent`` add how the graph is built.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Literal
from uuid import uuid4

from langgraph.types import Command

from core.error_handling import agent_stream_error_handler
from core.logging import get_logger
from core.settings import settings
from harness.agui.emitter import encode, is_agui_events
from harness.checkpointer import get_checkpointer
from harness.memory.binding import validate_memory_context
from harness.observability import trace_run_config
from utils.mcp_tools import get_tool_cache_key

logger = get_logger(__name__)

# The closed set of agent kinds, as a manifest's ``type``.
AgentType = Literal["deep agent", "langgraph agent"]

#: The context keys every run must carry (``docs/contracts/agents-contract.md`` § Config).
REQUIRED_CONTEXT_KEYS = ("client_id", "conversation_id")


class BaseAgent:
    """Base plumbing shared by deep agents and LangGraph agents.

    One instance per request: identity read from ``self.context`` (the
    backend's anonymous ``client_id`` and the conversation) is safe to close
    over, because nothing is shared between runs.
    """

    # Stable slug used for registry lookups and URL routing.
    name: str = "base-agent"
    agent_id: str = "base-agent"
    label: str = "Base Agent"
    version: str = "0.0.1"
    type: AgentType = "langgraph agent"
    description: str | None = None
    icon: str | None = None
    #: The stream modes the compiled graph is streamed with.
    stream_mode: Any = "custom"
    #: Prefix for this family's execution log events.
    _log_domain: str = "agent"

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = self._validate_config(config) if config else {}
        # Never Optional: a config carrying `"run_config": None` falls back to
        # a fresh thread rather than failing at stream time.
        configured_run_config = self.config.get("run_config")
        self.run_config: Mapping[str, Any] = (
            configured_run_config
            if configured_run_config is not None
            else {"configurable": {"thread_id": str(uuid4())}}
        )
        # The MCP tools this agent declares, as cache keys; a deep agent fills
        # them from its spec. `all_mcp_tools` takes every live gateway tool.
        self.config_tool_names: list[str] = []
        self.all_mcp_tools: bool = False
        # Resolved tools (populated per stream after loading from MCP).
        self.tools: list[Any] = []
        self.tools_names: list[str] = []
        self.context: dict[str, Any] = self.config.get("context", {})

    # ---------------------------------------------------------------------
    # Metadata
    # ---------------------------------------------------------------------
    @property
    def metadata(self) -> dict[str, Any]:
        """The class-level manifest of this agent."""
        return self.__class__.manifest()

    @classmethod
    def manifest(cls) -> dict[str, Any]:
        """The registry manifest describing this agent."""
        return {
            "id": cls.agent_id,
            "slug": cls.name,
            "name": cls.label,
            "version": cls.version,
            "type": cls.type,
            "description": cls.description or "",
            "icon": cls.icon or "",
        }

    @property
    def client_id(self) -> str:
        """The run's owner key: the backend's anonymous browser id (never logged raw)."""
        return str(self.context.get("client_id") or "")

    # ---------------------------------------------------------------------
    # Tool management
    # ---------------------------------------------------------------------
    def attach_tools(self, live_tools: Sequence[Any]) -> None:
        """Filter and attach the live MCP tools for the next run."""
        self._apply_live_tools(self._filter_live_tools(live_tools))

    def _filter_live_tools(self, tools: Sequence[Any]) -> list[Any]:
        """The live gateway tools this run attaches: the declared ones, or all of them.

        Builtins are structurally out of reach here: only live gateway tools
        are considered.
        """
        desired = set(self.config_tool_names)
        if not (desired or self.all_mcp_tools):
            return []
        if not settings.mcp.enabled:
            logger.info(
                "agent_tools_mcp_disabled",
                "MCP is not enabled; running without the agent's MCP tools",
                agent_slug=self.name,
            )
            return []
        resolved: list[Any] = []
        seen: set[str] = set()
        for tool in tools:
            key = get_tool_cache_key(tool)
            if key not in seen and (self.all_mcp_tools or key in desired):
                resolved.append(tool)
                seen.add(key)
        missing = desired - seen
        if missing:
            logger.warning(
                "agent_tools_missing",
                "Declared tools were not found in the live MCP tools",
                agent_slug=self.name,
                missing_tools=sorted(missing),
            )
        logger.info(
            "agent_tools_resolved",
            "Resolved the agent's MCP tools",
            agent_slug=self.name,
            resolved_count=len(seen),
            all_mcp_tools=self.all_mcp_tools,
        )
        return resolved

    def _apply_live_tools(self, tools: Sequence[Any]) -> None:
        """Attach the filtered live tools."""
        self.tools.extend(list(tools))
        self.tools_names = [getattr(tool, "name", "") for tool in self.tools]

    # ---------------------------------------------------------------------
    # Config validation
    # ---------------------------------------------------------------------
    def _validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """A normalised copy of the run config (the caller's object is never mutated)."""
        normalised = dict(config)
        run_config = normalised.get("run_config")
        if run_config is not None:
            normalised["run_config"] = self._validate_run_config(run_config)
        context = normalised.get("context")
        if context is not None:
            normalised["context"] = self._validate_context_config(context)
        return normalised

    @staticmethod
    def _validate_run_config(run_config: Mapping[str, Any]) -> dict[str, Any]:
        """Ensure run_config is a mapping with a mapping ``configurable``."""
        if not isinstance(run_config, Mapping):
            raise TypeError("Agent config 'run_config' must be a mapping.")
        normalised = dict(run_config)
        configurable = normalised.get("configurable")
        if configurable is not None and not isinstance(configurable, Mapping):
            raise TypeError("Agent run_config 'configurable' must be a mapping.")
        return normalised

    @staticmethod
    def _validate_context_config(context: Mapping[str, Any]) -> dict[str, Any]:
        """The run context, with the client and conversation ids required."""
        if not isinstance(context, Mapping):
            raise TypeError("Agent config 'context' must be a mapping.")
        normalised = dict(context)
        for key in REQUIRED_CONTEXT_KEYS:
            val = normalised.get(key)
            if val is None or not isinstance(val, str) or not val.strip():
                raise ValueError(f"Agent config 'context' must include a non-empty '{key}' string.")
            normalised[key] = val.strip()
        # Optional: the audited system whose memory the run shares.
        validate_memory_context(normalised)
        return normalised

    # ---------------------------------------------------------------------
    # Build + streaming, shared by both agent families
    # ---------------------------------------------------------------------
    @property
    def compiled(self) -> Any:
        """The compiled runnable. ``None`` until :meth:`ensure_built` has run."""
        raise NotImplementedError

    async def ensure_built(self) -> None:
        """Assemble the runnable. Idempotent: ``astream`` and ``/resume`` both call it."""
        raise NotImplementedError

    def _stream_kwargs(self) -> dict[str, Any]:
        """Extra keyword arguments for the runnable's ``astream`` (none by default)."""
        return {}

    def _traced_config(self) -> Mapping[str, Any]:
        """``run_config`` plus this run's Langfuse trace; the same config when tracing is off.

        Nested under the backend's trace when the request carried one
        (``config.trace``). A background sub-agent's run lands in its parent's
        session, tagged ``subagent``.
        """
        ctx = self.context
        thread_id = self.run_config.get("configurable", {}).get("thread_id")
        trace = self.config.get("trace")
        return trace_run_config(
            self.run_config,
            kind="subagent" if ctx.get("async_task_id") else "chat",
            name=self.name,
            trace=trace if isinstance(trace, Mapping) else None,
            session_id=ctx.get("conversation_id") or thread_id,
            user_id=self.client_id or None,
            tags=(self.name,),
        )

    def _durable_checkpointer(self) -> Any:
        """The process-wide durable saver, or ``None`` for a thread-less run."""
        thread_id = self.run_config.get("configurable", {}).get("thread_id") or ""
        return get_checkpointer() if thread_id else None

    async def astream(
        self, payload: Mapping[str, Any], *, command: Command | None = None
    ) -> AsyncIterator[bytes]:
        """Build on demand and stream the run as AG-UI SSE bytes.

        ``command`` (a ``Command(resume=...)``) replaces ``payload`` so a run
        paused on a HITL interrupt resumes from its saved checkpoint.
        """
        try:
            await self.ensure_built()
            logger.info(
                f"{self._log_domain}_execution_started",
                "Agent execution started",
                agent_slug=self.name,
                resumed=command is not None,
            )
            stream_input: Any = command if command is not None else payload
            async for chunk in self.compiled.astream(
                stream_input,
                config=self._traced_config(),
                stream_mode=self.stream_mode,
                **self._stream_kwargs(),
            ):
                if isinstance(chunk, (str, bytes)):
                    yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk
                elif is_agui_events(chunk):
                    # A LangGraph node wrote emitter events to its stream writer
                    # unencoded (``send`` would have encoded them already).
                    for event in chunk if isinstance(chunk, list) else [chunk]:
                        yield encode(event)
                else:
                    for agui_event in self.agui_normalizer.handle_chunk(chunk):
                        yield agui_event
            logger.info(
                f"{self._log_domain}_execution_completed",
                "Agent execution completed",
                agent_slug=self.name,
            )
        # A disconnected client is the normal way a stream ends early (the
        # backend closes it on cancel); not an error, never encoded as one.
        except (BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
            logger.info(
                f"{self._log_domain}_execution_cancelled",
                "Agent execution cancelled",
                agent_slug=self.name,
            )
            return
        except Exception as exc:
            yield self._encode_run_error(exc)

    # ---------------------------------------------------------------------
    # Error encoding
    # ---------------------------------------------------------------------
    @classmethod
    def _encode_run_error(cls, exc: BaseException) -> bytes:
        """Log the traceback and return a clean SSE RUN_ERROR frame."""
        return agent_stream_error_handler.encode_run_error(logger, exc, agent_slug=cls.name)
