"""Deeply nested sub-agents on real Gemini, replayed through the AG-UI normalizer.

Each ``fixtures/gemini/nested_*.json`` is a real run of the throwaway test agent
``fixtures/gemini/agents/nested-demo`` (agent > researcher > checker >
source-verifier, plus a leaf summarizer) on ``ChatGoogleGenerativeAI``,
recorded by ``gemini_record.py`` as the raw chunks ``BaseAgent.astream``
handed the normalizer, one list per stream: a HITL pause and its ``/resume``
are two streams of one run, and an async run is one stream per run of each
background task plus the orchestrator's wake-up. Replaying needs no network.

Checked on every recording, at every depth: the contract of
``test_agui_gemini`` (text and thinking balanced, each tool card's lifecycle
once and in order, args = the settled args, streamed text = the settled text,
usage once per settled model call), and nesting: every event is keyed to its
own `task` call (the ground truth is the ``tasks`` stream: which call each
namespace runs), siblings never mix, each sub-agent is announced inside its
caller's stream before its first event and completes there once after its
last, nothing is left orphaned, and a pause and its resume keep that order.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from test_agui_gemini import _decode

from harness.agui.normalizer import (
    AGUIStreamNormalizer,
    is_gemini,
    release_namespace_bindings,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gemini"

SYNC = [
    "nested_sync3_35-flash-lite",
    "nested_sync3_35-flash",
    "nested_siblings_35-flash",
    "nested_hitl_35-flash-lite",
    "nested_hitl_35-flash",
]
ASYNC = ["nested_async_35-flash-lite", "nested_async_hitl_35-flash-lite"]
ALL = SYNC + ASYNC

TEXT_DELTAS = {"TEXT_MESSAGE_CHUNK", "TEXT_MESSAGE_CONTENT"}
SILENT_TOOLS = {"task", "start_async_task", "update_async_task", "write_todos"}


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------
def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class Emitted:
    """One AG-UI event and where it came from."""

    def __init__(self, stream: int, chunk: int, event: dict[str, Any]) -> None:
        self.stream, self.chunk, self.raw = stream, chunk, event
        self.task_id: str | None = None  # the innermost envelope's `task` call
        self.namespace: tuple[str, ...] = ()
        inner = event
        while inner["type"] == "CUSTOM" and inner["name"] == "SUBAGENT_EVENT":
            self.task_id = inner["value"]["task_id"]
            self.namespace = tuple(inner["value"]["namespace"])
            inner = inner["value"]["event"]
        self.event = inner

    @property
    def kind(self) -> str:
        e = self.event
        return f"C:{e['name']}" if e["type"] == "CUSTOM" else e["type"]

    @property
    def value(self) -> dict[str, Any]:
        return self.event.get("value") or {}


class Replay:
    """A recorded run replayed stream by stream, as the service streams it:
    one fresh normalizer per stream on the run's id (its per-run memory kept
    across a pause), a resume seeded from the orchestrator's state."""

    def __init__(self, name: str) -> None:
        self.data = _fixture(name)
        self.streams: list[list[Any]] = []
        self.events: list[Emitted] = []
        self.by_stream: list[list[Emitted]] = []
        for index, stream in enumerate(self.data["streams"]):
            run_id = stream.get("thread_id") or self.data["thread_id"]
            if not stream["resume"]:
                release_namespace_bindings(run_id)
            normalizer = AGUIStreamNormalizer(run_id)
            if stream["seed_messages"]:
                normalizer.seed_pending_tasks(_decode(stream["seed_messages"]))
            chunks = [_decode(chunk) for chunk in stream["chunks"]]
            self.streams.append(chunks)
            emitted: list[Emitted] = []
            for position, chunk in enumerate(chunks):
                for frame in normalizer.handle_chunk(chunk):
                    text = frame.decode("utf-8")
                    assert text.startswith("data: ") and text.endswith("\n\n")
                    emitted.append(Emitted(index, position, json.loads(text[len("data: ") :])))
            self.by_stream.append(emitted)
            self.events.extend(emitted)
        # Ground truth: the `task` call each sub-agent namespace runs (the
        # "tasks" stream names the call a tools node task runs, exactly).
        self.truth: dict[tuple[str, ...], str] = {}
        for chunks in self.streams:
            for namespace, mode, payload in chunks:
                if mode != "tasks" or payload.get("name") != "tools":
                    continue
                for call in payload.get("input") or []:
                    if isinstance(call, dict) and call.get("name") == "task":
                        child = (*namespace, f"tools:{payload['id']}")
                        assert self.truth.setdefault(child, call["id"]) == call["id"]

    def actor(self, namespace: tuple) -> str | None:
        """The `task` call a namespace runs (None: the stream's own agent)."""
        return self.truth[tuple(namespace)] if namespace else None

    def settled(self, stream: int | None = None) -> list[tuple[str | None, Any]]:
        """Every settled model message, as (actor, message), in order."""
        out = []
        for index, chunks in enumerate(self.streams):
            if stream is not None and index != stream:
                continue
            for namespace, mode, payload in chunks:
                if mode == "updates" and "model" in payload and payload["model"]:
                    for msg in payload["model"].get("messages") or []:
                        out.append((self.actor(namespace), msg))
        return out

    def settled_calls(self) -> dict[str, tuple[str | None, dict[str, Any]]]:
        """Every settled tool call by id: (the actor that made it, the call)."""
        return {
            tc["id"]: (actor, tc) for actor, msg in self.settled() for tc in msg.tool_calls or []
        }

    def paused(self, stream: int) -> bool:
        return any(e.kind == "C:HITL_INTERRUPT" for e in self.by_stream[stream])


