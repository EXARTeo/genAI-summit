"""The service's core plumbing: the internal-caller gate, error responses, settings,
the checkpointer accessors, the end-of-run cache release, fork seeding and
``BaseAgent``'s identity and config.

Each piece is driven directly (no route, no database): a hand-built Starlette
request for the gate and the handlers, small stubs for the graph a run holds.
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import CLIENT_ID, CONVERSATION_ID, SERVICE_ROOT
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from core import error_handling
from core.security import internal_trust
from core.settings import settings
from harness.abstractions.base_agent import BaseAgent
from harness.agui import AGUIEmitter
from harness.checkpointer import fork
from harness.checkpointer import store as checkpointer_store
from utils import checkpointer as checkpointer_util

# `core` re-exports the settings object under the module's name, so the
# module itself is fetched by path.
settings_module = importlib.import_module("core.settings")

FALLBACK_DETAIL = "Request could not be completed. Please try again."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_request(*, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": ("203.0.113.7", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


class _RecordingLogger:
    """Captures structured-logger calls without a real backend."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.calls.append((method, args, kwargs))

    def log(self, *args: Any, **kwargs: Any) -> None:
        self._record("log", args, kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._record("warning", args, kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._record("error", args, kwargs)

    def exception(self, *args: Any, **kwargs: Any) -> None:
        self._record("exception", args, kwargs)


def _frame_payload(frame: bytes) -> dict[str, Any]:
    assert frame.startswith(b"data: ")
    assert frame.endswith(b"\n\n")
    return json.loads(frame[len(b"data: ") : -2].decode("utf-8"))


def _secret() -> str:
    return settings.proxy.internal_service_secret.get_secret_value()


# ---------------------------------------------------------------------------
# core/security/internal_trust.py
# ---------------------------------------------------------------------------
def test_the_secret_header_admits_the_caller():
    header = internal_trust.INTERNAL_SECRET_HEADER
    assert internal_trust.is_internal_caller(_make_request(headers={header: _secret()})) is True
    assert internal_trust.is_internal_caller(_make_request(headers={header: "wrong"})) is False
    assert internal_trust.is_internal_caller(_make_request(headers={header: ""})) is False
    assert internal_trust.is_internal_caller(_make_request()) is False


def test_without_a_configured_secret_every_caller_is_admitted():
    # Development and test only; settings refuse to start so elsewhere.
    settings.proxy.internal_service_secret = SecretStr("")
    assert internal_trust.is_internal_caller(_make_request()) is True
    assert internal_trust.internal_service_headers() == {}


def test_require_internal_caller():
    header = internal_trust.INTERNAL_SECRET_HEADER
    assert (
        internal_trust.require_internal_caller(_make_request(headers={header: _secret()})) is None
    )
    with pytest.raises(HTTPException) as excinfo:
        internal_trust.require_internal_caller(_make_request())
    assert excinfo.value.status_code == 403


def test_internal_service_headers_carry_the_secret():
    assert internal_trust.internal_service_headers() == {
        internal_trust.INTERNAL_SECRET_HEADER: _secret()
    }


# ---------------------------------------------------------------------------
# core/error_handling.py
# ---------------------------------------------------------------------------
async def test_handle_http_exception_client_error():
    logger = _RecordingLogger()
    handler = error_handling.AgentServiceExceptionHandler(logger)

    exc = HTTPException(status_code=404, detail="Not found", headers={"X-Foo": "bar"})
    response = await handler.handle_http_exception(_make_request(), exc)

    assert response.status_code == 404
    assert json.loads(response.body) == {"detail": "Not found"}
    assert response.headers["X-Foo"] == "bar"
    method, _args, kwargs = logger.calls[0]
    assert method == "log"
    # status < 500: no traceback, detail withheld from the log.
    assert kwargs["exc_info"] is False
    assert kwargs["detail"] is None


async def test_handle_http_exception_server_error():
    logger = _RecordingLogger()
    handler = error_handling.AgentServiceExceptionHandler(logger)

    response = await handler.handle_http_exception(
        _make_request(), HTTPException(status_code=500, detail="boom")
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "boom"}
    _method, _args, kwargs = logger.calls[0]
    assert kwargs["exc_info"] is True
    assert kwargs["detail"] == "boom"


async def test_handle_http_exception_blank_detail_uses_fallback():
    handler = error_handling.AgentServiceExceptionHandler(_RecordingLogger())
    response = await handler.handle_http_exception(
        _make_request(), HTTPException(status_code=400, detail="   ")
    )
    assert response.status_code == 400
    assert json.loads(response.body) == {"detail": FALLBACK_DETAIL}


async def test_handle_validation_exception():
    """A real ``RequestValidationError``: the raw ``input`` (a secret here) never
    reaches the log, only where and why."""
    logger = _RecordingLogger()
    handler = error_handling.AgentServiceExceptionHandler(logger)
    exc = RequestValidationError(
        [
            {
                "loc": ("query", "limit"),
                "msg": "Input should be less than or equal to 50",
                "type": "less_than_equal",
                "input": "secret-value-51",
                "ctx": {"le": 50},
            }
        ]
    )

    response = await handler.handle_validation_exception(_make_request(), exc)

    assert response.status_code == 422
    assert "Invalid request" in json.loads(response.body)["detail"]
    method, _args, fields = logger.calls[0]
    assert method == "warning"
    assert fields["errors"] == [
        {
            "loc": ["query", "limit"],
            "msg": "Input should be less than or equal to 50",
            "type": "less_than_equal",
        }
    ]
    assert "secret-value-51" not in repr(logger.calls)


async def test_handle_unhandled_exception():
    logger = _RecordingLogger()
    handler = error_handling.AgentServiceExceptionHandler(logger)

    response = await handler.handle_unhandled_exception(_make_request(), RuntimeError("kaboom"))

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Something went wrong. Please try again."}
    assert logger.calls[0][0] == "exception"
    assert "kaboom" not in repr(logger.calls)


def test_public_http_detail():
    detail = error_handling.AgentServiceExceptionHandler._public_http_detail
    assert detail(HTTPException(status_code=400, detail="real")) == "real"
    assert detail(HTTPException(status_code=400, detail="")) == FALLBACK_DETAIL
    # A structured detail without a message is not passed through.
    assert detail(HTTPException(status_code=400, detail={"k": "v"})) == FALLBACK_DETAIL


def test_a_structured_client_error_is_kept_whole():
    # A resume's stale/pending interrupt ids: the backend acts on them.
    stale = {"message": "stale", "stale_interrupt_ids": ["a"], "pending_interrupt_ids": ["b"]}
    detail = error_handling.AgentServiceExceptionHandler._public_http_detail
    assert detail(HTTPException(status_code=409, detail=stale)) == stale
    # Never for a server error: structured internals must not leak.
    assert detail(HTTPException(status_code=500, detail=stale)) == FALLBACK_DETAIL


def test_encode_run_error_frame():
    logger = _RecordingLogger()
    frame = error_handling.agent_stream_error_handler.encode_run_error(
        logger, RuntimeError("nope"), agent_slug="assistant", public_message="Custom failure."
    )
    assert _frame_payload(frame) == {"type": "RUN_ERROR", "message": "Custom failure."}
    method, _args, kwargs = logger.calls[0]
    assert method == "error"
    assert kwargs["agent_slug"] == "assistant"
    assert kwargs["exception_type"] == "RuntimeError"
    # The exception's text is an internal: never in the frame.
    assert b"nope" not in frame


def test_encode_run_error_default_message():
    frame = error_handling.agent_stream_error_handler.encode_run_error(
        _RecordingLogger(), ValueError("x"), agent_slug="assistant"
    )
    assert _frame_payload(frame)["message"] == (
        "The agent could not complete this run. Please try again."
    )


# ---------------------------------------------------------------------------
# core/settings.py
# ---------------------------------------------------------------------------
def test_resolve_file_backed_secret_from_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("  file-secret-value  ")
    monkeypatch.setenv("MY_TEST_SECRET_FILE", str(secret_file))
    monkeypatch.delenv("MY_TEST_SECRET", raising=False)

    assert settings_module._resolve_file_backed_secret("MY_TEST_SECRET") == "file-secret-value"


def test_resolve_file_backed_secret_file_unreadable_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TEST_SECRET_FILE", str(tmp_path / "does-not-exist.txt"))
    monkeypatch.delenv("MY_TEST_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="could not be read"):
        settings_module._resolve_file_backed_secret("MY_TEST_SECRET")


def test_resolve_file_backed_secret_empty_file_then_env(tmp_path, monkeypatch):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   ")
    monkeypatch.setenv("MY_TEST_SECRET_FILE", str(empty_file))
    monkeypatch.setenv("MY_TEST_SECRET", "  env-secret  ")

    assert settings_module._resolve_file_backed_secret("MY_TEST_SECRET") == "env-secret"


def test_resolve_file_backed_secret_first_name_wins(monkeypatch):
    for name in ("FIRST_SECRET", "SECOND_SECRET"):
        monkeypatch.delenv(f"{name}_FILE", raising=False)
    monkeypatch.delenv("FIRST_SECRET", raising=False)
    monkeypatch.setenv("SECOND_SECRET", "second")
    assert settings_module._resolve_file_backed_secret("FIRST_SECRET", "SECOND_SECRET") == "second"
    monkeypatch.setenv("FIRST_SECRET", "first")
    assert settings_module._resolve_file_backed_secret("FIRST_SECRET", "SECOND_SECRET") == "first"


def test_resolve_file_backed_secret_missing_returns_none(monkeypatch):
    monkeypatch.delenv("ABSENT_SECRET_FILE", raising=False)
    monkeypatch.delenv("ABSENT_SECRET", raising=False)
    assert settings_module._resolve_file_backed_secret("ABSENT_SECRET") is None


def test_api_keys_settings_branches(monkeypatch):
    assert (
        settings_module.ApiKeysSettings(google=SecretStr("g-direct")).google.get_secret_value()
        == "g-direct"
    )
    assert settings_module.ApiKeysSettings(google="  g-key  ").google.get_secret_value() == "g-key"
    # An empty value falls back to the environment (GOOGLE_API_KEY, then GEMINI_API_KEY).
    monkeypatch.delenv("GOOGLE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert (
        settings_module.ApiKeysSettings(google=SecretStr("")).google.get_secret_value()
        == "from-env"
    )


def test_proxy_settings_secret_branches(monkeypatch):
    direct = settings_module.ProxySettings(internal_service_secret=SecretStr("abc"))
    assert direct.internal_service_secret.get_secret_value() == "abc"
    as_str = settings_module.ProxySettings(internal_service_secret="xyz")  # noqa: S106 - a test value
    assert as_str.internal_service_secret.get_secret_value() == "xyz"

    monkeypatch.delenv("INTERNAL_SERVICE_SECRET_FILE", raising=False)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "resolved-secret")
    resolved = settings_module.ProxySettings(internal_service_secret=SecretStr(""))
    assert resolved.internal_service_secret.get_secret_value() == "resolved-secret"

    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    empty = settings_module.ProxySettings(internal_service_secret=SecretStr(""))
    assert empty.internal_service_secret.get_secret_value() == ""


def test_logging_settings_normalization():
    instance = settings_module.LoggingSettings(LOG_LEVEL="debug", LOG_FORMAT="  JSON  ")
    assert instance.level == "DEBUG"
    assert instance.format == "json"
    direct = settings_module.LoggingSettings(redaction_secret=SecretStr("redact-me"))
    assert direct.redaction_secret.get_secret_value() == "redact-me"


def test_an_unset_redaction_secret_becomes_a_random_key(monkeypatch):
    monkeypatch.delenv("LOG_REDACTION_SECRET", raising=False)
    monkeypatch.delenv("LOG_REDACTION_SECRET_FILE", raising=False)
    alone = settings_module.LoggingSettings(redaction_secret=SecretStr(""))
    assert alone.redaction_secret.get_secret_value() == "agents-log-redaction"

    # The shared default is public (it is in the source), so the whole
    # settings tree replaces it with a per-process key.
    first = settings_module.Settings(logging=alone)
    second = settings_module.Settings(
        logging=settings_module.LoggingSettings(redaction_secret=SecretStr(""))
    )
    key = first.logging.redaction_secret.get_secret_value()
    assert key != "agents-log-redaction"
    assert len(key) == 64
    assert key != second.logging.redaction_secret.get_secret_value()


def test_settings_refuse_to_start_without_a_secret_outside_local(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET_FILE", raising=False)

    with pytest.raises(ValidationError, match="INTERNAL_SERVICE_SECRET must be set"):
        settings_module.Settings(
            app=settings_module.AppSettings(APP_ENV="production"),
            proxy=settings_module.ProxySettings(internal_service_secret=""),
        )


@pytest.mark.parametrize("env", ["development", "test", " TEST "])
def test_local_environments_may_run_without_a_secret(monkeypatch, env):
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET_FILE", raising=False)
    instance = settings_module.Settings(
        app=settings_module.AppSettings(APP_ENV=env),
        proxy=settings_module.ProxySettings(internal_service_secret=""),
    )
    assert instance.app.is_local is True
    assert instance.proxy.internal_service_secret.get_secret_value() == ""


def test_settings_build_with_a_secret_outside_local():
    instance = settings_module.Settings(
        app=settings_module.AppSettings(APP_ENV="production"),
        proxy=settings_module.ProxySettings(internal_service_secret="present"),  # noqa: S106 - a test value
    )
    assert instance.app.is_local is False
    assert instance.proxy.internal_service_secret.get_secret_value() == "present"


def test_mcp_is_on_only_with_a_gateway_url():
    assert settings_module.McpSettings(MCP_GATEWAY_URL="").enabled is False
    assert settings_module.McpSettings(MCP_GATEWAY_URL="   ").enabled is False
    assert settings_module.McpSettings(MCP_GATEWAY_URL="http://gw:8005/sse").enabled is True


def test_sandbox_execution_needs_the_switch_and_a_runner():
    def active(enabled: bool, url: str) -> bool:
        return settings_module.FilesystemSettings(
            SANDBOX_EXECUTION_ENABLED=enabled, SANDBOX_RUNNER_URL=url
        ).sandbox_execution_active

    assert active(True, " http://runner:8090 ") is True
    assert active(True, "") is False
    assert active(False, "http://runner:8090") is False


def test_langfuse_is_on_only_with_url_and_both_keys():
    def enabled(**kwargs: Any) -> bool:
        base = {"LANGFUSE_BASE_URL": "http://lf", "public_key": "pk", "secret_key": "sk"}
        return settings_module.LangfuseSettings(**{**base, **kwargs}).enabled

    assert enabled() is True
    assert enabled(LANGFUSE_BASE_URL="") is False


def test_agent_models_parse_from_json():
    registry = settings_module.AgentRegistrySettings(
        AGENT_MODELS=json.dumps({"openai:gpt-x": {"reasoning": True, "context_window": 1000}})
    )
    assert set(registry.models) == {"openai:gpt-x"}
    assert registry.models["openai:gpt-x"].reasoning is True
    assert registry.models["openai:gpt-x"].context_window == 1000


def test_agent_models_refuse_unknown_facts():
    with pytest.raises(ValidationError):
        settings_module.AgentRegistrySettings(
            AGENT_MODELS=json.dumps({"openai:gpt-x": {"cost": 1}})
        )
    with pytest.raises(ValidationError):
        settings_module.AgentRegistrySettings(
            AGENT_MODELS=json.dumps({"openai:gpt-x": {"context_window": 0}})
        )


def test_the_registry_defaults(monkeypatch):
    # The suite points AGENTS_DIR / DEFAULT_AGENT_SLUG at its fixture; the
    # service's own defaults are its definitions folder and the chat copilot.
    monkeypatch.delenv("AGENTS_DIR", raising=False)
    monkeypatch.delenv("DEFAULT_AGENT_SLUG", raising=False)
    monkeypatch.delenv("AGENT_MODELS", raising=False)
    registry = settings_module.AgentRegistrySettings()
    assert registry.default_agent_slug == "mnamon"
    assert registry.agents_dir == SERVICE_ROOT / "definitions"
    # Gemini only: the product's model facts.
    assert all(spec.startswith("google_genai:") for spec in registry.models)
    assert registry.models["google_genai:gemini-3.5-flash-lite"].context_window == 1_048_576


def test_the_service_ships_only_the_chat_copilot():
    shipped = [p.name for p in (SERVICE_ROOT / "definitions").iterdir() if p.name != ".gitkeep"]
    assert shipped == ["mnamon"]


# ---------------------------------------------------------------------------
# harness/checkpointer/store.py
# ---------------------------------------------------------------------------
def test_set_and_get_checkpointer(monkeypatch):
    monkeypatch.setattr(checkpointer_store, "_checkpointer", None)
    sentinel = object()
    checkpointer_store.set_checkpointer(sentinel)
    assert checkpointer_store.has_checkpointer_initialized() is True
    # One process-wide saver: the same handle every call.
    assert checkpointer_store.get_checkpointer() is sentinel
    assert checkpointer_store.get_checkpointer() is sentinel


def test_get_checkpointer_uninitialized_raises(monkeypatch):
    monkeypatch.setattr(checkpointer_store, "_checkpointer", None)
    assert checkpointer_store.has_checkpointer_initialized() is False
    with pytest.raises(RuntimeError):
        checkpointer_store.get_checkpointer()


def test_the_runtime_pool_accessors():
    pool = object()
    checkpointer_store.set_runtime_pool(pool)
    assert checkpointer_store.has_runtime_pool() is True
    assert checkpointer_store.get_runtime_pool() is pool
    checkpointer_store.set_runtime_pool(None)
    assert checkpointer_store.has_runtime_pool() is False
    with pytest.raises(RuntimeError):
        checkpointer_store.get_runtime_pool()


# ---------------------------------------------------------------------------
# utils/checkpointer.py (namespace-cache release; never deletes the checkpoint)
# ---------------------------------------------------------------------------
class _FakeCompiled:
    """Stubs the async ``aget_state`` the durable saver exposes."""

    def __init__(self, snapshot: Any = None, raises: bool = False) -> None:
        self._snapshot = snapshot
        self._raises = raises
        self.calls: list[Any] = []

    async def aget_state(self, run_config: Any) -> Any:
        self.calls.append(run_config)
        if self._raises:
            raise RuntimeError("probe failure")
        return self._snapshot


def _fake_agent(compiled: Any, thread_id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(
        compiled=compiled,
        run_config={"configurable": {"thread_id": thread_id}},
        agui_emitter=AGUIEmitter(),
    )


@pytest.fixture
def released(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(checkpointer_util, "release_namespace_bindings", calls.append)
    return calls


async def test_release_skips_an_empty_run_id(released):
    await checkpointer_util.release_checkpoint_unless_paused(object(), "")
    assert released == []


async def test_release_keeps_the_bindings_of_a_paused_run(released):
    agent = _fake_agent(_FakeCompiled(snapshot=SimpleNamespace(interrupts=["pending"])))
    await checkpointer_util.release_checkpoint_unless_paused(agent, "run-1")
    # A later /resume rehydrates the same namespace bindings.
    assert released == []


async def test_release_drops_the_bindings_of_a_finished_run(released):
    compiled = _FakeCompiled(snapshot=SimpleNamespace(interrupts=[]))
    await checkpointer_util.release_checkpoint_unless_paused(_fake_agent(compiled, "t2"), "run-2")
    assert released == ["run-2"]
    assert compiled.calls == [{"configurable": {"thread_id": "t2"}}]


async def test_release_on_probe_failure(released):
    agent = _fake_agent(_FakeCompiled(raises=True))
    await checkpointer_util.release_checkpoint_unless_paused(agent, "run-3")
    assert released == ["run-3"]


async def test_release_without_a_compiled_graph(released):
    await checkpointer_util.release_checkpoint_unless_paused(_fake_agent(None), "run-4")
    assert released == ["run-4"]


async def test_checkpoint_committed_carries_the_head():
    snapshot = SimpleNamespace(config={"configurable": {"checkpoint_id": "cp-7"}})
    frame = await checkpointer_util.emit_checkpoint_committed(
        _fake_agent(_FakeCompiled(snapshot=snapshot)), "t1", _RecordingLogger(), None
    )
    payload = _frame_payload(frame)
    assert payload["type"] == "CUSTOM"
    assert payload["name"] == "CHECKPOINT_COMMITTED"
    assert payload["value"] == {"thread_id": "t1", "checkpoint_id": "cp-7"}


async def test_checkpoint_committed_needs_a_thread_and_a_graph():
    logger = _RecordingLogger()
    agent = _fake_agent(_FakeCompiled(snapshot=SimpleNamespace(config={})))
    assert await checkpointer_util.emit_checkpoint_committed(agent, "", logger, None) is None
    assert (
        await checkpointer_util.emit_checkpoint_committed(_fake_agent(None), "t1", logger, None)
        is None
    )


async def test_checkpoint_committed_read_failure_is_logged_not_raised():
    logger = _RecordingLogger()
    frame = await checkpointer_util.emit_checkpoint_committed(
        _fake_agent(_FakeCompiled(raises=True)), "t1", logger, {"req": "x"}
    )
    assert frame is None
    assert logger.calls[0][0] == "warning"


# ---------------------------------------------------------------------------
# harness/checkpointer/fork.py (copy-on-fork seeding)
# ---------------------------------------------------------------------------
class _ForkGraph:
    """Stub graph: records aupdate_state calls; aget_state returns canned snapshots."""

    def __init__(self, states: dict[tuple, Any]) -> None:
        # Keyed by (thread_id, checkpoint_id or None).
        self._states = states
        self.updated: list[tuple[str, Any]] = []

    async def aget_state(self, config: Any) -> Any:
        cfg = config["configurable"]
        return self._states.get((cfg["thread_id"], cfg.get("checkpoint_id")))

    async def aupdate_state(self, config: Any, values: Any, **_: Any) -> None:
        self.updated.append((config["configurable"]["thread_id"], values))


@pytest.fixture
def scratch_copies(monkeypatch) -> list[tuple[str, str]]:
    """The scratch copy-on-fork calls (the store itself needs Postgres)."""
    calls: list[tuple[str, str]] = []

    async def copy(source: str, target: str) -> int:
        calls.append((source, target))
        return 0

    monkeypatch.setattr(fork, "copy_branch_scratch", copy)
    return calls


async def _seed(graph: _ForkGraph) -> bool:
    return await fork.seed_thread_from_checkpoint(
        graph=graph, source_thread_id="src", source_checkpoint_id="cp-9", target_thread_id="new"
    )


async def test_fork_seeds_an_empty_target_from_the_source(scratch_copies):
    src_values = {"messages": ["m1", "m2"], "files": {"/x": 1}}
    graph = _ForkGraph(
        {
            ("new", None): SimpleNamespace(values={}),
            ("src", "cp-9"): SimpleNamespace(values=src_values),
        }
    )
    assert await _seed(graph) is True
    assert graph.updated == [("new", src_values)]
    assert scratch_copies == [("src", "new")]


async def test_fork_skips_a_target_already_seeded(scratch_copies):
    graph = _ForkGraph({("new", None): SimpleNamespace(values={"messages": ["existing"]})})
    assert await _seed(graph) is True
    assert graph.updated == []
    # The scratch copy still runs: it is idempotent and an earlier attempt may
    # have seeded the state without it.
    assert scratch_copies == [("src", "new")]


async def test_fork_returns_false_on_an_empty_source(scratch_copies):
    graph = _ForkGraph(
        {("new", None): SimpleNamespace(values={}), ("src", "cp-9"): SimpleNamespace(values={})}
    )
    assert await _seed(graph) is False
    assert graph.updated == []


async def test_fork_needs_both_threads(scratch_copies):
    graph = _ForkGraph({})
    assert (
        await fork.seed_thread_from_checkpoint(
            graph=graph, source_thread_id="", source_checkpoint_id=None, target_thread_id="new"
        )
        is False
    )
    assert scratch_copies == []


async def test_fork_degrades_when_the_graph_fails(scratch_copies):
    class _Broken(_ForkGraph):
        async def aget_state(self, config: Any) -> Any:
            raise RuntimeError("db down")

    assert await _seed(_Broken({})) is False


async def test_scratch_copy_without_a_pool_copies_nothing():
    checkpointer_store.set_runtime_pool(None)
    assert await fork.copy_branch_scratch("src", "new") == 0


# ---------------------------------------------------------------------------
# harness/abstractions/base_agent.py
# ---------------------------------------------------------------------------
class _NamedTool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_base_agent_manifest():
    assert BaseAgent.manifest() == {
        "id": "base-agent",
        "slug": "base-agent",
        "name": "Base Agent",
        "version": "0.0.1",
        "type": "langgraph agent",
        "description": "",
        "icon": "",
        "kind": "chat",
    }


def test_base_agent_metadata_property():
    assert BaseAgent().metadata == BaseAgent.manifest()


def test_base_agent_default_construction():
    agent = BaseAgent()
    assert agent.config == {}
    assert agent.run_config["configurable"]["thread_id"]
    assert agent.config_tool_names == []
    assert agent.all_mcp_tools is False
    assert agent.tools == []
    assert agent.context == {}
    assert agent.client_id == ""


def test_each_agent_without_a_thread_gets_a_fresh_one():
    first = BaseAgent().run_config["configurable"]["thread_id"]
    assert first != BaseAgent().run_config["configurable"]["thread_id"]


def test_base_agent_valid_full_config():
    agent = BaseAgent(
        config={
            "run_config": {"configurable": {"thread_id": "abc"}},
            "context": {"client_id": f"  {CLIENT_ID} ", "conversation_id": " c1 "},
        }
    )
    assert agent.run_config == {"configurable": {"thread_id": "abc"}}
    assert agent.context == {"client_id": CLIENT_ID, "conversation_id": CONVERSATION_ID}
    assert agent.client_id == CLIENT_ID
    # Tools are declared per agent (a YamlDeepAgent seeds them from its spec),
    # never from the request config.
    assert agent.config_tool_names == []


def test_a_null_run_config_falls_back_to_a_fresh_thread():
    agent = BaseAgent(
        config={
            "run_config": None,
            "context": {"client_id": CLIENT_ID, "conversation_id": CONVERSATION_ID},
        }
    )
    assert agent.run_config["configurable"]["thread_id"]


def test_base_agent_run_config_without_configurable_is_kept():
    agent = BaseAgent(config={"run_config": {"other": "value"}})
    assert agent.run_config == {"other": "value"}


def test_base_agent_attach_tools_with_nothing_declared_attaches_nothing():
    agent = BaseAgent()
    agent.attach_tools([_NamedTool("search")])
    assert agent.tools == []
    assert agent.tools_names == []


def test_base_agent_encode_run_error():
    payload = _frame_payload(BaseAgent._encode_run_error(RuntimeError("boom")))
    assert payload["type"] == "RUN_ERROR"
    assert "boom" not in payload["message"]
