"""Langfuse tracing: opt-in, fail-open, nested under the backend, masked before anything leaves.

The contract (``harness/observability/langfuse.py`` and ``docs/contracts/agents-contract.md``
section ``trace``):

- off unless ``LANGFUSE_BASE_URL`` and both keys are set, and off means every
  run config is handed back untouched;
- on, each run gets its own handler plus the trace's session, tags and the
  client's ``h:<16 hex>`` pseudonym, never the raw id;
- a run the backend traces (``config.trace``) nests under the backend's
  observation in the backend's trace, takes its session and user, and keeps the
  backend's trace name; malformed ids are never used;
- the mask removes API keys, tokens, e-mail addresses, URL credentials and
  credential-named fields, and fails closed on unknown shapes;
- a client that cannot start, or a flush that fails, never takes the service down.
"""

from __future__ import annotations

import types

import pytest
from conftest import CLIENT_ID, run_config
from pydantic import BaseModel, SecretStr

from core.logging.redaction import hash_identifier
from core.settings import LangfuseSettings, settings
from harness.abstractions.base_agent import BaseAgent
from harness.observability import langfuse as lf

_TRACE_ID = "0123456789abcdef0123456789abcdef"
_SPAN_ID = "0123456789abcdef"


class _FakeHandler:
    """Stands in for the SDK's ``CallbackHandler``: records how it was built."""

    def __init__(self, *, public_key=None, trace_context=None):
        self.public_key = public_key
        self.trace_context = trace_context


@pytest.fixture
def tracing_on(monkeypatch):
    """Tracing as if a client were live, with a stand-in handler class."""
    _configure()
    monkeypatch.setattr(lf, "_client", object())
    monkeypatch.setattr(lf, "CallbackHandler", _FakeHandler)
    return lf


def _configure(*, url="http://langfuse-web:3000", public="pk-lf-test", secret="sk-lf-test"):  # noqa: S107 - test keys
    settings.langfuse.base_url = url
    settings.langfuse.public_key = SecretStr(public)
    settings.langfuse.secret_key = SecretStr(secret)


def _backend_trace(**overrides):
    return {
        "trace_id": _TRACE_ID,
        "parent_observation_id": _SPAN_ID,
        "traceparent": f"00-{_TRACE_ID}-{_SPAN_ID}-01",
        "user_id": hash_identifier(CLIENT_ID),
        "session_id": "conv-from-backend",
        **overrides,
    }


# ---------------------------------------------------------------------------
# Settings: on only with the URL and both keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "public", "secret", "enabled"),
    [
        ("", "", "", False),
        ("http://langfuse-web:3000", "", "", False),
        ("http://langfuse-web:3000", "pk-lf-x", "", False),
        ("", "pk-lf-x", "sk-lf-x", False),
        ("   ", "pk-lf-x", "sk-lf-x", False),
        ("http://langfuse-web:3000", "pk-lf-x", "sk-lf-x", True),
    ],
)
def test_enabled_needs_url_and_both_keys(url, public, secret, enabled):
    _configure(url=url, public=public, secret=secret)
    assert settings.langfuse.enabled is enabled