@pytest.fixture(scope="module")
def replays() -> dict[str, Replay]:
    return {name: Replay(name) for name in ALL}


# --------------------------------------------------------------------------
# The contract of test_agui_gemini, per actor at every depth
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ALL)
def test_recorded_on_gemini_and_nested(replays, name):
    replay = replays[name]
    ai = [m for _a, m in replay.settled()]
    assert ai and all(is_gemini(m) for m in ai)
    if name in SYNC:
        assert max(len(ns) for ns in replay.truth) >= 2  # a sub-agent delegated in turn


@pytest.mark.parametrize("name", ALL)
def test_text_messages_are_balanced_per_actor(replays, name):
    for stream in replays[name].by_stream:
        open_by_actor: dict[str | None, bool] = defaultdict(bool)
        for e in stream:
            if e.kind == "TEXT_MESSAGE_START":
                assert not open_by_actor[e.task_id]
                open_by_actor[e.task_id] = True
            elif e.kind == "TEXT_MESSAGE_END":
                assert open_by_actor[e.task_id]
                open_by_actor[e.task_id] = False
            elif e.kind in TEXT_DELTAS:
                assert open_by_actor[e.task_id]
                assert isinstance(e.event["delta"], str) and e.event["delta"]
                assert "signature" not in e.event["delta"]
        assert not any(open_by_actor.values())


@pytest.mark.parametrize("name", ALL)
def test_thinking_is_balanced_per_actor_and_closed_at_each_stream_end(replays, name):
    for stream in replays[name].by_stream:
        open_by_actor: dict[str | None, bool] = defaultdict(bool)
        for e in stream:
            if e.kind == "THINKING_START":
                assert not open_by_actor[e.task_id]
                open_by_actor[e.task_id] = True
            elif e.kind == "THINKING_END":
                assert open_by_actor[e.task_id]
                open_by_actor[e.task_id] = False
            elif e.kind == "THINKING_TEXT_MESSAGE_START":
                assert open_by_actor[e.task_id], "a thought outside a thinking phase"
        assert not any(open_by_actor.values())


@pytest.mark.parametrize("name", ALL)
def test_every_tool_card_has_its_lifecycle_once_in_order(replays, name):
    """Per stream: start, args, result, end, once each. A stream that pauses
    leaves only the gated call open, and its resume opens it again (the HITL
    re-emission, which may carry edited args) and closes it."""
    replay = replays[name]
    closed: set[str] = set()
    for index, stream in enumerate(replay.by_stream):
        by_call: dict[str, list[str]] = defaultdict(list)
        for e in stream:
            if e.kind.startswith("TOOL_CALL_"):
                by_call[e.event["toolCallId"]].append(e.kind)
        left_open = []
        for call_id, seq in by_call.items():
            if seq == ["TOOL_CALL_START", "TOOL_CALL_ARGS"]:
                left_open.append(call_id)
                continue
            assert seq == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_RESULT", "TOOL_CALL_END"]
            assert call_id not in closed, "a tool card closed twice in one run"
            closed.add(call_id)
        assert len(left_open) == (1 if replay.paused(index) else 0), (index, left_open)
    # Nothing orphaned: every settled tool call that ran got its card closed.
    for call_id, (_actor, call) in replay.settled_calls().items():
        if call["name"] not in SILENT_TOOLS:
            assert call_id in closed, (call["name"], call_id)


