"""``DeepAgent``: the deepagents base every deep agent (YAML or code) builds through.

It owns everything that is the same for every deep agent, so a concrete agent
only says what differs (model, prompt, sub-agents, gates):

* the workspace (``harness.filesystem.workspace``): the conversation's files
  and the branch scratch, shared by the orchestrator and every sub-agent;
* the native builtins (``present_artifact``, ``view_image``, ``render_chart``,
  ``ask_user``) and the approval gates (``harness.tools.gates``);
* the middleware guarantees (tool errors as results, rate limits waited out,
  the tuned summarizer) at every depth;
* the composed system prompt (``harness.prompt_engineering``);
* sub-agents: blocking ``task`` at any depth, or async background tasks
  (``ASYNC_SUBAGENTS_ENABLED``) through ``AsyncTaskMiddleware``, and the build
  of one task's node when the task runner sets ``async_task_node``.
"""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from deepagents import ProviderProfile, create_deep_agent, register_provider_profile
from deepagents._models import resolve_model
from deepagents.backends import CompositeBackend

# Both private. `_merge_fs_interrupt_on` is the very merge create_deep_agent
# applies to its own sub-agents' gates (a sub-agent built below depth 1 must get
# the same); `_LEGACY_BASE_AGENT_PROMPT` is the base prompt deepagents 0.6.x
# appended to every main agent, kept so the instructions do not change with 0.7.
from deepagents.graph import _LEGACY_BASE_AGENT_PROMPT, _merge_fs_interrupt_on
from deepagents.middleware._fs_interrupt import _build_interrupt_on_from_permissions
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT, SubAgentMiddleware
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents.middleware import ModelRefusalMiddleware, TodoListMiddleware
from langgraph.checkpoint.memory import MemorySaver

from core.logging import get_logger
from core.settings import settings
from harness.abstractions.base_agent import AgentType, BaseAgent
from harness.abstractions.subagent_tree import SUBAGENTS_KEY, validate_subagent_tree
from harness.agui import AGUIEmitter, AGUIStreamNormalizer
from harness.async_tasks.client import AsyncTaskMiddleware
from harness.async_tasks.specs import (
    TaskNode,
    async_subagent_specs,
    disable_blocking_general_purpose,
    resolve_chain,
    supports_async,
    top_level,
)
from harness.async_tasks.token import InheritedContext, mint_launch_token, trace_carrier
from harness.checkpointer import get_runtime_pool
from harness.conversation_files import ConversationFiles, ConversationFileStore
from harness.filesystem import (
    build_workspace_backend,
    filesystem_middleware,
    resolve_branch_thread_id,
    workspace_write_deny,
)
from harness.memory import (
    MemoryBinding,
    SystemMemoryFiles,
    SystemMemoryStore,
    memory_binding_from_context,
)
from harness.memory.binding import MEMORY_CONTEXT_KEYS
from harness.memory.entries import is_valid_id
from harness.middlewares import (
    RetryOnRateLimitMiddleware,
    ToolErrorMiddleware,
    build_summarization_middleware,
    exclude_stock_summarization,
)
from harness.models import register_reasoning_summaries
from harness.models.gemini import ensure_specs_configured
from harness.prompt_engineering import (
    PromptContext,
    compose_system_prompt,
    compose_task_prompt,
    describe_sections,
    task_sections,
)
from harness.prompt_engineering.prompts.capabilities_prompt import delegating_subagent_prompt
from harness.prompt_engineering.prompts.memory_prompt import memory_prompt
from harness.tools.ask_user import ASK_USER_TOOL_NAME
from harness.tools.gates import resolve_interrupt_on, strip_reserved_names
from harness.tools.present_artifact import PresentedFiles
from harness.tools.registry import NativeToolContext, build_auto_attach_tools
from harness.tools.workspace_api import WorkspaceAPI, WorkspaceScope

logger = get_logger(__name__)

#: The memory tools a narrowed sub-agent tool list still gets.
MEMORY_TOOL_NAMES = ("remember", "forget")

STREAMING_MODES = Literal["updates", "messages", "tasks"]
SubAgentsT = Sequence[Any] | Mapping[str, Any] | None


def model_specs(model: Any, subagents: SubAgentsT) -> set[str]:
    """Every string model spec in an agent's tree: its own and each sub-agent's, at any depth."""
    specs: set[str] = {model} if isinstance(model, str) and model else set()

    def walk(nodes: Any) -> None:
        if isinstance(nodes, Mapping):
            items: Any = nodes.values()
        elif isinstance(nodes, (list, tuple)):
            items = nodes
        else:
            items = ()
        for node in items:
            if not isinstance(node, Mapping):
                continue  # a pre-compiled runnable: its model is already built
            node_model = node.get("model")
            if isinstance(node_model, str) and node_model:
                specs.add(node_model)
            walk(node.get(SUBAGENTS_KEY))

    walk(subagents)
    return specs