def test_keys_are_read_from_files(tmp_path, monkeypatch):
    public, secret = tmp_path / "pk", tmp_path / "sk"
    public.write_text("pk-lf-from-file\n", encoding="utf-8")
    secret.write_text("sk-lf-from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # no .env to read keys from
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://langfuse-web:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY_FILE", str(public))
    monkeypatch.setenv("LANGFUSE_SECRET_KEY_FILE", str(secret))
    cfg = LangfuseSettings()
    assert cfg.public_key.get_secret_value() == "pk-lf-from-file"
    assert cfg.secret_key.get_secret_value() == "sk-lf-from-file"
    assert cfg.enabled


# ---------------------------------------------------------------------------
# Off: nothing changes, nothing starts
# ---------------------------------------------------------------------------
def test_off_returns_the_same_config():
    config = {"configurable": {"thread_id": "t"}, "callbacks": ["usage"]}
    traced = lf.trace_run_config(
        config, kind="chat", name="a", trace=_backend_trace(), session_id="c", user_id="u"
    )
    assert traced is config


def test_init_without_configuration_stays_off(monkeypatch):
    _configure(url="")
    monkeypatch.setattr(lf, "Langfuse", pytest.fail)  # must never be constructed
    lf.init_langfuse()
    assert not lf.tracing_enabled()


def test_a_client_that_cannot_start_leaves_tracing_off(monkeypatch):
    _configure()

    def _boom(**_kwargs):
        raise ValueError("bad base url")

    monkeypatch.setattr(lf, "Langfuse", _boom)
    lf.init_langfuse()
    assert not lf.tracing_enabled()


def test_init_passes_the_mask_and_the_keys(monkeypatch):
    _configure(public="pk-lf-abc", secret="sk-lf-def")  # noqa: S106 - test keys
    built: list[dict] = []

    def fake_client(**kwargs):
        built.append(kwargs)
        return object()

    monkeypatch.setattr(lf, "Langfuse", fake_client)
    monkeypatch.setattr(lf, "_client", None)
    lf.init_langfuse()
    assert lf.tracing_enabled()
    (kwargs,) = built
    assert kwargs["mask"] is lf.mask
    assert (kwargs["public_key"], kwargs["secret_key"]) == ("pk-lf-abc", "sk-lf-def")
    assert kwargs["base_url"] == "http://langfuse-web:3000"


def test_shutdown_without_a_client_is_a_no_op(monkeypatch):
    monkeypatch.setattr(lf, "_client", None)
    lf.shutdown_langfuse()
    assert not lf.tracing_enabled()


def test_shutdown_survives_a_failing_flush(monkeypatch):
    def failing_shutdown():
        raise RuntimeError("export failed")

    monkeypatch.setattr(lf, "_client", types.SimpleNamespace(shutdown=failing_shutdown))
    lf.shutdown_langfuse()
    assert not lf.tracing_enabled()


# ---------------------------------------------------------------------------
# On: one handler per run, the trace's attributes, the client pseudonymised
# ---------------------------------------------------------------------------
def test_on_appends_a_fresh_handler_and_keeps_existing_callbacks(tracing_on):
    config = {"configurable": {"thread_id": "t"}, "callbacks": ["usage"], "metadata": {"keep": 1}}
    first = tracing_on.trace_run_config(config, kind="chat", name="agent-x")
    second = tracing_on.trace_run_config(config, kind="chat", name="agent-x")

    assert first["callbacks"][0] == "usage"
    assert isinstance(first["callbacks"][1], _FakeHandler)
    assert first["callbacks"][1] is not second["callbacks"][1]
    assert first["callbacks"][1].public_key == "pk-lf-test"
    assert first["metadata"]["keep"] == 1
    assert first["configurable"] == {"thread_id": "t"}
    # The caller's config is never written into.
    assert config["callbacks"] == ["usage"]
    assert "langfuse_trace_name" not in config["metadata"]


def test_on_sets_name_session_tags_and_the_client_pseudonym(tracing_on):
    config = tracing_on.trace_run_config(
        {}, kind="chat", name="assistant", session_id="conv-1", user_id=CLIENT_ID, tags=("x", "")
    )
    meta = config["metadata"]
    assert meta["langfuse_trace_name"] == "assistant"
    assert meta["langfuse_session_id"] == "conv-1"
    assert meta["langfuse_tags"] == sorted({"agents", "chat", "x"})
    assert meta["langfuse_user_id"] == hash_identifier(CLIENT_ID)
    assert CLIENT_ID not in str(meta)
    # Without a backend trace the run is a trace of its own.
    assert config["callbacks"][0].trace_context is None


def test_an_already_hashed_user_passes_through(tracing_on):
    hashed = hash_identifier(CLIENT_ID)
    meta = tracing_on.trace_run_config({}, kind="chat", name="a", user_id=hashed)["metadata"]
    assert meta["langfuse_user_id"] == hashed


def test_on_without_session_or_user_omits_them(tracing_on):
    meta = tracing_on.trace_run_config({}, kind="title", name="title")["metadata"]
    assert "langfuse_session_id" not in meta and "langfuse_user_id" not in meta


def test_a_callback_manager_is_left_alone(tracing_on):
    config = {"callbacks": object()}
    assert tracing_on.trace_run_config(config, kind="chat", name="a") is config


# ---------------------------------------------------------------------------
# Nested under the backend's trace
# ---------------------------------------------------------------------------
def test_a_backend_trace_nests_the_run_under_its_observation(tracing_on):
    config = tracing_on.trace_run_config(
        {},
        kind="chat",
        name="assistant",
        trace=_backend_trace(),
        session_id="conv-local",
        user_id="local-user",
    )
    handler = config["callbacks"][0]
    assert handler.trace_context == {"trace_id": _TRACE_ID, "parent_span_id": _SPAN_ID}
    meta = config["metadata"]
    # The backend named the trace; the run keeps that name.
    assert "langfuse_trace_name" not in meta
    # The trace's own attributes win over the run's.
    assert meta["langfuse_session_id"] == "conv-from-backend"
    assert meta["langfuse_user_id"] == hash_identifier(CLIENT_ID)


def test_a_raw_user_id_in_the_trace_is_still_hashed(tracing_on):
    trace = _backend_trace(user_id=CLIENT_ID)
    meta = tracing_on.trace_run_config({}, kind="chat", name="a", trace=trace)["metadata"]
    assert meta["langfuse_user_id"] == hash_identifier(CLIENT_ID)
    assert CLIENT_ID not in str(meta)


def test_a_malformed_backend_trace_starts_a_trace_of_its_own(tracing_on):
    trace = _backend_trace(trace_id="not-a-trace-id")
    config = tracing_on.trace_run_config({}, kind="chat", name="assistant", trace=trace)
    assert config["callbacks"][0].trace_context is None
    assert config["metadata"]["langfuse_trace_name"] == "assistant"


@pytest.mark.parametrize(
    ("trace", "expected"),
    [
        (None, None),
        ("00-abc", None),
        ({}, None),
        ({"trace_id": "abc"}, None),
        ({"trace_id": _TRACE_ID + "0"}, None),
        ({"trace_id": "g" * 32}, None),
        ({"trace_id": _TRACE_ID}, {"trace_id": _TRACE_ID}),
        ({"trace_id": _TRACE_ID.upper()}, {"trace_id": _TRACE_ID}),
        (
            {"trace_id": _TRACE_ID, "parent_observation_id": "short"},
            {"trace_id": _TRACE_ID},
        ),
        (
            {"trace_id": _TRACE_ID, "parent_observation_id": _SPAN_ID.upper()},
            {"trace_id": _TRACE_ID, "parent_span_id": _SPAN_ID},
        ),
    ],
)
def test_parent_trace_context_uses_only_well_formed_ids(trace, expected):
    assert lf.parent_trace_context(trace) == expected


class _Probe(BaseAgent):
    name = "probe"


def test_base_agent_traces_a_chat_run_under_the_backend_trace(tracing_on):
    agent = _Probe(config=run_config(thread_id="branch-1", trace=_backend_trace()))
    config = agent._traced_config()
    meta = config["metadata"]
    assert config["callbacks"][0].trace_context == {
        "trace_id": _TRACE_ID,
        "parent_span_id": _SPAN_ID,
    }
    assert meta["langfuse_session_id"] == "conv-from-backend"
    assert meta["langfuse_user_id"] == hash_identifier(CLIENT_ID)
    assert "chat" in meta["langfuse_tags"] and "probe" in meta["langfuse_tags"]


def test_base_agent_without_a_backend_trace_uses_the_conversation_and_client(tracing_on):
    agent = _Probe(config=run_config(thread_id="branch-1"))
    meta = agent._traced_config()["metadata"]
    assert meta["langfuse_session_id"] == "c1"
    assert meta["langfuse_user_id"] == hash_identifier(CLIENT_ID)
    assert meta["langfuse_trace_name"] == "probe"
    assert CLIENT_ID not in str(meta)


def test_base_agent_tags_a_background_task_run_as_subagent(tracing_on):
    config = run_config(thread_id="task-9")
    config["context"]["async_task_id"] = "task-9"
    meta = _Probe(config=config)._traced_config()["metadata"]
    assert meta["langfuse_session_id"] == "c1"  # the parent conversation's session
    assert "subagent" in meta["langfuse_tags"] and "chat" not in meta["langfuse_tags"]


def test_base_agent_hands_the_run_config_back_untouched_when_off():
    agent = _Probe(config=run_config(trace=_backend_trace()))
    assert agent._traced_config() is agent.run_config


# ---------------------------------------------------------------------------
# The mask
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("key pk-lf-1234567890abcdef here", "[REDACTED_LANGFUSE_KEY]"),
        ("sk-proj-ABCDEFGHIJKLMNOPQRSTUV", "[REDACTED_API_KEY]"),
        ("sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV", "[REDACTED_API_KEY]"),
        ("AKIAABCDEFGHIJKLMNOP", "[REDACTED_AWS_KEY]"),
        ("ghp_" + "a" * 36, "[REDACTED_GITHUB_TOKEN]"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijklmnop", "[REDACTED_JWT]"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "Bearer [REDACTED]"),
        ("write to jane.doe@example.com", "[REDACTED_EMAIL]"),
        ("postgresql://admin:hunter2@postgres:5432/db", "postgresql://[REDACTED]@postgres"),
    ],
)
def test_mask_removes_secret_patterns(raw, expected):
    masked = lf.mask(data=raw)
    assert expected in masked
    for secret in (
        "1234567890abcdef",
        "ABCDEFGHIJKLMNOPQRSTUV",
        "AKIAABCDEFGHIJKLMNOP",
        "a" * 36,
        "abcdefghijklmnop",
        "jane.doe",
        "hunter2",
    ):
        assert secret not in masked