@pytest.mark.parametrize("name", ALL)
def test_tool_cards_carry_the_settled_args_and_belong_to_their_caller(replays, name):
    replay = replays[name]
    calls = replay.settled_calls()
    for e in replay.events:
        if e.kind == "TOOL_CALL_START":
            actor, call = calls[e.event["toolCallId"]]
            assert e.task_id == actor
            assert e.event["toolCallName"] == call["name"]
        elif e.kind == "TOOL_CALL_ARGS":
            actor, call = calls[e.event["toolCallId"]]
            assert e.task_id == actor
            assert json.loads(e.event["delta"]) == {"name": call["name"], "args": call["args"]}
        elif e.kind in ("TOOL_CALL_RESULT", "TOOL_CALL_END"):
            assert e.task_id == calls[e.event["toolCallId"]][0]


@pytest.mark.parametrize("name", ALL)
def test_streamed_text_is_each_actors_settled_text(replays, name):
    replay = replays[name]
    for index in range(len(replay.streams)):
        streamed: dict[str | None, str] = defaultdict(str)
        for e in replay.by_stream[index]:
            if e.kind in TEXT_DELTAS:
                streamed[e.task_id] += e.event["delta"]
        settled: dict[str | None, str] = defaultdict(str)
        for actor, msg in replay.settled(index):
            content = msg.content if isinstance(msg.content, list) else [{"text": msg.content}]
            settled[actor] += "".join(
                b["text"]
                for b in content
                if isinstance(b, dict) and b.get("type", "text") == "text"
            )
        assert dict(streamed) == {a: t for a, t in settled.items() if t}


@pytest.mark.parametrize("name", ALL)
def test_usage_once_per_settled_model_call_of_each_actor(replays, name):
    replay = replays[name]
    for index in range(len(replay.streams)):
        usage: dict[str | None, list[str]] = defaultdict(list)
        for e in replay.by_stream[index]:
            if e.kind == "C:TOKEN_USAGE":
                usage[e.task_id].append(e.value["message_id"])
        settled: dict[str | None, list[str]] = defaultdict(list)
        for actor, msg in replay.settled(index):
            settled[actor].append(msg.id)
            assert msg.usage_metadata["input_tokens"] > 0
        assert dict(usage) == dict(settled)


# --------------------------------------------------------------------------
# Nesting
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ALL)
def test_every_event_is_keyed_to_its_own_task_call(replays, name):
    """The envelope is the namespace that produced the event, and its key the
    `task` call that namespace runs: never a parent's, a sibling's or a bare
    namespace id."""
    replay = replays[name]
    for e in replay.events:
        chunk_ns = tuple(replay.streams[e.stream][e.chunk][0])
        mode = replay.streams[e.stream][e.chunk][1]
        if mode == "tasks":  # a sub-agent's start marker, in the child it starts
            assert e.kind == "C:BEFORE_AGENT_EVENT"
            assert e.namespace[:-1] == chunk_ns
        else:
            assert e.namespace == chunk_ns
        assert e.task_id == replay.actor(e.namespace)


@pytest.mark.parametrize("name", SYNC)
def test_each_subagent_is_announced_and_completed_once_inside_its_callers_stream(replays, name):
    replay = replays[name]
    caller = {call: replay.actor(ns[:-1]) for ns, call in replay.truth.items()}
    child_ns = {call: ns for ns, call in replay.truth.items()}
    announced = [e for e in replay.events if e.kind == "C:TASK_SUBAGENT"]
    completed = [e for e in replay.events if e.kind == "C:SUBAGENT_COMPLETED"]
    assert sorted(e.value["task_id"] for e in announced) == sorted(caller)
    assert sorted(e.value["task_id"] for e in completed) == sorted(caller)
    position = {id(e): i for i, e in enumerate(replay.events)}
    for e in announced:
        call = e.value["task_id"]
        assert e.task_id == caller[call]
        first = next(x for x in replay.events if x.task_id == call)
        assert position[id(e)] < position[id(first)]
    for e in completed:
        call = e.value["task_id"]
        assert e.task_id == caller[call]
        assert e.value["status"] == "completed"
        assert tuple(e.value["namespace"]) == child_ns[call]
        last = max(position[id(x)] for x in replay.events if x.task_id == call)
        assert last < position[id(e)]