def _without_ask_user(tools: Sequence[Any] | None) -> list[Any]:
    """``tools`` minus ``ask_user``: only the main agent may pause the run on a
    question, at any depth (the tool also refuses a sub-agent's call)."""
    return [t for t in (tools or []) if getattr(t, "name", None) != ASK_USER_TOOL_NAME]


def ensure_planning_and_filesystem(
    stack: Sequence[Any] | None, backend: Any, permissions: list[Any]
) -> list[Any]:
    """``stack`` with ``write_todos`` and our filesystem middleware guaranteed.

    deepagents 0.7 no longer adds ``TodoListMiddleware`` to a deep agent or its
    sub-agents, and its own filesystem middleware differs from 0.6.x (see
    :mod:`harness.filesystem.middleware`). Both are put back here (never
    duplicated). The write-deny rules ride this middleware.
    """
    items = list(stack or [])
    if not any(isinstance(m, TodoListMiddleware) for m in items):
        items.insert(0, TodoListMiddleware())
    if not any(isinstance(m, FilesystemMiddleware) for m in items):
        items.insert(1, filesystem_middleware(backend, permissions))
    return items


def _unique_by_name(tools: Sequence[Any]) -> list[Any]:
    """``tools`` with each name once, the first kept: the model API rejects two
    tools with one name (a spec may list a native tool that is also always-on)."""
    seen: set[str] = set()
    unique: list[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if name is not None and name in seen:
            continue
        if name is not None:
            seen.add(name)
        unique.append(tool)
    return unique


class DeepAgent(BaseAgent, ABC):
    """Blueprint for deep agents: a concrete subclass implements ``register_agent()``.

    Build lifecycle (run by ``ensure_built()`` on the first ``astream``):

        register_subagents() → self.sub_agents  (nested agents, if any)
        register_agent()  ★  → self.agent       (the final runnable, via build_deep_agent)

    Checkpointing: the process-wide durable saver when the run has a thread,
    else an ephemeral ``MemorySaver``.
    """

    # `provider:model` specs whose context window this process has declared.
    _windows_registered: set[str] = set()

    # "tasks" emits no events of its own: it tells the normalizer which `task`
    # call each sub-agent namespace runs (exact for parallel and nested
    # sub-agents, and on a /resume stream).
    stream_mode: list[STREAMING_MODES] = ["messages", "updates", "tasks"]
    _log_domain: str = "deep_agent"
    type: AgentType = "deep agent"

    # The system prompt, passed to create_deep_agent(system_prompt=...).
    instructions: str = ""
    # Approval gates the agent declares (``hitl:`` for a YAML agent).
    hitl_gates: Mapping[str, bool] | None = None

    # A background task's node of the tree, set per instance by the task
    # runner; None builds the main agent.
    async_task_node: TaskNode | None = None

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config=config)
        # Built on first use and shared by the mounts and the file tools.
        self._conversation_files: ConversationFiles | None = None
        # The run's accepted presentations: filled by present_artifact,
        # drained by the normalizer into PRESENT_ARTIFACT events.
        self.presented = PresentedFiles()
        self.checkpointer: Any = None
        # The audited system's memory (``system_id`` in the context), resolved
        # by ``ensure_built``: the mount, and the index the prompt carries.
        self._memory_files: SystemMemoryFiles | None = None
        self._memory_index: str | None = None
        self._workspace_api_client: WorkspaceAPI | None = None
        self.sub_agents: SubAgentsT = None
        self.agent: Any = None
        self.async_task_node = None
        # AG-UI message ids and sub-agent bindings are keyed on the run id
        # (the assistant message), falling back to the thread.
        self.agui_emitter: AGUIEmitter = AGUIEmitter()
        self.agui_normalizer: AGUIStreamNormalizer = AGUIStreamNormalizer(
            thread_id=self.context.get("run_id")
            or self.run_config.get("configurable", {}).get("thread_id", ""),
            presented=self.presented,
        )

    @property
    def compiled(self) -> Any:
        """The runnable assembled by ``register_agent()``. ``None`` until built."""
        return self.agent

    def _stream_kwargs(self) -> dict[str, Any]:
        """``subgraphs=True`` so a sub-agent's chunks arrive namespaced."""
        return {"subgraphs": True}

    # ---------------------------------------------------------------------
    # The conversation's files
    # ---------------------------------------------------------------------
    @property
    def conversation_files(self) -> ConversationFiles:
        """This run's view of its conversation's files, one per run.

        ``client_id`` and ``conversation_id`` come from ``self.context``,
        which ``BaseAgent._validate_context_config`` guarantees.
        """
        if self._conversation_files is None:
            ctx = self.context
            self._conversation_files = ConversationFiles(
                client_id=ctx["client_id"],
                conversation_id=ctx["conversation_id"],
                agent_slug=self.name,
                store=ConversationFileStore(get_runtime_pool()),
                run_id=ctx.get("run_id"),
            )
        return self._conversation_files

    def _build_composite_backend(self) -> CompositeBackend:
        """This run's ``CompositeBackend`` (the mount table lives in the workspace module).

        The scratch store is keyed by the branch: a task run (its own thread)
        reads its root's ``branch_thread_id`` from the context, so the whole
        tree shares one scratch.
        """
        return build_workspace_backend(
            client_id=self.context["client_id"],
            agent_slug=self.name,
            files=self.conversation_files,
            reference_dir=self.reference_dir,
            branch_thread_id=resolve_branch_thread_id(self.context, self.run_config),
            memory=self._memory_files,
        )

    # ---------------------------------------------------------------------
    # The audited system's memory
    # ---------------------------------------------------------------------
    def memory_store(self) -> Any:
        """The typed store behind ``/memory/`` and the memory tools (a seam for tests)."""
        return SystemMemoryStore(get_runtime_pool())

    def _memory_binding(self) -> MemoryBinding | None:
        """Whose memory this run uses, from the run context (never the model)."""
        node = self.async_task_node
        agent_name = f"{self.name}/{'/'.join(node.path)}" if node and node.path else self.name
        return memory_binding_from_context(
            self.context,
            agent_name=agent_name,
            thread_id=self.run_config.get("configurable", {}).get("thread_id"),
        )

    async def _prepare_memory(self) -> None:
        """Bind ``/memory/`` and load ``MEMORY.md`` for the prompt. Fail-open:
        a memory outage costs the lessons, never the run."""
        binding = self._memory_binding()
        if binding is None:
            return
        files = SystemMemoryFiles(
            self.memory_store(),
            binding,
            max_entries=settings.memory.max_entries_per_system,
            loop=asyncio.get_running_loop(),
        )
        try:
            index, records = await files.index_text()
        except Exception as exc:
            logger.warning(
                "system_memory_index_unavailable",
                "Could not load the system memory index; building without it",
                agent_slug=self.name,
                system_id=binding.system_id,
                failure_reason=type(exc).__name__,
            )
            index, records = "_System memory is unavailable for this run._", []
        self._memory_files = files
        self._memory_index = index
        logger.info(
            "system_memory_bound",
            "Bound the run to its system memory",
            agent_slug=self.name,
            system_id=binding.system_id,
            audit_id=binding.audit_id,
            step=binding.step,
            entries=len(records),
        )

    def _with_memory_prompt(self, prompt: Any) -> Any:
        """A blocking sub-agent's prompt plus the memory section (unchanged without memory)."""
        if self._memory_files is None or not (prompt is None or isinstance(prompt, str)):
            return prompt
        section = memory_prompt(self.prompt_context())
        return f"{(prompt or '').strip()}\n\n{section}".strip()

    def _with_memory_tools(self, tools: Sequence[Any]) -> list[Any]:
        """``tools`` plus the run's memory tools that a narrowed tool list left out."""
        if self._memory_files is None:
            return list(tools)
        names = {getattr(t, "name", None) for t in tools}
        extra = [
            t
            for t in self._builtin_tools()
            if getattr(t, "name", None) in MEMORY_TOOL_NAMES and t.name not in names
        ]
        return [*tools, *extra]

    @property
    def reference_dir(self) -> Path | None:
        """Folder to mount read-only at ``/reference/``, or ``None`` for no mount.

        ``None`` by default: an agent written in code has no such folder, and
        its package directory holds source, which must never be readable from
        a run. A declarative agent overrides it with its definition folder.
        """
        return None

    def default_middleware(self, model: Any, backend: Any) -> list[Any]:
        """The middleware stack a deep agent gets unless it overrides this.

        ``ToolErrorMiddleware`` and ``RetryOnRateLimitMiddleware`` are
        guaranteed by ``build_deep_agent`` regardless. The summarizer replaces
        deepagents' stock one with env-tuned thresholds and offloads to
        ``backend`` (the conversation's files).
        """
        return [ToolErrorMiddleware(), build_summarization_middleware(model, backend)]

    def _native_context(self) -> NativeToolContext:
        """What a native tool builder needs, from this run's context."""
        conversation_id = self.context.get("conversation_id")
        return NativeToolContext(
            agent_slug=self.name,
            conversation_id=conversation_id,
            files=self.conversation_files if conversation_id else None,
            presented=self.presented,
            async_task_id=self.async_task_id,
            memory=self._memory_files.binding if self._memory_files else None,
            memory_store=self._memory_files.store if self._memory_files else None,
            workspace_scope=self._workspace_scope(),
            workspace_api=self._workspace_api(),
        )

    def _workspace_scope(self) -> WorkspaceScope | None:
        """The run's client and conversation scope (``system_id`` / ``audit_id``), or None."""
        if not self.client_id:
            return None
        system_id = self.context.get("system_id")
        audit_id = self.context.get("audit_id")
        return WorkspaceScope(
            client_id=self.client_id,
            agent_slug=self.name,
            system_id=system_id if is_valid_id(system_id) else None,
            audit_id=audit_id if is_valid_id(audit_id) else None,
        )

    def _workspace_api(self) -> WorkspaceAPI | None:
        """One product-API client per run, shared by every tool bound to it."""
        if not self.client_id:
            return None
        if self._workspace_api_client is None:
            self._workspace_api_client = WorkspaceAPI(
                client_id=self.client_id, agent_slug=self.name
            )
        return self._workspace_api_client

    def _builtin_tools(self) -> list[Any]:
        """The always-on native tools, each subject to its gate (none without a client)."""
        if not self.client_id:
            return []
        return build_auto_attach_tools(self._native_context())

    @property
    def async_task_id(self) -> str | None:
        """The background task this run is, or ``None`` for a chat turn.

        The task runner puts it in the run context; a task run never gets
        ``ask_user``."""
        value = self.context.get("async_task_id")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def interactive(self) -> bool:
        """Whether someone is there to answer this run (a chat turn always is)."""
        return bool(self.context.get("interactive", True))

    @staticmethod
    def _ensure_platform_middleware(stack: Sequence[Any] | None) -> list[Any]:
        """Every guarantee a deep agent's or sub-agent's stack gets.

        ``ToolErrorMiddleware`` (prepended if missing): a tool error degrades to
        a ToolMessage instead of aborting the run. ``RetryOnRateLimitMiddleware``
        (first, so outermost): a provider rate limit pauses the agent instead of
        failing the run. Never duplicated.
        """
        items = list(stack or [])
        if not any(isinstance(m, ToolErrorMiddleware) for m in items):
            items.insert(0, ToolErrorMiddleware())
        if not any(isinstance(m, RetryOnRateLimitMiddleware) for m in items):
            items.insert(0, RetryOnRateLimitMiddleware())
        return items

    def prompt_context(
        self,
        *,
        has_subagents: bool = False,
        async_subagents: bool = False,
    ) -> PromptContext:
        """What this run has, for the prompt composer to describe.

        Every field is read from the same flag that builds the thing it names,
        so a section can never advertise a mount or tool the run lacks.
        """
        has_conversation = bool(self.context.get("conversation_id"))
        scope = self._workspace_scope()
        return PromptContext(
            has_subagents=has_subagents,
            async_subagents=async_subagents,
            has_conversation=has_conversation,
            narrate_progress=has_conversation,
            narrate_as_subagent=self.async_task_id is not None,
            # The same gate as the tool's builder: never describe a tool the run lacks.
            has_ask_user=bool(self.client_id and has_conversation) and self.async_task_id is None,
            has_reference=self.reference_dir is not None,
            sandbox_enabled=settings.filesystem.sandbox_execution_active,
            memory_index=self._memory_index if self._memory_files is not None else None,
            memory_audit_id=self._memory_files.binding.audit_id if self._memory_files else None,
            scope_system_id=scope.system_id if scope else None,
            scope_audit_id=scope.audit_id if scope else None,
            now=datetime.now(UTC),
        )

    @classmethod
    def register_model_windows(cls) -> None:
        """Declare the context window of models newer than the pinned LangChain.

        Compaction reads a model's window from its LangChain profile; a model
        released after the pinned ``langchain-openai`` (``gpt-6-luna``) has
        none, so its ``context_window`` from ``AGENT_MODELS`` is handed to the
        model through deepagents' ``ProviderProfile`` when it resolves the spec.
        Runs before anything in the build resolves a model.
        """
        for spec, info in settings.registry.models.items():
            window = info.context_window
            if window is None or spec in cls._windows_registered:
                continue
            register_provider_profile(
                spec, ProviderProfile(init_kwargs={"profile": {"max_input_tokens": window}})
            )
            cls._windows_registered.add(spec)
            logger.info(
                "model_window_registered",
                "Declared a model's context window",
                model=spec,
                window=window,
            )

    def build_deep_agent(
        self,
        *,
        model: Any,
        system_prompt: Any = None,
        subagents: SubAgentsT = None,
        interrupt_on: Mapping[str, bool] | None = None,
        middleware: list[Any] | None = None,
    ) -> Any:
        """Assemble the runnable with the fixed workspace wiring injected from the base.

        Concrete agents call this from ``register_agent()`` and supply only
        what differs: model, system prompt, sub-agents and approval gates.
        Agent-specific tools come from ``self.tools``. ``middleware`` defaults
        to ``default_middleware(model, backend)``; deepagents' stock summarizer
        is dropped so ours is the only one.

        With ``ASYNC_SUBAGENTS_ENABLED`` every sub-agent is a background task:
        ``AsyncTaskMiddleware`` gives the agent the async task tools instead of
        ``task``. With ``async_task_node`` set (a task run), the node of the
        tree that task is gets built instead of the main agent.
        """
        # Before anything resolves the model: the window rides the profile,
        # and so does a reasoning model's request for its reasoning summary.
        specs = model_specs(model, subagents)
        # A Gemini spec without a key stops here with a message the UI shows.
        ensure_specs_configured(specs)
        self.register_model_windows()
        register_reasoning_summaries(specs)
        backend = self._build_composite_backend()
        resolved_tools = _unique_by_name([*self.tools, *self._builtin_tools()])
        # `is not None`, not truthiness: a spec that declares no gates passes
        # `{}` and must not fall back to the class attribute.
        own_gates = interrupt_on if interrupt_on is not None else self.hitl_gates
        # Derived from the same flag as the mount, so a rule can never point
        # at a route this run did not mount.
        permissions = workspace_write_deny(include_reference=self.reference_dir is not None)

        if self.async_task_node is not None:
            return self._build_task_node(
                model=model,
                subagents=subagents,
                backend=backend,
                tools=resolved_tools,
                own_gates=own_gates,
                permissions=permissions,
            )

        use_async = self._uses_async_subagents(subagents)
        stack = middleware if middleware is not None else self.default_middleware(model, backend)
        stack = self._ensure_platform_middleware(stack)
        exclude_stock_summarization(model if isinstance(model, str) else "")

        # The agent's own instructions lead; the platform sections follow.
        prompt_context = self.prompt_context(
            has_subagents=bool(subagents), async_subagents=use_async
        )
        system_prompt = compose_system_prompt(system_prompt, prompt_context)
        logger.info(
            "deep_agent_prompt_composed",
            "Composed the system prompt from the agent's instructions",
            agent_slug=self.name,
            sections=describe_sections(prompt_context),
        )
        resolved_interrupt_on = resolve_interrupt_on(own_gates)
        stack = ensure_planning_and_filesystem(stack, backend, permissions)

        if use_async:
            # Every sub-agent, the general-purpose one included, is an async
            # task: the task tools replace the blocking `task`, which
            # deepagents would otherwise still add for general-purpose.
            validate_subagent_tree(subagents or [])
            stack.append(
                self._task_middleware(
                    top_level(subagents, None),
                    parent_path=(),
                    launch_token=self._launch_token(),
                )
            )
            disable_blocking_general_purpose(model)
            augmented_subagents: SubAgentsT = None
        else:
            augmented_subagents = self._prepare_subagents(
                subagents,
                model=model,
                backend=backend,
                tools=resolved_tools,
                own_gates=own_gates,
                permissions=permissions,
            )

        return create_deep_agent(
            model=model,
            name=self.name,
            tools=resolved_tools,
            system_prompt=f"{system_prompt}\n\n{_LEGACY_BASE_AGENT_PROMPT}",
            subagents=augmented_subagents,
            interrupt_on=resolved_interrupt_on,
            middleware=stack,
            memory=None,
            skills=None,
            backend=backend,
            context_schema=self.context,
            checkpointer=self.checkpointer,
            store=None,
        )

    # ---------------------------------------------------------------------
    # Async sub-agents
    # ---------------------------------------------------------------------
    @property
    def async_subagents_supported(self) -> bool:
        """Whether this agent's sub-agents may run as background tasks.

        A task run rebuilds the agent from its definition, so an agent that
        cannot be rebuilt keeps the blocking path. True by default.
        """
        return True

    def definition_fingerprint(self) -> str:
        """The definition version a task tree is pinned to (the ``graph_id``'s).

        Code agents change only with a deploy, so their class and ``version``
        name them; declarative agents hash their definition instead. Hex only,
        so it can never contain the ``@`` or ``:`` of a graph id.
        """
        raw = f"{type(self).__module__}.{type(self).__qualname__}:{self.version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _branch_thread_id(self) -> str:
        """The orchestrator's branch thread: the run context's, else the run's thread."""
        value = (
            self.context.get("branch_thread_id")
            or self.run_config.get("configurable", {}).get("thread_id")
            or ""
        )
        return str(value)

    def _uses_async_subagents(self, subagents: SubAgentsT) -> bool:
        """Whether this build gives the agent async tasks instead of ``task``.

        All of: the flag is on, the agent can be rebuilt by a task run, the run
        has an identity to bind the tasks to (client, conversation, branch),
        and every node of the tree can be rebuilt from a path.
        """
        if not settings.async_tasks.enabled or not self.async_subagents_supported:
            return False
        if not (
            self.client_id and self.context.get("conversation_id") and self._branch_thread_id()
        ):
            return False
        if not supports_async(subagents):
            logger.warning(
                "async_subagents_unsupported_tree",
                "The sub-agent tree holds a compiled sub-agent; keeping blocking sub-agents",
                agent_slug=self.name,
            )
            return False
        return True

    def _inherited_context(self) -> InheritedContext:
        """What this run's children inherit: who is watching, and the trace to nest under."""
        if self.async_task_node is not None:
            return self.async_task_node.inherited
        return InheritedContext(
            interactive=self.interactive,
            trace=trace_carrier(self.config.get("trace")),
            # The audited system travels with the tree, so every task shares its memory.
            **{key: self.context[key] for key in MEMORY_CONTEXT_KEYS if self.context.get(key)},
        )

    def _launch_token(self) -> str:
        """The task-launch token this build's children are started with.

        Minted per build and bound to this run's identity and its place in the
        tree; ``/ap`` reads the caller from it, never from a request body.
        """
        node = self.async_task_node
        if node is not None:
            return mint_launch_token(
                client_id=node.client_id,
                conversation_id=node.conversation_id,
                root_run_id=node.root_run_id,
                branch_thread_id=node.branch_thread_id,
                caller_task_id=node.task_id,
                caller_depth=node.depth,
                caller_path=list(node.path),
                agent_slug=node.agent_slug,
                definition_version=node.definition_version,
                context=node.inherited,
            )
        branch = self._branch_thread_id()
        return mint_launch_token(
            client_id=self.client_id,
            conversation_id=str(self.context["conversation_id"]),
            root_run_id=str(self.context.get("run_id") or branch),
            branch_thread_id=branch,
            caller_task_id=None,
            caller_depth=0,
            caller_path=[],
            agent_slug=self.name,
            definition_version=self.definition_fingerprint(),
            context=self._inherited_context(),
        )

    def _task_middleware(
        self,
        children: Sequence[Mapping[str, Any]],
        *,
        parent_path: Sequence[str],
        launch_token: str,
    ) -> AsyncTaskMiddleware:
        """The async task tools over ``children``, served by this process's ``/ap``."""
        node = self.async_task_node
        return AsyncTaskMiddleware(
            async_subagents=async_subagent_specs(
                children,
                agent_slug=node.agent_slug if node is not None else self.name,
                definition_version=(
                    node.definition_version if node is not None else self.definition_fingerprint()
                ),
                parent_path=parent_path,
                launch_token=launch_token,
            )
        )

    def _build_task_node(
        self,
        *,
        model: Any,
        subagents: SubAgentsT,
        backend: Any,
        tools: Sequence[Any],
        own_gates: Mapping[str, bool] | None,
        permissions: list[Any],
    ) -> Any:
        """The graph of one background task: its node of the sub-agent tree.

        Resolved down the tree exactly as the blocking path resolves a
        sub-agent: the model defaults to the one above it, the tools to the
        ones above it (never ``ask_user``; a spec can only narrow them), the
        gates are the run's with its own on top. It is built as a deep agent of
        its own (planning, our filesystem with the write-deny rules, our
        summarizer, the platform middleware) on the same workspace backend as
        the agent, so it reads and writes the same conversation files and
        branch scratch, and, when it has children, with its own task tools.
        """
        node = self.async_task_node
        if node is None:
            raise RuntimeError("_build_task_node needs async_task_node")
        tree = subagents if isinstance(subagents, (list, tuple)) else None
        if tree:
            validate_subagent_tree(tree)
        chain = resolve_chain(tree, None, node.path)
        node_model = model
        node_tools: list[Any] = _without_ask_user(tools)
        for level in chain:
            node_model = level.get("model") or node_model
            node_tools = _without_ask_user(level["tools"]) if "tools" in level else node_tools
        node_tools = self._with_memory_tools(node_tools)
        spec = chain[-1]
        gates = self._subagent_gates(spec.get("interrupt_on"), own_gates)
        children = [
            child for child in (spec.get(SUBAGENTS_KEY) or []) if isinstance(child, Mapping)
        ]
        system_prompt = str(spec.get("system_prompt") or "")
        stack: list[Any] = [
            ToolErrorMiddleware(),
            build_summarization_middleware(node_model, backend),
            *(spec.get("middleware") or []),
        ]
        if children:
            stack.append(
                self._task_middleware(
                    children, parent_path=node.path, launch_token=self._launch_token()
                )
            )
            system_prompt = delegating_subagent_prompt(system_prompt, async_subagents=True)
        # The task's own platform sections: how to work with the shared files
        # and how to narrate for its task panel.
        prompt_context = self.prompt_context(has_subagents=bool(children), async_subagents=True)
        system_prompt = compose_task_prompt(system_prompt, prompt_context)
        stack = self._ensure_platform_middleware(
            ensure_planning_and_filesystem(stack, backend, permissions)
        )
        exclude_stock_summarization(node_model if isinstance(node_model, str) else "")
        disable_blocking_general_purpose(node_model)
        logger.info(
            "async_task_node_built",
            "Built a background task's node of the sub-agent tree",
            agent_slug=self.name,
            task_id=node.task_id,
            depth=node.depth,
            has_children=bool(children),
            tool_count=len(node_tools),
            sections=[name for name, _ in task_sections(prompt_context)],
        )
        return create_deep_agent(
            model=node_model,
            name=self.name,
            tools=node_tools,
            system_prompt=system_prompt,
            subagents=None,
            interrupt_on=gates,
            middleware=stack,
            memory=None,
            skills=None,
            backend=backend,
            context_schema=self.context,
            checkpointer=self.checkpointer,
            store=None,
        )

    # ---------------------------------------------------------------------
    # Blocking sub-agents, at every depth
    # ---------------------------------------------------------------------
    def _prepare_subagents(
        self,
        subagents: SubAgentsT,
        *,
        model: Any,
        backend: Any,
        tools: Sequence[Any],
        own_gates: Mapping[str, bool] | None,
        permissions: list[Any],
    ) -> SubAgentsT:
        """The main agent's sub-agent specs, ready for ``create_deep_agent``.

        deepagents builds the depth-1 sub-agents itself (planning, filesystem,
        summarization, PatchToolCalls, the run's gates). What this adds: the
        platform middleware; no ``ask_user``, ever (an inheriting sub-agent
        gets the main agent's tools minus it, and the general-purpose
        sub-agent is declared here so it is covered too); a ``task`` tool of
        its own when the spec lists sub-agents (built fully by
        :meth:`_nested_subagent`, since deepagents processes nothing below
        depth 1); and a spec's own gates re-resolved, so a sub-agent can add a
        gate but never clear a locked one.
        """
        if not isinstance(subagents, (list, tuple)):
            return subagents
        validate_subagent_tree(subagents)
        inherited = _without_ask_user(tools)
        prepared: list[Any] = []
        for raw in subagents:
            if not isinstance(raw, Mapping) or "runnable" in raw:
                prepared.append(raw)
                continue
            spec = dict(raw)
            children = spec.pop(SUBAGENTS_KEY, None) or []
            spec["tools"] = self._with_memory_tools(
                _without_ask_user(spec["tools"]) if "tools" in spec else list(inherited)
            )
            if "interrupt_on" in spec:
                spec["interrupt_on"] = self._subagent_gates(spec["interrupt_on"], own_gates)
            stack = list(spec.get("middleware") or [])
            if children:
                stack.append(
                    self._subagent_middleware(
                        children,
                        parent_model=spec.get("model") or model,
                        parent_tools=spec["tools"],
                        backend=backend,
                        own_gates=own_gates,
                        permissions=permissions,
                    )
                )
                spec["system_prompt"] = delegating_subagent_prompt(spec.get("system_prompt"))
            spec["middleware"] = self._ensure_platform_middleware(
                ensure_planning_and_filesystem(stack, backend, permissions)
            )
            spec["system_prompt"] = self._with_memory_prompt(spec.get("system_prompt"))
            prepared.append(spec)
        if not any(
            isinstance(s, Mapping) and s.get("name") == GENERAL_PURPOSE_SUBAGENT["name"]
            for s in prepared
        ):
            prepared.insert(
                0, self._general_purpose_subagent(model, inherited, backend, permissions)
            )
        return prepared

    def _general_purpose_subagent(
        self, model: Any, tools: Sequence[Any], backend: Any, permissions: list[Any]
    ) -> dict[str, Any]:
        """deepagents' general-purpose sub-agent, declared rather than auto-added,
        so it too runs without ``ask_user`` and with the platform middleware."""
        return {
            **GENERAL_PURPOSE_SUBAGENT,
            "system_prompt": self._with_memory_prompt(GENERAL_PURPOSE_SUBAGENT["system_prompt"]),
            "model": model,
            "tools": list(tools),
            "middleware": self._ensure_platform_middleware(
                ensure_planning_and_filesystem([], backend, permissions)
            ),
        }

    def _subagent_middleware(
        self,
        children: Sequence[Any],
        *,
        parent_model: Any,
        parent_tools: Sequence[Any],
        backend: Any,
        own_gates: Mapping[str, bool] | None,
        permissions: list[Any],
    ) -> SubAgentMiddleware:
        """The ``task`` tool of a sub-agent that has sub-agents of its own."""
        return SubAgentMiddleware(
            backend=backend,
            subagents=[
                child
                if "runnable" in child
                else self._nested_subagent(
                    child,
                    parent_model=parent_model,
                    parent_tools=parent_tools,
                    backend=backend,
                    own_gates=own_gates,
                    permissions=permissions,
                )
                for child in children
            ],
        )

    def _nested_subagent(
        self,
        raw: Mapping[str, Any],
        *,
        parent_model: Any,
        parent_tools: Sequence[Any],
        backend: Any,
        own_gates: Mapping[str, bool] | None,
        permissions: list[Any],
    ) -> dict[str, Any]:
        """A fully built spec for a sub-agent at depth ≥ 2.

        ``SubAgentMiddleware`` runs a spec as given, so everything a depth-1
        sub-agent gets is added here: planning, filesystem with the write-deny
        rules, summarization, PatchToolCalls (whose marker binds the
        sub-agent's stream), its own ``task`` tool if it has sub-agents,
        refusal handling, then the platform middleware.
        """
        spec = dict(raw)
        children = spec.pop(SUBAGENTS_KEY, None) or []
        model = spec.get("model") or parent_model
        resolved_model = resolve_model(model)
        tools = self._with_memory_tools(
            _without_ask_user(spec["tools"]) if "tools" in spec else list(parent_tools)
        )
        gates = _merge_fs_interrupt_on(
            _build_interrupt_on_from_permissions(permissions, backend),
            self._subagent_gates(spec.get("interrupt_on"), own_gates),
        )
        stack: list[Any] = [
            TodoListMiddleware(),
            filesystem_middleware(backend, permissions),
            create_summarization_middleware(resolved_model, backend),
            PatchToolCallsMiddleware(),
            *(spec.get("middleware") or []),
        ]
        system_prompt = spec.get("system_prompt", "")
        if children:
            stack.append(
                self._subagent_middleware(
                    children,
                    parent_model=model,
                    parent_tools=tools,
                    backend=backend,
                    own_gates=own_gates,
                    permissions=permissions,
                )
            )
            system_prompt = delegating_subagent_prompt(system_prompt)
        system_prompt = self._with_memory_prompt(system_prompt)
        stack.append(ModelRefusalMiddleware())
        built: dict[str, Any] = {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "system_prompt": system_prompt,
            "model": resolved_model,
            "tools": tools,
            "middleware": self._ensure_platform_middleware(stack),
        }
        if gates:
            built["interrupt_on"] = gates
        return built

    @staticmethod
    def _subagent_gates(
        spec_gates: Mapping[str, bool] | None, own_gates: Mapping[str, bool] | None
    ) -> dict[str, bool]:
        """A sub-agent's approval gates: the agent's, with its own spec's on top,
        then the locked gates, so no spec can clear a gate the service mandates."""
        return resolve_interrupt_on({**(own_gates or {}), **(spec_gates or {})})

    # ---------------------------------------------------------------------
    # Lifecycle hooks
    # ---------------------------------------------------------------------
    def register_subagents(self) -> SubAgentsT:
        """Override to declare nested sub-agents."""
        return None

    @abstractmethod
    def register_agent(self) -> Any:
        """Build and return the main agent runnable.

        ``self.sub_agents``, ``self.checkpointer`` and ``self.tools`` are
        populated before this is called. Call ``self.build_deep_agent(...)``
        rather than ``create_deep_agent`` directly: it injects the workspace,
        its permission ladder, the builtins, the composed system prompt and the
        approval gates.
        """

    async def ensure_built(self) -> None:
        """Bind the checkpointer, then run the lifecycle hooks once. Idempotent.

        ``/resume`` calls it first so it can read ``self.compiled.aget_state``
        before issuing the resume command; ``astream`` calls it too.
        """
        if self.checkpointer is None:
            self.checkpointer = self._durable_checkpointer() or MemorySaver()
        if self.agent is not None:
            return
        logger.info("deep_agent_build_started", "Deep agent build started", agent_slug=self.name)
        await self._prepare_memory()
        self.sub_agents = self.register_subagents()
        self.agent = self.register_agent()
        logger.info(
            "deep_agent_build_completed",
            "Deep agent build completed",
            agent_slug=self.name,
            has_subagents=self.sub_agents is not None,
        )

    def _apply_live_tools(self, tools: Sequence[Any]) -> None:
        """Attach live MCP tools, minus any whose name a prebuilt tool owns."""
        super()._apply_live_tools(strip_reserved_names(tools, agent_slug=self.name))
