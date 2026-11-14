"""The run's in-process state and the agents-service wire helpers, as units:
event folding, delta coalescing, tool-result truncation, checkpoint capture,
interrupt accounting, generated files, SSE parsing, request shapes and the
inline-attachment budget."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

from pydantic import SecretStr

from core.settings import settings
from utils import agents
from utils.inference import InlineBudget, serialise_message_for_agent
from utils.inference_runs import (
    InferenceRunRuntime,
    append_coalesced,
    hitl_resolved_value,
    overall_hitl_decision,
    truncate_tool_result,
)


# --- runtime ---------------------------------------------------------------
def test_text_chunks_accumulate_and_coalesce_into_one_stored_event():
    runtime = InferenceRunRuntime()
    for delta in ("Hel", "lo"):
        runtime.apply_event({"type": "TEXT_MESSAGE_CHUNK", "messageId": "m", "delta": delta})
    assert runtime.content == "Hello"
    assert [e["delta"] for e in runtime.raw_events] == ["Hello"]
    assert runtime.raw_events[0]["seq"] == 2


def test_thinking_steps_are_never_coalesced():
    runtime = InferenceRunRuntime()
    runtime.apply_event({"type": "THINKING_START"})
    for step in ("a", "b"):
        runtime.apply_event({"type": "THINKING_TEXT_MESSAGE_CONTENT", "delta": step})
    runtime.apply_event({"type": "THINKING_END"})
    assert runtime.thoughts == ["a", "b"]
    assert len([e for e in runtime.raw_events if e["type"] == "THINKING_TEXT_MESSAGE_CONTENT"]) == 2
    assert runtime.thinking_duration_seconds() is not None


def test_tool_call_start_is_a_thought_and_args_coalesce_per_call():
    runtime = InferenceRunRuntime()
    runtime.apply_event({"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "search"})
    runtime.apply_event({"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"q":'})
    runtime.apply_event({"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '"x"}'})
    assert runtime.thoughts == ["[tool] search"]
    assert runtime.raw_events[-1]["delta"] == '{"q":"x"}'


def test_subagent_deltas_coalesce_one_level_down():
    log: list[dict] = []
    for delta in ("a", "b"):
        append_coalesced(
            log,
            {
                "type": "CUSTOM",
                "name": "SUBAGENT_EVENT",
                "value": {
                    "task_id": "t",
                    "event": {"type": "TEXT_MESSAGE_CHUNK", "messageId": "s", "delta": delta},
                },
            },
        )
    assert len(log) == 1 and log[0]["value"]["event"]["delta"] == "ab"


def test_checkpoint_committed_is_captured_but_never_stored():
    runtime = InferenceRunRuntime()
    applied = runtime.apply_event(
        {"type": "CUSTOM", "name": "CHECKPOINT_COMMITTED", "value": {"checkpoint_id": "ck-9"}}
    )
    assert applied is None
    assert runtime.produced_checkpoint_id == "ck-9"
    assert runtime.raw_events == []


def test_an_interrupt_seen_bare_and_wrapped_is_pending_once():
    runtime = InferenceRunRuntime()
    hitl = {"type": "CUSTOM", "name": "HITL_INTERRUPT", "value": {"interrupt": {"id": "i1"}}}
    runtime.apply_event({"type": "CUSTOM", "name": "SUBAGENT_EVENT", "value": {"event": hitl}})
    runtime.apply_event(hitl)
    assert runtime.pending_interrupt_ids == ["i1"]
    runtime.resolve_interrupt("i1")
    assert runtime.pending_interrupts == 0


def test_unrelated_custom_events_are_stored_without_pausing():
    runtime = InferenceRunRuntime()
    runtime.apply_event({"type": "CUSTOM", "name": "PLAN_SNAPSHOT", "value": {"items": []}})
    assert runtime.pending_interrupts == 0
    assert runtime.raw_events[-1]["name"] == "PLAN_SNAPSHOT"


def test_oversized_tool_results_are_cut_and_flagged(monkeypatch):
    monkeypatch.setattr(settings.inference, "tool_result_max_chars", 10)
    cut = truncate_tool_result({"type": "TOOL_CALL_RESULT", "content": "x" * 50})
    assert cut["content"] == "x" * 10 and cut["truncated"] is True
    assert truncate_tool_result({"content": "short"}) == {"content": "short"}
    image = {"content": "preview_base64" + "y" * 50}
    assert truncate_tool_result(image) is image
    runtime = InferenceRunRuntime()
    runtime.apply_event(
        {
            "type": "CUSTOM",
            "name": "SUBAGENT_EVENT",
            "value": {"event": {"type": "TOOL_CALL_RESULT", "content": "z" * 50}},
        }
    )
    assert runtime.raw_events[-1]["value"]["event"]["truncated"] is True


def test_a_presented_file_keeps_its_bytes_off_the_wire():
    runtime = InferenceRunRuntime()
    data = b"%PDF-1.7 report"
    applied = runtime.apply_event(
        {
            "type": "CUSTOM",
            "name": "PRESENT_ARTIFACT",
            "value": {
                "path": "/out/report.pdf",
                "filename": "report.pdf",
                "mime": "application/pdf",
                "title": "Report",
                "data_base64": base64.b64encode(data).decode(),
            },
        }
    )
    assert "data_base64" not in applied["value"]
    assert "data_base64" not in json.dumps(runtime.raw_events)
    stored = runtime.generated_files["/out/report.pdf"]
    assert stored["data"] == data and stored["file_name"] == "report.pdf"


def test_a_presented_file_over_the_limit_is_dropped(monkeypatch):
    monkeypatch.setattr(settings.attachments, "max_size_bytes", 4)
    runtime = InferenceRunRuntime()
    runtime.apply_event(
        {
            "type": "CUSTOM",
            "name": "PRESENT_ARTIFACT",
            "value": {"path": "/big", "data_base64": base64.b64encode(b"too big").decode()},
        }
    )
    assert runtime.generated_files == {}


def test_hitl_markers():
    answers = [{"id": "q1", "selected": ["A"]}]
    marker = hitl_resolved_value({"interrupt_id": "i", "value": {"answers": answers}}, "approve")
    assert marker["answers"] == answers
    assert "answers" not in hitl_resolved_value({"value": "text"}, "approve")
    batch = {"decisions": [{"decision": "reject"}, {"decision": "approve"}]}
    assert overall_hitl_decision(batch) == "approve"
    assert overall_hitl_decision({"decision": "reject"}) == "reject"


# --- agents-service wire ---------------------------------------------------
def test_parse_sse_handles_crlf_split_utf8_and_junk():
    payload = 'data: {"type": "TEXT_MESSAGE_CHUNK", "delta": "καλημέρα"}\r\n\r\n'.encode()
    cut = payload.index("μ".encode()) + 1  # in the middle of a two-byte character
    buffer, first = agents.parse_sse(b"", payload[:cut])
    buffer, second = agents.parse_sse(buffer, payload[cut:] + b"data: not json\n\n: comment\n\n")
    assert first == [] and buffer == b""
    assert second == [{"type": "TEXT_MESSAGE_CHUNK", "delta": "καλημέρα"}]


def test_urls_quote_the_slug(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_url", "http://agents:8003/")
    assert agents.agent_stream_url("test-agent") == "http://agents:8003/agents/test-agent/stream"
    assert agents.agent_resume_url("a/b") == "http://agents:8003/agents/a%2Fb/resume"


def test_the_service_secret_header_is_sent_only_when_configured(monkeypatch):
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr(""))
    assert agents.SERVICE_AUTH_HEADER not in agents.agents_headers()
    monkeypatch.setattr(settings.upstream, "agents_service_secret", SecretStr("s3cret"))
    headers = agents.agents_headers()
    assert headers[agents.SERVICE_AUTH_HEADER] == "s3cret"
    assert headers["Accept"] == "text/event-stream"


def test_resume_body_single_and_batched():
    config = {"run_config": {"configurable": {"thread_id": "th"}}}
    one = agents.resume_body(config, [{"interrupt_id": "i1", "decision": "approve"}])
    assert (one["thread_id"], one["interrupt_id"], "resumes" in one) == ("th", "i1", False)
    two = agents.resume_body(
        config,
        [{"interrupt_id": "i1"}, {"interrupt_id": "i2", "decision": "reject", "reason": "no"}],
    )
    assert [r["interrupt_id"] for r in two["resumes"]] == ["i1", "i2"]
    assert two["resumes"][1] == {
        "interrupt_id": "i2",
        "decision": "reject",
        "reason": "no",
        "value": None,
        "decisions": None,
    }


def _attachment(name: str, mime: str, data: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"att-{name}",
        file_name=name,
        mime_type=mime,
        size_bytes=len(data),
        content_sha256="ab" * 32,
        origin="upload",
        blob=SimpleNamespace(data=data),
    )


def _message(content: str | None, attachments: list) -> SimpleNamespace:
    return SimpleNamespace(
        id="m1",
        sender="user",
        content=content,
        attachments=attachments,
        kind=None,
        task_notice=None,
    )


def test_plain_text_serialises_to_a_string():
    out = serialise_message_for_agent(_message("Hi", []), InlineBudget())
    assert out == {"id": "m1", "role": "user", "content": "Hi", "attachments": []}


def test_files_go_inline_within_the_budget(monkeypatch):
    monkeypatch.setattr(settings.attachments, "max_total_bytes", 10)
    msg = _message(
        "See files",
        [
            _attachment("pic.png", "image/png", b"PNG1"),
            _attachment("a.csv", "text/csv", b"x,y\n"),
            _attachment("b.csv", "text/csv", b"too many bytes"),
        ],
    )
    out = serialise_message_for_agent(msg, InlineBudget())
    parts = out["content"]
    assert parts[0] == {"type": "text", "text": "See files"}
    assert (
        parts[1]["image_url"]["url"]
        == "data:image/png;base64," + base64.b64encode(b"PNG1").decode()
    )
    assert "a.csv (text/csv)" in parts[2]["text"]
    first, second = out["attachments"]
    assert base64.b64decode(first["data_base64"]) == b"x,y\n"
    assert first["sha256"] == "ab" * 32 and first["size_bytes"] == 4
    assert second["data_base64"] is None and second["omitted"] == "budget"