@pytest.mark.parametrize("name", ALL)
def test_nothing_is_orphaned(replays, name):
    """Every envelope is an announced sub-agent; every announced one started
    and finished; the run ends on the orchestrator's own reply."""
    replay = replays[name]
    announced = {e.value["task_id"] for e in replay.events if e.kind == "C:TASK_SUBAGENT"}
    assert {e.task_id for e in replay.events if e.task_id} == announced
    started = {e.task_id for e in replay.events if e.kind == "C:BEFORE_AGENT_EVENT"}
    assert started == announced
    last = replay.by_stream[-1]
    assert last[-1].kind == "C:TOKEN_USAGE" and last[-1].task_id is None
    assert any(e.kind == "TEXT_MESSAGE_END" and e.task_id is None for e in last)


def test_three_levels_deep_nest_in_order(replays):
    for name in ("nested_sync3_35-flash-lite", "nested_sync3_35-flash"):
        replay = replays[name]
        chain = sorted(replay.truth.items(), key=lambda item: len(item[0]))
        assert [len(ns) for ns, _ in chain] == [1, 2, 3]
        researcher, checker, verifier = (call for _ns, call in chain)
        tasks = [
            (e.task_id, e.value["task_id"], e.value["subagent_type"])
            for e in replay.events
            if e.kind == "C:TASK_SUBAGENT"
        ]
        assert tasks == [
            (None, researcher, "researcher"),
            (researcher, checker, "checker"),
            (checker, verifier, "source-verifier"),
        ]
        done = [
            (e.task_id, e.value["task_id"])
            for e in replay.events
            if e.kind == "C:SUBAGENT_COMPLETED"
        ]
        assert done == [(checker, verifier), (researcher, checker), (None, researcher)]
        ls = [e for e in replay.events if e.kind == "TOOL_CALL_START"]
        assert [(e.task_id, e.event["toolCallName"]) for e in ls] == [(verifier, "ls")]


def test_parallel_siblings_never_mix():
    replay = Replay("nested_siblings_35-flash")
    top = [e for e in replay.events if e.kind == "C:TASK_SUBAGENT" and e.task_id is None]
    types = {e.value["task_id"]: e.value["subagent_type"] for e in top}
    assert sorted(types.values()) == ["researcher", "summarizer"]
    # Both were called in one model turn, so both are announced before either speaks.
    first_sub = next(i for i, e in enumerate(replay.events) if e.task_id is not None)
    assert all(replay.events.index(e) < first_sub for e in top)
    summarizer = next(c for c, t in types.items() if t == "summarizer")
    researcher = next(c for c, t in types.items() if t == "researcher")
    # The summarizer delegates nothing and its text is its own.
    assert not [e for e in replay.events if e.task_id == summarizer and e.kind == "C:TASK_SUBAGENT"]
    below_researcher = {call for ns, call in replay.truth.items() if len(ns) > 1}
    assert len(below_researcher) == 2
    assert all(replay.truth[ns[:1]] == researcher for ns in replay.truth if len(ns) > 1)
    for e in replay.events:
        if e.task_id == summarizer:
            assert len(e.namespace) == 1


@pytest.mark.parametrize("name", ["nested_hitl_35-flash-lite", "nested_hitl_35-flash"])
def test_an_approval_inside_a_depth_two_subagent_pauses_and_resumes_in_order(replays, name):
    replay = replays[name]
    assert len(replay.by_stream) == 2
    paused, resumed = replay.by_stream
    chain = sorted(replay.truth.items(), key=lambda item: len(item[0]))
    (_r_ns, researcher), (_c_ns, checker) = chain
    # The pause: the gated write_file card stays open in the checker's card, every
    # level's thinking is closed, and one interrupt is raised from the inside out.
    gated = [e for e in paused if e.kind == "TOOL_CALL_START"]
    assert [(e.task_id, e.event["toolCallName"]) for e in gated] == [(checker, "write_file")]
    interrupts = [e for e in paused if e.kind == "C:HITL_INTERRUPT"]
    assert [e.task_id for e in interrupts] == [checker, researcher, None]
    assert len({e.value["interrupt"]["id"] for e in interrupts}) == 1
    assert paused[-1] is interrupts[-1]
    request = interrupts[0].value["interrupt"]["value"]["action_requests"][0]
    assert request["name"] == "write_file"
    assert not [e for e in paused if e.kind == "C:SUBAGENT_COMPLETED"]
    # The resume: the same call's card closes in the checker's card, then each
    # level completes inside its caller, innermost first, then the reply.
    call_id = gated[0].event["toolCallId"]
    card = [(e.task_id, e.kind) for e in resumed if e.event.get("toolCallId") == call_id]
    assert card == [
        (checker, "TOOL_CALL_START"),
        (checker, "TOOL_CALL_ARGS"),
        (checker, "TOOL_CALL_RESULT"),
        (checker, "TOOL_CALL_END"),
    ]
    result = next(
        e for e in resumed if e.kind == "TOOL_CALL_RESULT" and e.event["toolCallId"] == call_id
    )
    assert "verdict.md" in result.event["content"]
    done = [(e.task_id, e.value["task_id"]) for e in resumed if e.kind == "C:SUBAGENT_COMPLETED"]
    assert done == [(researcher, checker), (None, researcher)]
    assert not [e for e in resumed if e.kind == "C:TASK_SUBAGENT"]  # announced once, before


