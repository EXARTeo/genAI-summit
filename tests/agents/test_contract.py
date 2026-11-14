"""This service's side of ``docs/agents-contract.md``, pinned at the HTTP boundary.

What the backend relies on, checked through the real app:

* the internal-caller gate: ``X-Internal-Service-Secret`` or 403, ``/health`` open,
  and a deployed service that refuses to start without a secret;
* ``GET /agents``: the manifests a UI picks from, exactly one marked default;
* the run endpoints' HTTP errors: 404 for an unknown slug, 400 for a config
  without ``context`` (or one missing ``client_id`` / ``conversation_id``), the
  ``/resume`` 400 / 503 / 409 and the 409 body the backend recovers from;
* the SSE framing (``text/event-stream``, ``data: {json}`` frames ended by a blank
  line), ``CHECKPOINT_COMMITTED`` last, one ``RUN_ERROR`` and nothing after it;
* uploads: written to ``/conversation/input/``, ``attachments`` stripped from the
  messages, a note naming the paths in their place; task-notification rows
  passed through as their ``HumanMessage``;
* the client id is sensitive: every log line of a run carries it only as the
  keyed ``h:<16 hex>`` pseudonym.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import logging

import pytest
import route_fakes
from conftest import CLIENT_ID, run_config
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import SecretStr, ValidationError

from core.logging import clear_context
from core.logging.filters import RequestContextFilter
from core.logging.formatters import ConsoleFormatter, JsonFormatter
from core.logging.redaction import hash_identifier, sanitize_context_value
from core.security.internal_trust import INTERNAL_SECRET_HEADER
from core.settings import Settings, settings
from harness.agui.events import CHECKPOINT_COMMITTED_EVENT_TYPE
from harness.async_tasks.notification import NOTIFICATION_KWARGS, TASK_NOTIFICATION_KIND
from harness.checkpointer.store import set_checkpointer
from harness.conversation_files.inputs import StoredUpload
from utils import inference
from utils.agents import AGENT_REGISTRY

_MESSAGES = [{"id": "m1", "role": "user", "content": "hello"}]


@pytest.fixture
def saver():
    """A wired checkpointer (the lifespan's job, which these tests skip)."""
    checkpointer = MemorySaver()
    set_checkpointer(checkpointer)
    yield checkpointer
    set_checkpointer(None)


@pytest.fixture
def files_in_memory(monkeypatch, memory_file_store):
    """Uploads land in the in-memory store instead of ``agent_runtime``."""
    monkeypatch.setattr(inference, "ConversationFileStore", lambda _pool: memory_file_store)
    return memory_file_store


def _stream(client, headers, slug="fake", messages=None, config=None):
    return client.post(
        f"/agents/{slug}/stream",
        headers=headers,
        json={"messages": _MESSAGES if messages is None else messages, "config": config},
    )


def _resume(client, headers, slug="fake", **body):
    payload = {"config": run_config(), "thread_id": "t1", "decision": "approve", **body}
    return client.post(f"/agents/{slug}/resume", headers=headers, json=payload)


# ---------------------------------------------------------------------------
# The internal-caller gate
# ---------------------------------------------------------------------------
async def test_health_is_open_to_any_caller(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("presented", [None, "", "wrong-secret"])
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/agents"),
        ("POST", "/agents/assistant/stream"),
        ("POST", "/agents/assistant/resume"),
    ],
)
async def test_a_caller_without_the_secret_is_refused(client, method, path, presented):
    headers = {} if presented is None else {INTERNAL_SECRET_HEADER: presented}
    body = {"messages": _MESSAGES, "config": run_config(), "thread_id": "t1", "decision": "approve"}
    response = await client.request(method, path, headers=headers, json=body)
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


async def test_the_secret_lets_the_backend_in(client, internal_headers):
    response = await client.get("/agents", headers=internal_headers)
    assert response.status_code == 200


