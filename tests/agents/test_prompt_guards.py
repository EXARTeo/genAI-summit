"""The run's input messages on their way to the agent.

The service no longer rebuilds LangChain messages itself: the contract's
``Message`` dicts go to LangGraph as they are, and only a persisted task
notice is turned back into its ``HumanMessage``. Pinned here: a multimodal
user message reaches the model with every part intact, an upload adds a note
naming where its files now are, and attachment payloads never ride along.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import convert_to_messages

from harness.async_tasks.notification import normalize_payload_messages
from harness.conversation_files.inputs import StoredUpload
from utils.inference import agent_messages

IMAGE_PART = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,abcd", "detail": "low"},
}


def test_a_plain_message_passes_through_untouched():
    message = {"id": "m1", "role": "user", "content": "Hello"}
    assert normalize_payload_messages([message]) == [message]


def test_multimodal_content_is_preserved_to_the_model():
    message = {
        "id": "m1",
        "role": "user",
        "content": [{"type": "text", "text": "Look at this"}, IMAGE_PART],
    }
    (out,) = agent_messages([message], [])
    # LangGraph's own conversion is what the agent's graph applies to the dict.
    (converted,) = convert_to_messages([out])

    assert isinstance(converted, HumanMessage)
    assert converted.content == [{"type": "text", "text": "Look at this"}, IMAGE_PART]


def test_attachment_payloads_are_dropped_from_the_agent_input():
    message = {
        "id": "m1",
        "role": "user",
        "content": "Read it",
        "attachments": [{"id": "a1", "name": "report.pdf", "data_base64": "QUJD"}],
    }
    assert agent_messages([message], []) == [{"id": "m1", "role": "user", "content": "Read it"}]


def test_an_upload_adds_a_note_naming_its_input_path():
    upload = StoredUpload(
        message_id="m1",
        name="report.pdf",
        path="/conversation/input/report.pdf",
        mime_type="application/pdf",
    )
    text_message = {"id": "m1", "role": "user", "content": "Read it"}
    parts_message = {"id": "m1", "role": "user", "content": [{"type": "text", "text": "Read it"}]}

    (text_out,) = agent_messages([text_message], [upload])
    (parts_out,) = agent_messages([parts_message], [upload])

    note = (
        "Uploaded files, readable in /conversation/input/:\n"
        "- /conversation/input/report.pdf (application/pdf)"
    )
    assert text_out["content"] == f"Read it\n\n{note}"
    assert parts_out["content"][-1] == {"type": "text", "text": note}
