from typing import Any, Literal

from pydantic import BaseModel

# Custom event names/constants for AG-UI
HITL_INTERRUPT_EVENT_TYPE = "HITL_INTERRUPT"
PLAN_SNAPSHOT_EVENT_TYPE = "PLAN_SNAPSHOT"
TASK_SUBAGENT_EVENT_TYPE = "TASK_SUBAGENT"
SUBAGENT_EVENT_TYPE = "SUBAGENT_EVENT"
SUBAGENT_COMPLETED_EVENT_TYPE = "SUBAGENT_COMPLETED"
BEFORE_AGENT_EVENT_TYPE = "BEFORE_AGENT_EVENT"
TOKEN_USAGE_EVENT_TYPE = "TOKEN_USAGE"  # noqa: S105 - an event name
CHECKPOINT_COMMITTED_EVENT_TYPE = "CHECKPOINT_COMMITTED"
PRESENT_ARTIFACT_EVENT_TYPE = "PRESENT_ARTIFACT"
RENDER_CHART_EVENT_TYPE = "RENDER_CHART"
CONTEXT_COMPACTION_EVENT_TYPE = "CONTEXT_COMPACTION"
# Async sub-agents, inside a run's own stream.
TASK_LAUNCHED_EVENT_TYPE = "TASK_LAUNCHED"
TASK_SETTLED_INLINE_EVENT_TYPE = "TASK_SETTLED_INLINE"
#: A follow-up instruction a background task received (its own event stream only).
TASK_INPUT_EVENT_TYPE = "TASK_INPUT"


# ------------------------------------------------------------------
# HITL Interrupt Event
# ------------------------------------------------------------------
class HITLInterruptEvent(BaseModel):
    """Human-in-the-loop interrupt payload streamed to AG-UI."""

    thread_id: str
    interrupt: Any
    metadata: dict[str, Any] | None = None


# ------------------------------------------------------------------
# Planning Snapshot Event
# ------------------------------------------------------------------
class PlanItem(BaseModel):
    """Single planning step in a snapshot."""

    content: str
    status: Literal["pending", "in_progress", "completed"]
    metadata: dict[str, Any] | None = None


class PlanSnapshot(BaseModel):
    """Immutable snapshot of the current plan state."""

    items: list[PlanItem]
    updated_at: int | None = None
    metadata: dict[str, Any] | None = None


# ------------------------------------------------------------------
# Task -> Sub-agent assignment Event
# ------------------------------------------------------------------
class TaskSubAgentEvent(BaseModel):
    """Describes a task delegated to a sub-agent."""

    task_id: str
    subagent_type: str
    description: str


# ------------------------------------------------------------------
# Sub-agent envelope Event
# ------------------------------------------------------------------
class SubAgentEvent(BaseModel):
    """
    Wraps any normalized AG-UI event emitted by a sub-agent namespace.
    """

    task_id: str
    namespace: list[str]
    event: dict[str, Any]


# ------------------------------------------------------------------
# Sub-agent completed Event
# ------------------------------------------------------------------
class SubAgentCompletedEvent(BaseModel):
    """A delegated sub-agent returned: the orchestrator got its ``task`` result.

    Emitted once per ``task`` tool call, when its ToolMessage arrives, so the UI
    can mark that sub-agent's card done (or failed) while the run goes on — the
    result text itself is never forwarded (the orchestrator restates it).

    ``task_id`` is the ``task`` tool_call_id (the id TASK_SUBAGENT used);
    ``namespace`` is the sub-agent's LangGraph namespace path when it was bound
    to that call, so a UI that keyed the sub-agent's events by namespace can
    resolve it either way. ``started_at``/``ended_at`` are epoch ms; started_at
    is the moment the sub-agent's namespace was first seen (absent when that
    happened on an earlier stream the service no longer remembers).
    """

    task_id: str
    status: Literal["completed", "error"]
    namespace: list[str] | None = None
    started_at: int | None = None
    ended_at: int | None = None


# ------------------------------------------------------------------
# Async sub-agent task events
# ------------------------------------------------------------------
class TaskLaunchedEvent(BaseModel):
    """This run started a background task: ``start_async_task`` returned its id.

    The UI folds it into the "Started task" reference block, linked to the
    task's node in the conversation's task tree. It carries no status: the
    task outlives this run, and its life arrives on the conversation channel.

    ``name`` is the ``subagent_type`` the model asked for and ``description``
    the task it was given — both read off the launching tool call's args.
    ``action`` is ``"update"`` for an ``update_async_task`` that reached an
    existing task (a clarification, or continuing a stopped one): the same
    live card, said as "Updated task" — the name then comes from the tree.
    """

    task_id: str
    name: str
    description: str
    action: Literal["start", "update"] = "start"


class TaskSettledInlineEvent(BaseModel):
    """A task's result was pulled into this busy run instead of waking it.

    deepagents' pull path adds a notification message to the running agent's
    state before its next model call; this event is how the run's timeline
    shows that moment ("researcher finished"). Only settled outcomes are
    announced — a task that paused for approval is not finished.
    """

    task_id: str
    name: str
    status: Literal["success", "error", "cancelled"]


