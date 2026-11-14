"""``present_artifact``: the tool parks what it read, the normalizer turns it into a card.

The tool is the only way a file reaches the user. It is held to
``/conversation/output/``, refuses what it cannot read, and parks the file's
bytes in the run's ``PresentedFiles`` (base64, unless over the per-file or
per-run cap). The stream normalizer then emits exactly one ``PRESENT_ARTIFACT``
for the orchestrator's successful result, carrying those bytes; a sub-agent's
call or a refused call never becomes a card.
"""

from __future__ import annotations

import base64
import json

from langchain_core.messages import AIMessage, ToolMessage

from core.settings import settings
from harness.agui.normalizer import AGUIStreamNormalizer
from harness.tools.present_artifact import (
    PRESENT_ARTIFACT_TOOL_NAME,
    PresentedFiles,
    build_present_artifact_tool,
)

REPORT_PATH = "/conversation/output/report.md"
REPORT_BYTES = b"# Report\n\nAll good.\n"


def _call(call_id: str = "call-1", **args) -> dict:
    """A ToolCall dict, so LangChain fills the injected tool_call_id."""
    return {"type": "tool_call", "id": call_id, "name": PRESENT_ARTIFACT_TOOL_NAME, "args": args}


def _tool(conversation_files, presented: PresentedFiles):
    return build_present_artifact_tool(files=conversation_files, presented=presented)


async def _present(conversation_files, presented, call_id="call-1", **args) -> str:
    result = await _tool(conversation_files, presented).ainvoke(_call(call_id, **args))
    return str(result.content)


def _events(frames: list[bytes]) -> list[dict]:
    return [
        json.loads(line[5:])
        for frame in frames
        for line in frame.decode().splitlines()
        if line.startswith("data:")
    ]


def _presentation_turn(call_id: str, path: str) -> AIMessage:
    return AIMessage(
        content="",
        id=f"m-{call_id}",
        tool_calls=[
            {
                "id": call_id,
                "name": PRESENT_ARTIFACT_TOOL_NAME,
                "args": {"path": path, "title": "Report"},
            }
        ],
    )


def _result(call_id: str, content: str) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=PRESENT_ARTIFACT_TOOL_NAME)


# --- the tool -------------------------------------------------------------------


async def test_a_presented_file_is_parked_with_its_bytes(conversation_files):
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()

    reply = await _present(
        conversation_files, presented, path=REPORT_PATH, title=" Q3 Report ", summary="Numbers."
    )

    assert "document card" in reply
    parked = presented.pop("call-1")
    assert parked is not None
    assert parked.path == REPORT_PATH
    assert parked.filename == "report.md"
    assert parked.title == "Q3 Report"
    assert parked.summary == "Numbers."
    assert parked.mime == "text/markdown"
    assert parked.size == len(REPORT_BYTES)
    assert base64.b64decode(parked.data_base64) == REPORT_BYTES
    # The model reads a confirmation, never the document.
    assert base64.b64encode(REPORT_BYTES).decode() not in reply


async def test_an_empty_summary_is_parked_as_none(conversation_files):
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()
    await _present(conversation_files, presented, path=REPORT_PATH, title="R", summary="  ")
    assert presented.pop("call-1").summary is None


async def test_a_path_outside_output_is_refused(conversation_files):
    # An upload exists, but only output/ holds deliverables.
    await conversation_files.create("/conversation/input/upload.md", REPORT_BYTES)
    presented = PresentedFiles()

    for path in ("/conversation/input/upload.md", "/conversation/output/../input/upload.md"):
        reply = await _present(conversation_files, presented, path=path, title="Upload")
        assert reply.startswith("Could not present:")
    assert presented.pop("call-1") is None


async def test_a_missing_file_is_refused(conversation_files):
    presented = PresentedFiles()
    reply = await _present(conversation_files, presented, path=REPORT_PATH, title="Report")
    assert reply.startswith("Could not present: no file at")
    assert presented.pop("call-1") is None


async def test_an_empty_title_is_refused(conversation_files):
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()
    reply = await _present(conversation_files, presented, path=REPORT_PATH, title="   ")
    assert reply == "Could not present: 'title' is required."
    assert presented.pop("call-1") is None


async def test_a_file_over_the_size_cap_is_parked_without_bytes(conversation_files):
    settings.filesystem.output_max_file_bytes = len(REPORT_BYTES) - 1
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()

    await _present(conversation_files, presented, path=REPORT_PATH, title="Report")

    parked = presented.pop("call-1")
    assert parked is not None and parked.size == len(REPORT_BYTES)
    assert parked.data_base64 is None