async def test_with_no_secret_configured_every_caller_is_accepted(client, monkeypatch):
    # Development and test only: settings refuse an empty secret anywhere else.
    monkeypatch.setattr(settings.proxy, "internal_service_secret", SecretStr(""))
    response = await client.get("/agents")
    assert response.status_code == 200


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """A process environment without the secret, and no ``.env`` to read one from."""
    monkeypatch.chdir(tmp_path)
    for name in ("INTERNAL_SERVICE_SECRET", "INTERNAL_SERVICE_SECRET_FILE", "ENV"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize("env", ["production", "staging", "prod"])
def test_a_deployed_service_refuses_to_start_without_a_secret(clean_env, env):
    clean_env.setenv("APP_ENV", env)
    with pytest.raises(ValidationError, match="INTERNAL_SERVICE_SECRET must be set"):
        Settings()


def test_a_deployed_service_starts_with_a_secret(clean_env):
    clean_env.setenv("APP_ENV", "production")
    clean_env.setenv("INTERNAL_SERVICE_SECRET", "deployed-secret")
    loaded = Settings()
    assert loaded.proxy.internal_service_secret.get_secret_value() == "deployed-secret"


def test_a_deployed_service_reads_the_secret_from_a_file(clean_env, tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("from-a-file\n", encoding="utf-8")
    clean_env.setenv("APP_ENV", "production")
    clean_env.setenv("INTERNAL_SERVICE_SECRET_FILE", str(secret_file))
    assert Settings().proxy.internal_service_secret.get_secret_value() == "from-a-file"


@pytest.mark.parametrize("env", ["development", "test", " Test "])
def test_development_and_test_may_run_without_a_secret(clean_env, env):
    clean_env.setenv("APP_ENV", env)
    assert Settings().proxy.internal_service_secret.get_secret_value() == ""


# ---------------------------------------------------------------------------
# GET /agents
# ---------------------------------------------------------------------------
async def test_the_agent_list_has_every_registered_agent_and_one_default(client, internal_headers):
    response = await client.get("/agents", headers=internal_headers)
    assert response.status_code == 200
    agents = response.json()
    assert {item["slug"] for item in agents} == set(AGENT_REGISTRY)
    for item in agents:
        assert set(item) == {
            "id",
            "slug",
            "name",
            "version",
            "type",
            "description",
            "icon",
            "default",
        }
    assert [item["slug"] for item in agents if item["default"]] == [
        settings.registry.default_agent_slug
    ]
    assert [item["name"] for item in agents] == sorted(item["name"] for item in agents)


# ---------------------------------------------------------------------------
# Run endpoints: HTTP errors before the first frame
# ---------------------------------------------------------------------------
async def test_stream_answers_404_for_an_unknown_slug(client, internal_headers):
    response = await _stream(client, internal_headers, slug="no-such-agent", config=run_config())
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown agent."}


async def test_resume_answers_404_for_an_unknown_slug(client, internal_headers, saver):
    response = await _resume(client, internal_headers, slug="no-such-agent")
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown agent."}


@pytest.mark.parametrize("config", [{}, {"run_config": {"configurable": {"thread_id": "t1"}}}])
async def test_stream_without_a_context_is_a_400(client, internal_headers, config):
    response = await _stream(client, internal_headers, slug="assistant", config=config)
    assert response.status_code == 400
    assert response.json() == {"detail": "config.context is required."}


@pytest.mark.parametrize("missing", ["client_id", "conversation_id"])
async def test_stream_with_a_context_missing_an_id_is_a_400(client, internal_headers, missing):
    config = run_config()
    del config["context"][missing]
    response = await _stream(client, internal_headers, slug="assistant", config=config)
    assert response.status_code == 400
    assert response.json() == {"detail": "Failed to initialise the requested agent."}


async def test_stream_without_messages_or_config_is_a_422(client, internal_headers):
    response = await client.post(
        "/agents/assistant/stream", headers=internal_headers, json={"messages": _MESSAGES}
    )
    assert response.status_code == 422


async def test_resume_without_a_thread_is_a_400(client, internal_headers, saver):
    # Neither the body nor the config's run_config names the paused thread.
    response = await _resume(
        client, internal_headers, slug="assistant", thread_id="", config=run_config(thread_id="")
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "thread_id is required to resume a paused run."}


async def test_resume_falls_back_to_the_config_thread(client, internal_headers, monkeypatch, saver):
    class _Paused(route_fakes.FakeAgent):
        interrupts = (route_fakes.interrupt("a" * 32),)

    built = route_fakes.install(monkeypatch, _Paused)
    response = await _resume(
        client, internal_headers, thread_id="", config=run_config(thread_id="from-config")
    )
    assert response.status_code == 200
    assert built[0].run_config["configurable"]["thread_id"] == "from-config"


async def test_resume_without_a_checkpointer_is_a_503(client, internal_headers, monkeypatch):
    route_fakes.install(monkeypatch)
    response = await _resume(client, internal_headers)
    assert response.status_code == 503


async def test_resume_with_nothing_pending_is_a_409_naming_the_stale_id(
    client, internal_headers, monkeypatch, saver
):
    route_fakes.install(monkeypatch)
    response = await _resume(client, internal_headers, interrupt_id="int-1")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["stale_interrupt_ids"] == ["int-1"]
    assert detail["pending_interrupt_ids"] == []
    assert isinstance(detail["message"], str)


async def test_resume_naming_a_stale_interrupt_lists_stale_and_pending(
    client, internal_headers, monkeypatch, saver
):
    pending = "a" * 32

    class _Paused(route_fakes.FakeAgent):
        interrupts = (route_fakes.interrupt(pending),)

    built = route_fakes.install(monkeypatch, _Paused)
    response = await _resume(client, internal_headers, interrupt_id="d" * 32)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["stale_interrupt_ids"] == ["d" * 32]
    assert detail["pending_interrupt_ids"] == [pending]
    # Nothing was applied: the run never streamed.
    assert built[0].commands == []


# ---------------------------------------------------------------------------
# The SSE stream
# ---------------------------------------------------------------------------
async def test_a_run_streams_sse_frames_and_ends_with_the_checkpoint(
    client, internal_headers, monkeypatch, files_in_memory
):
    route_fakes.install(monkeypatch)
    response = await _stream(client, internal_headers, config=run_config(thread_id="branch-7"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = route_fakes.sse_events(response.text)
    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "TEXT_MESSAGE_CONTENT",
        "RUN_FINISHED",
        "CUSTOM",
    ]
    committed = events[-1]
    assert committed["name"] == CHECKPOINT_COMMITTED_EVENT_TYPE == "CHECKPOINT_COMMITTED"
    assert committed["value"] == {"thread_id": "branch-7", "checkpoint_id": "cp-1"}


async def test_resume_is_framed_like_stream(client, internal_headers, monkeypatch, saver):
    class _Paused(route_fakes.FakeAgent):
        interrupts = (route_fakes.interrupt("a" * 32),)

    route_fakes.install(monkeypatch, _Paused)
    response = await _resume(client, internal_headers, interrupt_id="a" * 32)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = route_fakes.sse_events(response.text)
    assert events[-1]["name"] == "CHECKPOINT_COMMITTED"
    assert events[-1]["value"]["thread_id"] == "t1"


async def test_a_failed_run_ends_with_one_run_error_and_nothing_after(
    client, internal_headers, monkeypatch, files_in_memory
):
    route_fakes.install(monkeypatch, route_fakes.FailingAgent)
    response = await _stream(client, internal_headers, config=run_config())
    assert response.status_code == 200
    events = route_fakes.sse_events(response.text)
    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    # A public message only: the exception's text never reaches the backend.
    assert "hunter2" not in response.text
    assert events[-1]["message"]


class _ScriptedModel(GenericFakeChatModel):
    """A chat model the deep agent can bind tools to; it only ever answers text."""

    def bind_tools(self, tools, **kwargs):
        return self


async def test_a_real_agent_run_commits_the_checkpoint_it_wrote(
    client, internal_headers, monkeypatch, saver, files_in_memory
):
    # The shipped assistant end to end, with a scripted model and an in-memory saver.
    settings.async_tasks.enabled = False
    model = _ScriptedModel(messages=iter([AIMessage(content="Hi there.")]))
    deep_models = importlib.import_module("deepagents._models")
    monkeypatch.setattr(deep_models, "init_chat_model", lambda *_a, **_k: model)
    response = await _stream(
        client, internal_headers, slug="assistant", config=run_config(thread_id="real-1")
    )
    assert response.status_code == 200
    events = route_fakes.sse_events(response.text)
    text = "".join(e.get("delta", "") for e in events if e["type"].startswith("TEXT_MESSAGE"))
    assert text == "Hi there."
    committed = events[-1]
    assert committed["name"] == "CHECKPOINT_COMMITTED"
    head = await saver.aget_tuple({"configurable": {"thread_id": "real-1"}})
    assert committed["value"] == {"thread_id": "real-1", "checkpoint_id": head.checkpoint["id"]}


# ---------------------------------------------------------------------------
# Uploads and notification rows
# ---------------------------------------------------------------------------
def test_agent_messages_strip_attachments_and_name_the_upload_paths():
    messages = [
        {"id": "m0", "role": "assistant", "content": "earlier"},
        {
            "id": "m1",
            "role": "user",
            "content": "summarise this",
            "attachments": [{"name": "report.pdf", "data_base64": "AAAA"}],
            "extra": "dropped",
        },
    ]
    uploads = [
        StoredUpload("m1", "report.pdf", "/conversation/input/report.pdf", "application/pdf")
    ]
    cleaned = inference.agent_messages(messages, uploads)
    assert cleaned[0] == {"id": "m0", "role": "assistant", "content": "earlier"}
    assert set(cleaned[1]) == {"id", "role", "content"}
    assert cleaned[1]["content"] == (
        "summarise this\n\nUploaded files, readable in /conversation/input/:\n"
        "- /conversation/input/report.pdf (application/pdf)"
    )


def test_agent_messages_append_the_note_as_a_part_to_multipart_content():
    parts = [{"type": "text", "text": "what is in these?"}]
    uploads = [
        StoredUpload("m1", "a.csv", "/conversation/input/a.csv", "text/csv"),
        StoredUpload("m1", "b.txt", "/conversation/input/b.txt", "text/plain"),
    ]
    cleaned = inference.agent_messages([{"id": "m1", "role": "user", "content": parts}], uploads)
    content = cleaned[0]["content"]
    assert content[0] == parts[0]
    assert content[1]["type"] == "text"
    assert "- /conversation/input/a.csv (text/csv)" in content[1]["text"]
    assert "- /conversation/input/b.txt (text/plain)" in content[1]["text"]
    # The caller's message is not written into.
    assert parts == [{"type": "text", "text": "what is in these?"}]


def test_agent_messages_turn_a_notification_row_into_its_human_message():
    kwargs = {key: {"task_id": "t-1"} for key in NOTIFICATION_KWARGS}
    row = {
        "id": "n1",
        "role": "user",
        "kind": TASK_NOTIFICATION_KIND,
        "content": [{"type": "text", "text": "<task-notification>...</task-notification>"}],
        "additional_kwargs": {**kwargs, "server_only": "dropped"},
    }
    (message,) = inference.agent_messages([row], [])
    assert isinstance(message, HumanMessage)
    assert message.content == row["content"]
    assert message.additional_kwargs == kwargs


async def test_stream_writes_uploads_and_hands_the_agent_the_note_instead(
    client, internal_headers, monkeypatch, files_in_memory
):
    built = route_fakes.install(monkeypatch)
    data = b"col\n1\n"
    messages = [
        {
            "id": "m1",
            "role": "user",
            "content": "chart this",
            "attachments": [
                {
                    "id": "att-1",
                    "name": "data.csv",
                    "mime_type": "text/csv",
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "origin": "upload",
                    "data_base64": base64.b64encode(data).decode(),
                }
            ],
        }
    ]
    response = await _stream(client, internal_headers, messages=messages, config=run_config())
    assert response.status_code == 200
    stored = await files_in_memory.read(CLIENT_ID, "c1", "/conversation/input/data.csv")
    assert stored == data
    (handed,) = built[0].payloads[0]["messages"]
    assert "attachments" not in handed
    assert handed["content"].startswith("chart this\n\n")
    assert "/conversation/input/data.csv (text/csv)" in handed["content"]


# ---------------------------------------------------------------------------
# The client id in logs
# ---------------------------------------------------------------------------
class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.addFilter(RequestContextFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_no_log_line_of_a_run_carries_the_raw_client_id(
    client, internal_headers, monkeypatch, files_in_memory
):
    route_fakes.install(monkeypatch, route_fakes.FailingAgent)
    capture = _Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        response = await _stream(client, internal_headers, config=run_config())
        assert response.status_code == 200
    finally:
        root.removeHandler(capture)
        clear_context()
    assert capture.records, "the run logged nothing"
    pseudonym = hash_identifier(CLIENT_ID)
    lines = [
        formatter.format(record)
        for record in capture.records
        for formatter in (JsonFormatter(), ConsoleFormatter())
    ]
    assert all(CLIENT_ID not in line for line in lines)
    run_lines = [json.loads(line) for line in lines if line.startswith("{")]
    assert any(line["user_id"] == pseudonym for line in run_lines)


def test_the_client_id_pseudonym_is_the_keyed_hmac(monkeypatch):
    monkeypatch.setattr(settings.logging, "redaction_secret", SecretStr("shared-key"))
    digest = hmac.new(b"shared-key", CLIENT_ID.encode(), hashlib.sha256).hexdigest()
    expected = f"h:{digest[:16]}"
    assert hash_identifier(CLIENT_ID) == expected
    for field in ("user_id", "client_id", "client_ip"):
        assert sanitize_context_value(field, CLIENT_ID) == expected


def test_an_already_hashed_id_passes_through_and_a_forged_one_is_rehashed():
    hashed = hash_identifier(CLIENT_ID)
    assert hash_identifier(hashed) == hashed
    forged = "h:not-a-real-hash"
    assert hash_identifier(forged) != forged
    assert hash_identifier(forged).startswith("h:")