# ------------------------------------------------------------------
# Before-agent event
# ------------------------------------------------------------------
class BeforeAgentEvent(BaseModel):
    """
    Captures the delegated instruction observed in
    PatchToolCallsMiddleware.before_agent.
    """

    message: str
    metadata: dict[str, Any] | None = None


# ------------------------------------------------------------------
# Token usage event
# ------------------------------------------------------------------
class TokenUsageEvent(BaseModel):
    """Per-AI-message token usage, pulled from ``AIMessage.usage_metadata``.

    Emitted once per settled AI message (main agent or sub-agent), relayed
    untouched by the backend; ``message_id`` lets a consumer dedupe.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    input_token_details: dict[str, Any] | None = None
    output_token_details: dict[str, Any] | None = None
    message_id: str | None = None
    # "compaction" for the summary call of an automatic compaction — booked
    # under its own usage scope, never the conversation's context reading.
    purpose: Literal["compaction"] | None = None


# ------------------------------------------------------------------
# Context compaction event
# ------------------------------------------------------------------
class ContextCompactionEvent(BaseModel):
    """The main agent compacted its context in the middle of a run.

    ``started`` arrives with the summary call's first tokens, ``done`` with the
    reply of the model call the compaction ran in front of: ``tokens_after`` is
    that call's provider-reported prompt, ``freed`` the summarizer's estimate of
    what it took out, ``tokens_before`` their sum.
    """

    phase: Literal["started", "done"]
    trigger: Literal["auto"] = "auto"
    tokens_before: int | None = None
    tokens_after: int | None = None
    freed: int | None = None
    summarized_messages: int | None = None
    kept_messages: int | None = None


# ------------------------------------------------------------------
# Checkpoint-committed event
# ------------------------------------------------------------------
class CheckpointCommittedEvent(BaseModel):
    """Terminal marker carrying the durable checkpoint head this run produced.

    Emitted once at the end of a /stream or /resume leg so the backend can
    persist ``(thread_id, checkpoint_id)`` on the assistant message: the next
    turn resumes from this head and edit/retry fork from it. Never relayed to
    browsers.
    """

    thread_id: str
    checkpoint_id: str | None = None


# ------------------------------------------------------------------
# Present-artifact event
# ------------------------------------------------------------------
class PresentArtifactEvent(BaseModel):
    """A user-facing deliverable the agent has explicitly designated.

    Emitted when the orchestrator calls the ``present_artifact`` tool to hand a
    finished document to the user — the ONE intentional act that promotes a file
    out of the agent's scratch/helper docs into something the user sees. Sent
    on the tool's successful result. ``data_base64`` carries the file's bytes
    as presented (absent past ``OUTPUT_MAX_FILE_BYTES`` or ``OUTPUT_MAX_FILES``);
    the backend stores them as a generated attachment of the answer and strips
    them from the relayed event.
    """

    artifact_id: str
    path: str
    filename: str
    title: str
    summary: str | None = None
    mime: str | None = None
    size: int | None = None
    data_base64: str | None = None
    status: Literal["ready"] = "ready"


# ------------------------------------------------------------------
# Render-chart event
# ------------------------------------------------------------------
class ChartSeries(BaseModel):
    """One plotted measure: the row field it reads and its legend label.

    ``type`` and ``axis`` are only populated for a ``composed`` chart, where
    each series draws itself and may be measured against a second y-axis. Every
    other chart type omits them — the top-level ``type`` decides the shape.
    """

    key: str
    label: str
    type: Literal["bar", "line", "area"] | None = None
    axis: Literal["left", "right"] | None = None


class RenderChartEvent(BaseModel):
    """A chart the agent chose to draw, folded into the run's timeline.

    Emitted when the orchestrator calls the ``render_chart`` tool. Unlike
    ``PresentArtifactEvent`` this carries the payload itself, not a pointer:
    a chart has no bytes on disk, so the event IS the chart. It lands in
    ``raw_events``, which means the UI's timeline reducer rebuilds the chart
    block at the log position it fired — surviving reload and reconnection
    without a table or a blob behind it.

    ``data`` rows are projected down to exactly ``x_key`` + the series keys
    before emission (see ``harness.tools.charts.normalize_chart_payload``), so
    nothing the model put in a row beyond what the chart plots reaches the wire.
    Colors are absent by design — the UI assigns them from the viewer's theme.
    """

    chart_id: str
    type: Literal["bar", "line", "area", "pie", "radar", "radial", "scatter", "composed"]
    title: str
    subtitle: str | None = None
    # A category label for every type except ``scatter``, where it names a
    # numeric field — the one place the two data shapes differ.
    x_key: str
    series: list[ChartSeries]
    data: list[dict[str, Any]]
    # Presentation modifiers, already reconciled against ``type`` by
    # ``normalize_chart_payload`` — an inapplicable flag arrives as False.
    stacked: bool = False
    horizontal: bool = False
    show_values: bool = False
