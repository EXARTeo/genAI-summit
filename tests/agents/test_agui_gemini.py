"""Gemini streams -> AG-UI: recorded real runs replayed through the normalizer.

Each fixture in ``fixtures/gemini/`` is one real run of the ``mnamon`` chat agent
on ``ChatGoogleGenerativeAI`` (``langchain-google-genai``), recorded as the raw
``(namespace, mode, payload)`` chunks ``BaseAgent.astream`` handed the
normalizer (thought signatures redacted, unused metadata dropped). Replaying
them needs no network and must give the same AG-UI contract the OpenAI
streams give: thinking before the reply, one text message per model call,
every tool card opened, given its args, its result and its end, sub-agent
events inside ``SUBAGENT_EVENT``, the thinking closed before a HITL pause,
usage per model call. ``before_fix_frames`` in each fixture is what the
service emitted when it was recorded (kept for the record, not asserted).

Gemini specifics covered: content as a list of parts (``text`` / ``thinking``),
a thought summary sent as several titled sections on one content index (each
its own step), the empty text part carrying the thought signature, tool calls
arriving whole (one per chunk, parallel ones on indexes 0 and 1), cumulative
usage split across chunks, Greek text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.load import load
from langgraph.types import Interrupt, Overwrite

from core.settings import settings
from harness.agui.normalizer import AGUIStreamNormalizer, is_gemini, thought_sections
from harness.models.reasoning_summary import is_reasoning_model, reasoning_kwargs

FIXTURES = Path(__file__).parent / "fixtures" / "gemini"

TEXT = ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CHUNK", "TEXT_MESSAGE_END"]
THOUGHT = [
    "THINKING_TEXT_MESSAGE_START",
    "THINKING_TEXT_MESSAGE_CONTENT",
    "THINKING_TEXT_MESSAGE_END",
]
TOOL_OPEN = ["TOOL_CALL_START", "TOOL_CALL_ARGS"]
TOOL_CLOSE = ["TOOL_CALL_RESULT", "TOOL_CALL_END"]
USAGE = "C:TOKEN_USAGE"


def _text(chunks: int) -> list[str]:
    return [TEXT[0], *[TEXT[1]] * chunks, TEXT[2]]


def _thoughts(count: int) -> list[str]:
    return THOUGHT * count


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------
def _decode(obj: Any) -> Any:
    """A fixture's JSON back into the objects the stream carried."""
    if isinstance(obj, list):
        return [_decode(item) for item in obj]
    if not isinstance(obj, dict):
        return obj
    if "__lc__" in obj:
        return load(obj["__lc__"], allowed_objects="messages")
    if "__tuple__" in obj:
        return tuple(_decode(item) for item in obj["__tuple__"])
    marker = obj.get("__interrupt__")
    if isinstance(marker, dict) and "value" in marker:
        return Interrupt(value=_decode(marker["value"]), id=marker["id"])
    if "__overwrite__" in obj:
        return Overwrite(_decode(obj["__overwrite__"]))
    return {key: _decode(value) for key, value in obj.items()}


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _chunks(name: str, modes: set[str] | None = None) -> list[Any]:
    chunks = [_decode(chunk) for chunk in _fixture(name)["chunks"]]
    return [chunk for chunk in chunks if modes is None or chunk[1] in modes]


def _replay(name: str, modes: set[str] | None = None) -> list[dict[str, Any]]:
    """The AG-UI events a fresh normalizer emits for the recorded run."""
    normalizer = AGUIStreamNormalizer(_fixture(name)["thread_id"])
    events: list[dict[str, Any]] = []
    for chunk in _chunks(name, modes):
        for frame in normalizer.handle_chunk(chunk):
            text = frame.decode("utf-8")
            assert text.startswith("data: ") and text.endswith("\n\n")
            events.append(json.loads(text[len("data: ") :]))
    return events


def _name(event: dict[str, Any]) -> str:
    if event["type"] == "CUSTOM":
        if event["name"] == "SUBAGENT_EVENT":
            return f"SUB[{_name(event['value']['event'])}]"
        return f"C:{event['name']}"
    return event["type"]


def _names(events: list[dict[str, Any]]) -> list[str]:
    return [_name(event) for event in events]