async def test_files_past_the_count_cap_are_parked_without_bytes(conversation_files):
    settings.filesystem.output_max_files = 2
    presented = PresentedFiles()
    for index in range(3):
        path = f"/conversation/output/f{index}.txt"
        await conversation_files.create(path, b"x")
        await _present(conversation_files, presented, call_id=f"call-{index}", path=path, title="F")

    carried = [presented.pop(f"call-{index}").data_base64 for index in range(3)]
    assert carried[:2] == ["eA==", "eA=="]
    assert carried[2] is None


def test_admits_bytes_follows_both_caps():
    settings.filesystem.output_max_file_bytes = 10
    settings.filesystem.output_max_files = 5
    presented = PresentedFiles()
    assert presented.admits_bytes(10)
    assert not presented.admits_bytes(11)


# --- the normalizer ------------------------------------------------------------


async def test_a_successful_result_becomes_one_card_with_the_bytes(conversation_files):
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()
    norm = AGUIStreamNormalizer(thread_id="run-pa", presented=presented)

    on_call = _events(
        norm.handle_chunk(
            ("updates", {"model": {"messages": [_presentation_turn("call-1", REPORT_PATH)]}})
        )
    )
    reply = await _present(conversation_files, presented, path=REPORT_PATH, title="Report")
    on_result = _events(
        norm.handle_chunk(("updates", {"tools": {"messages": [_result("call-1", reply)]}}))
    )
    # A replayed result (messages and updates both carry it) is no second card.
    replay = _events(norm.handle_chunk(("messages", (_result("call-1", reply), {}))))

    assert on_call == []  # the card waits for the result, and is never a tool card
    assert [e.get("name") for e in on_result] == ["PRESENT_ARTIFACT"]
    assert replay == []
    value = on_result[0]["value"]
    assert value == {
        "artifact_id": "call-1",
        "path": REPORT_PATH,
        "filename": "report.md",
        "title": "Report",
        "mime": "text/markdown",
        "size": len(REPORT_BYTES),
        "data_base64": base64.b64encode(REPORT_BYTES).decode(),
        "status": "ready",
    }


async def test_a_refused_call_has_no_card(conversation_files):
    presented = PresentedFiles()
    norm = AGUIStreamNormalizer(thread_id="run-pa", presented=presented)

    norm.handle_chunk(
        ("updates", {"model": {"messages": [_presentation_turn("call-1", REPORT_PATH)]}})
    )
    reply = await _present(conversation_files, presented, path=REPORT_PATH, title="Report")
    events = _events(
        norm.handle_chunk(("updates", {"tools": {"messages": [_result("call-1", reply)]}}))
    )

    assert reply.startswith("Could not present:")
    assert events == []


async def test_an_errored_result_has_no_card_even_with_parked_bytes(conversation_files):
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()
    norm = AGUIStreamNormalizer(thread_id="run-pa", presented=presented)

    norm.handle_chunk(
        ("updates", {"model": {"messages": [_presentation_turn("call-1", REPORT_PATH)]}})
    )
    await _present(conversation_files, presented, path=REPORT_PATH, title="Report")
    failed = ToolMessage(
        content="boom", tool_call_id="call-1", name=PRESENT_ARTIFACT_TOOL_NAME, status="error"
    )
    events = _events(norm.handle_chunk(("updates", {"tools": {"messages": [failed]}})))

    assert events == []


async def test_a_sub_agents_call_has_no_card(conversation_files):
    await conversation_files.create(REPORT_PATH, REPORT_BYTES)
    presented = PresentedFiles()
    norm = AGUIStreamNormalizer(thread_id="run-pa", presented=presented)
    ns = ("tools:sub-1",)

    events = _events(
        norm.handle_chunk(
            (ns, "updates", {"model": {"messages": [_presentation_turn("call-s", REPORT_PATH)]}})
        )
    )
    reply = await _present(
        conversation_files, presented, call_id="call-s", path=REPORT_PATH, title="Report"
    )
    events += _events(
        norm.handle_chunk((ns, "updates", {"tools": {"messages": [_result("call-s", reply)]}}))
    )

    # A sub-agent's file is scratch until the orchestrator presents it.
    names = [e.get("name") for e in events]
    inner = [e["value"]["event"].get("name") for e in events if e.get("name") == "SUBAGENT_EVENT"]
    assert "PRESENT_ARTIFACT" not in names
    assert "PRESENT_ARTIFACT" not in inner