# --------------------------------------------------------------------------
# Async: every task is its own stream
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ASYNC)
def test_async_tree_each_task_launches_its_child_inside_its_own_stream(replays, name):
    replay = replays[name]
    tasks = {t["task_id"]: t for t in replay.data["tasks"]}
    assert sorted(t["depth"] for t in tasks.values())[:2] == [1, 2]
    assert all(t["status"] == "success" for t in tasks.values())
    streams = replay.data["streams"]
    launched_in: dict[str | None, list[str]] = defaultdict(list)
    names_in: dict[str | None, list[str]] = defaultdict(list)
    for index, stream in enumerate(streams):
        for e in replay.by_stream[index]:
            # No blocking sub-agent anywhere: the stream's own agent only.
            assert e.task_id is None
            if e.kind == "C:TASK_LAUNCHED":
                launched_in[stream["task_id"]].append(e.value["task_id"])
                names_in[stream["task_id"]].append(e.value["name"])
    expected: dict[str | None, list[str]] = defaultdict(list)
    for task in tasks.values():
        expected[task["parent_task_id"]].append(task["task_id"])
    assert dict(launched_in) == dict(expected)
    assert {k: [tasks[c]["name"] for c in v] for k, v in expected.items()} == dict(names_in)
    # Each task's stream is keyed to its own run: its text never carries another's id.
    for index, stream in enumerate(streams):
        ids = {e.event["messageId"] for e in replay.by_stream[index] if "messageId" in e.event}
        assert ids <= {stream["thread_id"]}
    # A child runs only after its parent launched it, and the orchestrator is
    # woken with the depth-1 result last and answers.
    first_run = {}
    for index, stream in enumerate(streams):
        first_run.setdefault(stream["task_id"], index)
    for task in tasks.values():
        assert first_run[task["parent_task_id"]] < first_run[task["task_id"]]
    assert streams[-1]["task_id"] is None and first_run[None] == 0


def test_async_approval_inside_a_depth_two_task_pauses_that_task_and_resumes_in_order(replays):
    replay = replays["nested_async_hitl_35-flash-lite"]
    streams = replay.data["streams"]
    checker = next(t["task_id"] for t in replay.data["tasks"] if t["depth"] == 2)
    researcher = next(t["task_id"] for t in replay.data["tasks"] if t["depth"] == 1)
    order = [(s["task_id"], s["resume"]) for s in streams]
    assert order == [
        (None, False),  # the orchestrator launches the researcher
        (researcher, False),  # which launches the checker and waits for it
        (checker, False),  # the checker pauses on write_file
        (checker, True),  # the approved resume writes and settles it
        (researcher, False),  # woken with the checker's result
        (None, False),  # the orchestrator woken with the researcher's
    ]
    paused, resumed = replay.by_stream[2], replay.by_stream[3]
    gated = [e for e in paused if e.kind == "TOOL_CALL_START"]
    assert [e.event["toolCallName"] for e in gated] == ["write_file"]
    assert paused[-1].kind == "C:HITL_INTERRUPT" and paused[-1].task_id is None
    assert [e.kind for e in paused].count("C:HITL_INTERRUPT") == 1
    call_id = gated[0].event["toolCallId"]
    assert [e.kind for e in resumed if e.event.get("toolCallId") == call_id] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_RESULT",
        "TOOL_CALL_END",
    ]
    # Nothing of the paused task leaks into another task's stream.
    for index, stream in enumerate(streams):
        if stream["task_id"] != checker:
            assert not [e for e in replay.by_stream[index] if e.event.get("toolCallId") == call_id]