def _inner(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every event, a sub-agent's unwrapped."""
    return [
        event["value"]["event"]
        if event["type"] == "CUSTOM" and event["name"] == "SUBAGENT_EVENT"
        else event
        for event in events
    ]


def _settled_ai(name: str, namespace: tuple = ()) -> list[Any]:
    """The settled model messages of one actor, in order."""
    out = []
    for chunk_ns, mode, payload in _chunks(name, {"updates"}):
        if mode == "updates" and tuple(chunk_ns) == namespace and "model" in payload:
            out.extend(payload["model"]["messages"])
    return out


# --------------------------------------------------------------------------
# Contract checks shared by every scenario
# --------------------------------------------------------------------------
ALL = [
    "a_plain_text_flash_lite",
    "a_plain_text_thinking",
    "b_one_tool",
    "c_parallel_tools",
    "d_subagent_async",
    "d_subagent_sync",
    "e_hitl_interrupt",
    "f_long_greek",
]


@pytest.mark.parametrize("name", ALL)
def test_recorded_chunks_are_gemini(name):
    ai = [m for _ns, mode, payload in _chunks(name, {"messages"}) for m in [payload[0]]]
    assert ai and all(is_gemini(m) for m in ai if m.type == "AIMessageChunk" and m.content)


@pytest.mark.parametrize("name", ALL)
def test_no_part_list_signature_or_empty_delta_reaches_the_ui(name):
    for event in _inner(_replay(name)):
        delta = event.get("delta")
        if event["type"] in ("TEXT_MESSAGE_CHUNK", "THINKING_TEXT_MESSAGE_CONTENT"):
            assert isinstance(delta, str) and delta
            assert not delta.lstrip().startswith("[{")
            assert "signature" not in delta and "<thought-signature>" not in delta
    raw = json.dumps(_replay(name), ensure_ascii=False)
    assert "<thought-signature>" not in raw and "'type': 'text'" not in raw


@pytest.mark.parametrize("name", ALL)
def test_one_message_id_per_run_and_text_messages_balanced(name):
    events = _inner(_replay(name))
    ids = {e["messageId"] for e in events if e["type"].startswith("TEXT_MESSAGE")}
    assert ids <= {_fixture(name)["thread_id"]}
    depth = 0
    for event in events:
        if event["type"] == "TEXT_MESSAGE_START":
            assert depth == 0
            depth += 1
        elif event["type"] == "TEXT_MESSAGE_END":
            assert depth == 1
            depth -= 1
        elif event["type"] == "TEXT_MESSAGE_CHUNK":
            assert depth == 1


@pytest.mark.parametrize("name", ALL)
def test_every_tool_card_has_its_lifecycle_once_in_order(name):
    events = _inner(_replay(name))
    interrupted = any(_name(e) == "C:HITL_INTERRUPT" for e in events)
    by_call: dict[str, list[str]] = {}
    for event in events:
        if event["type"].startswith("TOOL_CALL_"):
            by_call.setdefault(event["toolCallId"], []).append(event["type"])
    open_calls = [c for c, seq in by_call.items() if seq == ["TOOL_CALL_START", "TOOL_CALL_ARGS"]]
    for call_id, seq in by_call.items():
        if call_id in open_calls:
            continue
        assert seq == [*TOOL_OPEN, *TOOL_CLOSE], (call_id, seq)
    # Only the call the run paused on is left open.
    assert len(open_calls) == (1 if interrupted else 0)


@pytest.mark.parametrize("name", ALL)
def test_tool_args_are_the_settled_calls_args(name):
    settled = {
        tc["id"]: tc
        for _ns, mode, payload in _chunks(name, {"updates"})
        for update in payload.values()
        if isinstance(update, dict)
        for msg in update.get("messages") or []
        if getattr(msg, "type", None) == "ai"
        for tc in msg.tool_calls
    }
    for event in _inner(_replay(name)):
        if event["type"] == "TOOL_CALL_ARGS":
            call = settled[event["toolCallId"]]
            assert json.loads(event["delta"]) == {"name": call["name"], "args": call["args"]}


@pytest.mark.parametrize("name", ALL)
def test_thinking_phases_are_balanced(name):
    """THINKING_START/END pair up per actor; a run never ends inside one."""
    events = _replay(name)
    open_by_actor: dict[str | None, bool] = {}
    for event in events:
        actor = event["value"]["task_id"] if _name(event).startswith("SUB[") else None
        kind = _inner([event])[0]["type"]
        if kind == "THINKING_START":
            assert not open_by_actor.get(actor)
            open_by_actor[actor] = True
        elif kind == "THINKING_END":
            assert open_by_actor.get(actor)
            open_by_actor[actor] = False
        elif kind == "THINKING_TEXT_MESSAGE_START":
            assert open_by_actor.get(actor), "a thought outside a thinking phase"
    assert not any(open_by_actor.values())


@pytest.mark.parametrize("name", ALL)
def test_usage_once_per_settled_model_call(name):
    settled = _settled_ai(name)
    usage = [e for e in _replay(name) if _name(e) == USAGE]
    assert [e["value"]["message_id"] for e in usage] == [m.id for m in settled]
    for event, msg in zip(usage, settled, strict=True):
        assert event["value"]["input_tokens"] == msg.usage_metadata["input_tokens"] > 0
        assert event["value"]["output_tokens"] == msg.usage_metadata["output_tokens"] > 0


@pytest.mark.parametrize("name", ALL)
def test_streamed_text_is_the_settled_text_exactly(name):
    """No text lost, repeated or rendered from the part list (Greek included)."""
    events = _replay(name)
    streamed = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CHUNK")
    settled = "".join(
        b["text"]
        for m in _settled_ai(name)
        for b in (m.content if isinstance(m.content, list) else [{"text": m.content}])
        if isinstance(b, dict) and b.get("type", "text") == "text"
    )
    assert streamed == settled


# --------------------------------------------------------------------------
# The scenarios, exact
# --------------------------------------------------------------------------
def test_a_plain_text_without_thoughts():
    """gemini-3.5-flash-lite returns no thought parts: text and usage only."""
    events = _replay("a_plain_text_flash_lite")
    assert _names(events) == [*_text(3), USAGE]


def test_a_plain_text_with_thinking():
    events = _replay("a_plain_text_thinking")
    assert _names(events) == ["THINKING_START", *_thoughts(1), "THINKING_END", *_text(3), USAGE]
    thought = next(e for e in events if e["type"] == "THINKING_TEXT_MESSAGE_CONTENT")
    assert thought["delta"].startswith("**Defining the EU AI Act**")


def test_b_one_tool_call():
    events = _replay("b_one_tool")
    assert _names(events) == [USAGE, *TOOL_OPEN, *TOOL_CLOSE, *_text(3), USAGE]
    start = events[1]
    assert start["toolCallName"] == "list_systems"
    result = events[3]
    assert result["toolCallId"] == start["toolCallId"]
    assert "SYS-001" in result["content"]


def test_c_parallel_tool_calls_open_both_then_close_both():
    events = _replay("c_parallel_tools")
    assert _names(events) == [
        "THINKING_START",
        *_thoughts(1),
        USAGE,
        *TOOL_OPEN,
        *TOOL_OPEN,
        *TOOL_CLOSE,
        *TOOL_CLOSE,
        "THINKING_END",
        *_text(3),
        USAGE,
    ]
    starts = [e for e in events if e["type"] == "TOOL_CALL_START"]
    results = [e for e in events if e["type"] == "TOOL_CALL_RESULT"]
    assert [e["toolCallName"] for e in starts] == ["list_systems", "list_audits"]
    assert [e["toolCallId"] for e in results] == [e["toolCallId"] for e in starts]
    assert len({e["toolCallId"] for e in starts}) == 2


def test_d_async_subagent_is_a_launched_task():
    """With ASYNC_SUBAGENTS_ENABLED (the default) the sub-agent runs as a task."""
    events = _replay("d_subagent_async")
    assert _names(events) == [USAGE, "C:TASK_LAUNCHED", *_text(3), USAGE]
    launched = events[1]["value"]
    assert launched["name"] == "regulation-researcher"
    assert "action" not in launched  # a start keeps the three-field shape
    assert launched["task_id"] == "12b46bed-af50-41f6-b9ba-002729a05b83"


def test_d_sync_subagent_events_are_wrapped_in_its_card():
    events = _replay("d_subagent_sync")
    names = _names(events)
    assert names[:13] == [
        "THINKING_START",
        *_thoughts(1),
        "THINKING_END",
        *_text(3),
        USAGE,
        "C:TASK_SUBAGENT",
        "SUB[C:BEFORE_AGENT_EVENT]",
    ]
    assert names[-4:] == [
        "SUB[TOOL_CALL_ARGS]",
        "SUB[THINKING_END]",
        "SUB[C:HITL_INTERRUPT]",
        "C:HITL_INTERRUPT",
    ]
    task = events[names.index("C:TASK_SUBAGENT")]["value"]
    assert task["subagent_type"] == "regulation-researcher"
    # Everything between the card and the orchestrator's interrupt is the sub-agent's.
    middle = events[names.index("C:TASK_SUBAGENT") + 1 : -1]
    assert middle and all(_name(e).startswith("SUB[") for e in middle)
    assert {e["value"]["task_id"] for e in middle} == {task["task_id"]}
    sub_tools = [e for e in _inner(middle) if e["type"] == "TOOL_CALL_START"]
    assert len(sub_tools) == 20
    assert sub_tools[-1]["toolCallName"] == "execute"  # the gated call it paused on
    sub_thoughts = [e for e in _inner(middle) if e["type"] == "THINKING_TEXT_MESSAGE_CONTENT"]
    assert len(sub_thoughts) == 7


def test_e_hitl_pause_closes_thinking_and_sends_the_interrupt_last():
    events = _replay("e_hitl_interrupt")
    assert _names(events) == [
        "THINKING_START",
        *_thoughts(2),  # two titled sections of one model call: two steps
        USAGE,
        *TOOL_OPEN,
        *TOOL_CLOSE,
        USAGE,
        *TOOL_OPEN,
        *TOOL_CLOSE,
        *_thoughts(1),
        USAGE,
        *TOOL_OPEN,
        *TOOL_CLOSE,
        USAGE,
        *TOOL_OPEN,
        "THINKING_END",
        "C:HITL_INTERRUPT",
    ]
    gated = [e for e in events if e["type"] == "TOOL_CALL_START"][-1]
    assert gated["toolCallName"] == "propose_system_note"
    interrupt = events[-1]["value"]["interrupt"]
    assert interrupt["id"]
    assert interrupt["value"]["action_requests"][0]["name"] == "propose_system_note"


def test_f_long_greek_answer_and_ten_thought_steps():
    events = _replay("f_long_greek")
    assert _names(events) == [
        "THINKING_START",
        *_thoughts(10),
        "THINKING_END",
        *_text(32),
        USAGE,
    ]
    thoughts = [e["delta"] for e in events if e["type"] == "THINKING_TEXT_MESSAGE_CONTENT"]
    assert all(t.startswith("**") for t in thoughts)
    assert thoughts[0].startswith("**Analyzing Greek Obligations**")
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CHUNK")
    assert "Κανονισμ" in text and "�" not in text


def test_updates_only_replay_gives_the_same_thoughts_and_text():
    """Without the ``messages`` stream the settled message carries the merged
    thought: it splits into the same sections, and the text comes whole."""
    full = _replay("f_long_greek")
    settled = _replay("f_long_greek", modes={"updates", "tasks"})
    assert _names(settled) == ["THINKING_START", *_thoughts(10), "THINKING_END"] + [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        USAGE,
    ]

    def thoughts(events):
        return [e["delta"] for e in events if e["type"] == "THINKING_TEXT_MESSAGE_CONTENT"]

    assert thoughts(settled) == thoughts(full)
    whole = next(e["delta"] for e in settled if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert whole == "".join(e["delta"] for e in full if e["type"] == "TEXT_MESSAGE_CHUNK")


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------
def test_thought_sections_split_on_title_lines_only():
    text = "**One**\n\nfirst **bold** word\n\n**Two**\nsecond\n"
    assert thought_sections(text) == ["**One**\n\nfirst **bold** word", "**Two**\nsecond"]
    assert thought_sections("no title at all") == ["no title at all"]
    assert thought_sections("  \n") == []


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("google_genai:gemini-3.5-flash", True),
        ("google_genai:gemini-3.5-flash-lite", True),
        ("google_genai:gemini-2.5-pro", True),
        ("google_genai:gemini-2.0-flash", False),  # no thinking: never asked
        ("google_genai:gemini-1.5-pro", False),
    ],
)
def test_which_gemini_models_are_asked_for_thoughts(spec, expected):
    assert is_reasoning_model(spec) is expected


def test_gemini_is_asked_for_thoughts_and_the_configured_thinking_level(monkeypatch):
    spec = "google_genai:gemini-3.5-flash"
    monkeypatch.setattr(settings.gemini, "thinking_level", "")
    assert reasoning_kwargs(spec, "auto") == {"include_thoughts": True}
    monkeypatch.setattr(settings.gemini, "thinking_level", "low")
    assert reasoning_kwargs(spec, "auto") == {"include_thoughts": True, "thinking_level": "low"}
    assert reasoning_kwargs("openai:gpt-5", "auto") == {"reasoning": {"summary": "auto"}}