def test_mask_walks_nested_structures_and_blanks_credential_fields():
    data = {
        "messages": [{"role": "user", "content": "mail me at a@b.co"}],
        "tool_args": {"password": "hunter2", "api_token": "abc", "max_tokens": 512},
        "tuple": ("sk-proj-ABCDEFGHIJKLMNOPQRSTUV",),
        "n": 3,
        "ok": True,
        "none": None,
    }
    masked = lf.mask(data=data)
    assert masked["messages"][0]["content"] == "mail me at [REDACTED_EMAIL]"
    assert masked["tool_args"] == {
        "password": "[REDACTED]",
        "api_token": "[REDACTED]",
        "max_tokens": 512,
    }
    assert masked["tuple"] == ["[REDACTED_API_KEY]"]
    assert (masked["n"], masked["ok"], masked["none"]) == (3, True, None)
    assert data["tool_args"]["password"] == "hunter2"  # noqa: S105 - the input is not mutated


def test_mask_fails_closed_on_unknown_shapes():
    class Payload(BaseModel):
        note: str

    class Opaque:
        def __str__(self):
            return "token=sk-proj-ABCDEFGHIJKLMNOPQRSTUV"

    assert lf.mask(data=Payload(note="x@y.io")) == {"note": "[REDACTED_EMAIL]"}
    assert "ABCDEFGHIJKLMNOPQRSTUV" not in lf.mask(data=Opaque())
    assert lf.mask(data=b"\x00\x01") == "<bytes:2>"


def test_mask_bounds_pathological_depth():
    deep: list = []
    node = deep
    for _ in range(200):
        child: list = []
        node.append(child)
        node = child
    assert "[TRUNCATED]" in str(lf.mask(data=deep))
