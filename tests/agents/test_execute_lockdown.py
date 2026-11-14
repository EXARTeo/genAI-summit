"""Sandbox-execution lockdown invariants, and the sandboxed ``execute`` itself.

While execution is off (``SANDBOX_EXECUTION_ENABLED`` false, or no
``SANDBOX_RUNNER_URL``) there must be no code-execution path: the workspace's
composite default backend must not be sandbox-capable (that is exactly what
makes deepagents surface its built-in ``execute`` tool), and the host-shell
backend must never even be imported in service code.

When it is on, ``execute`` is one ``POST /v1/exec`` to the sandbox runner. The
runner is another service; here it is an ``httpx.MockTransport`` speaking its
contract. What is pinned is this side: what is sent (the runner secret, a
pseudonymous client id, the conversation's input/ and output/), what the model
reads back, that an outage is an error result and never a fallback, and that
no layer can run a command without the user's approval.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import httpx
import pytest
from conftest import CLIENT_ID, CONVERSATION_ID
from deepagents import _models as deepagents_models
from deepagents.backends.protocol import SandboxBackendProtocol
from deepagents.middleware.filesystem import supports_execution
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import Field, SecretStr

from core.logging.redaction import hash_identifier
from core.settings import FilesystemSettings, settings
from harness.abstractions import subagent_tree
from harness.abstractions.agent_spec import AgentSpec
from harness.abstractions.deep_agent import DeepAgent
from harness.conversation_files import ConversationFiles, ConversationFilesBackend
from harness.conversation_files.inputs import UPLOAD_WRITER
from harness.conversation_files.store import ConversationFileStore
from harness.filesystem import sandbox_backend as sandbox_module
from harness.filesystem import workspace as workspace_module
from harness.tools import gates
from harness.tools.builtins import BUILTIN_BY_NAME

SERVICE_SRC = Path(__file__).resolve().parents[2] / "product" / "agents"
RUNNER_URL = "https://sandbox_runner:8090"
PROBE_MODEL = "openai:gpt-4o-mini"

# Import statements are banned; comments explaining the ban are fine.
_IMPORT_RE = re.compile(
    r"^\s*(from\s+\S+\s+import\s+.*LocalShellBackend|import\s+.*LocalShellBackend)",
    re.MULTILINE,
)


def _files(agent_slug: str = "agent-1") -> ConversationFiles:
    """A run's conversation files over a pool that is never queried here."""
    return ConversationFiles(
        client_id=CLIENT_ID,
        conversation_id="conv-1",
        agent_slug=agent_slug,
        store=ConversationFileStore(object()),
    )


def _build(files: ConversationFiles | None = None, agent_slug: str = "agent-1"):
    return workspace_module.build_workspace_backend(
        client_id=CLIENT_ID, agent_slug=agent_slug, files=files or _files(agent_slug)
    )


def _enable(monkeypatch, *, url: str = RUNNER_URL) -> None:
    monkeypatch.setattr(settings.filesystem, "sandbox_execution_enabled", True)
    monkeypatch.setattr(settings.filesystem, "sandbox_runner_url", url)


class _Runner:
    """A scripted sandbox runner: records every request, answers from a queue
    (the last answer repeats)."""

    def __init__(self, *answers):
        self.requests: list[httpx.Request] = []
        self._answers = list(answers) or [_ok()]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def _ok(**overrides) -> httpx.Response:
    body = {
        "exit_code": 0,
        "stdout": "hi\n",
        "stderr": "",
        "truncated": False,
        "duration_ms": 42,
        "killed_reason": None,
    }
    body.update(overrides)
    return httpx.Response(200, json=body)


def _backend(runner: _Runner, **identity) -> sandbox_module.RemoteSandboxBackend:
    ids = {
        "client_id": CLIENT_ID,
        "agent_slug": "agent-1",
        "conversation_id": "conv-1",
        **identity,
    }
    return sandbox_module.RemoteSandboxBackend(
        **ids,
        runner_url=RUNNER_URL,
        transport=runner.transport,
        async_transport=runner.transport,
    )


def _wire_runner(monkeypatch, runner: _Runner) -> None:
    """Make the workspace mint its sandbox backend against ``runner``."""
    real = sandbox_module.RemoteSandboxBackend

    class _Wired(real):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=runner.transport, async_transport=runner.transport)

    monkeypatch.setattr(workspace_module, "RemoteSandboxBackend", _Wired)


# ---------------------------------------------------------------------------
# The lockdown
# ---------------------------------------------------------------------------
def test_local_shell_backend_is_never_imported():
    """LocalShellBackend executes commands on the host process: its import is
    banned from the entire agents service, not just discouraged."""
    offenders: list[str] = []
    for path in SERVICE_SRC.rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        if _IMPORT_RE.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path.relative_to(SERVICE_SRC)))
    assert not offenders, f"LocalShellBackend import found in: {offenders}"


def test_the_workspace_builds_with_sandbox_execution_disabled():
    assert settings.filesystem.sandbox_execution_enabled is False
    backend = _build()
    assert type(backend.default) is workspace_module.BranchScratchBackend
    assert not isinstance(backend.default, SandboxBackendProtocol)
    assert not supports_execution(backend)


def test_the_workspace_refuses_a_sandbox_default_when_disabled(monkeypatch):
    """The guard's teeth: if a refactor ever swaps the default backend for a
    sandbox-capable one while the flag is off, minting the backend must raise
    instead of silently exposing ``execute``."""

    class _SandboxLookalike(workspace_module.BranchScratchBackend):
        """Default-backend subclass registered as a virtual SandboxBackendProtocol."""

    SandboxBackendProtocol.register(_SandboxLookalike)
    monkeypatch.setattr(workspace_module, "BranchScratchBackend", _SandboxLookalike)

    with pytest.raises(RuntimeError, match="SANDBOX_EXECUTION_ENABLED"):
        _build()


def test_the_guard_still_fires_when_the_flag_is_on_but_no_runner_is_set(monkeypatch):
    """Half-configured is off, and the guard holds that too."""

    class _SandboxLookalike(workspace_module.BranchScratchBackend):
        pass

    SandboxBackendProtocol.register(_SandboxLookalike)
    monkeypatch.setattr(workspace_module, "BranchScratchBackend", _SandboxLookalike)
    monkeypatch.setattr(settings.filesystem, "sandbox_execution_enabled", True)

    with pytest.raises(RuntimeError, match="SANDBOX_EXECUTION_ENABLED"):
        _build()


def test_a_runner_url_alone_does_not_switch_execution_on(monkeypatch):
    # The kill switch decides, not the presence of a URL.
    monkeypatch.setattr(settings.filesystem, "sandbox_runner_url", RUNNER_URL)
    assert settings.filesystem.sandbox_execution_active is False
    backend = _build()
    assert type(backend.default) is workspace_module.BranchScratchBackend
    assert not supports_execution(backend)


def test_the_flag_without_a_runner_url_stays_off(monkeypatch):
    monkeypatch.setattr(settings.filesystem, "sandbox_execution_enabled", True)
    monkeypatch.setattr(settings.filesystem, "sandbox_runner_url", "")
    assert settings.filesystem.sandbox_execution_active is False
    backend = _build()
    assert type(backend.default) is workspace_module.BranchScratchBackend
    assert not supports_execution(backend)


def test_execute_stays_a_reserved_locked_tool_name():
    """deepagents injects ``execute`` itself, but live MCP tools are
    name-filtered against the builtin roster: 'execute' must stay in it so an
    external tool cannot smuggle the name in."""
    assert "execute" in BUILTIN_BY_NAME
    assert BUILTIN_BY_NAME["execute"].locked


def test_a_gateway_tool_named_execute_is_dropped():
    class _Tool:
        def __init__(self, name):
            self.name = name

    kept = gates.strip_reserved_names([_Tool("execute"), _Tool("web_search")], agent_slug="a")
    assert [t.name for t in kept] == ["web_search"]


def test_the_write_deny_ladder_regressions():
    """input/ and the offload dirs must stay write-denied."""

    def has_write_deny(fragment: str) -> bool:
        return any(
            rule.mode == "deny"
            and "write" in rule.operations
            and any(fragment in p for p in rule.paths)
            for rule in workspace_module.WORKSPACE_WRITE_DENY
        )

    assert has_write_deny("/conversation/input")
    assert has_write_deny("/large_tool_results")
    assert has_write_deny("/conversation_history")


def test_enabled_makes_the_bound_sandbox_backend_the_default(monkeypatch):
    _enable(monkeypatch)
    backend = _build()
    default = backend.default

    assert isinstance(default, sandbox_module.RemoteSandboxBackend)
    assert isinstance(default, SandboxBackendProtocol)
    assert supports_execution(backend)
    # File operations are the branch scratch store's, as with execution off.
    assert isinstance(default, workspace_module.BranchScratchBackend)
    assert (default._client_id, default._agent_slug, default._conversation_id) == (
        CLIENT_ID,
        "agent-1",
        "conv-1",
    )


# ---------------------------------------------------------------------------
# The request: runner secret, pseudonymous identity
# ---------------------------------------------------------------------------
async def test_execute_carries_the_runner_secret_and_a_pseudonymous_client(monkeypatch):
    monkeypatch.setattr(
        settings.filesystem, "sandbox_runner_secret", SecretStr("runner-only-secret")
    )
    runner = _Runner(_ok(stdout="hello\n", stderr="warn\n", exit_code=0))

    result = await _backend(runner).aexecute("echo hello")

    [request] = runner.requests
    assert request.method == "POST"
    assert str(request.url) == f"{RUNNER_URL}/v1/exec"
    assert request.headers["X-Internal-Proxy-Secret"] == "runner-only-secret"
    # No identity headers: the runner learns who only from the body's pseudonym.
    assert "X-User-Id" not in request.headers
    assert "X-Client-Id" not in request.headers
    body = json.loads(request.content)
    pseudonym = hash_identifier(CLIENT_ID).removeprefix("h:")
    assert body == {
        "user_id": pseudonym,
        "agent_slug": "agent-1",
        "conversation_id": "conv-1",
        "command": "echo hello",
        "timeout_seconds": None,
        "workdir": "output",
    }
    # 16 hex: the runner's id pattern has no ':', and the raw id never leaves.
    assert re.fullmatch(r"[0-9a-f]{16}", body["user_id"])
    assert CLIENT_ID not in request.content.decode()
    assert result.exit_code == 0
    assert "hello" in result.output
    assert "[stderr]\nwarn" in result.output
    assert result.truncated is False


async def test_the_default_secret_is_the_configured_one():
    runner = _Runner()
    await _backend(runner).aexecute("true")
    expected = settings.filesystem.sandbox_runner_secret.get_secret_value()
    assert expected
    assert runner.requests[0].headers["X-Internal-Proxy-Secret"] == expected


def test_the_runner_secret_falls_back_to_the_internal_secret(monkeypatch):
    monkeypatch.delenv("SANDBOX_RUNNER_SECRET", raising=False)
    monkeypatch.delenv("SANDBOX_RUNNER_SECRET_FILE", raising=False)
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "shared-secret")
    assert FilesystemSettings().sandbox_runner_secret.get_secret_value() == "shared-secret"

    monkeypatch.setenv("SANDBOX_RUNNER_SECRET", "runner-secret")
    assert FilesystemSettings().sandbox_runner_secret.get_secret_value() == "runner-secret"


def test_the_sandbox_id_is_stable_and_carries_no_identity():
    first = _backend(_Runner())
    again = _backend(_Runner())
    other = _backend(_Runner(), conversation_id="conv-2")

    assert re.fullmatch(r"sandbox-[0-9a-f]{16}", first.id)
    assert first.id == again.id
    assert first.id != other.id
    assert CLIENT_ID not in first.id
    assert "conv-1" not in first.id


def test_the_sync_path_round_trips_too():
    runner = _Runner(_ok(exit_code=3, stdout="", stderr="boom"))
    result = _backend(runner).execute("false", timeout=30)
    assert runner.bodies()[0]["timeout_seconds"] == 30
    assert runner.requests[0].headers["X-Internal-Proxy-Secret"]
    assert result.exit_code == 3
    assert "boom" in result.output


async def test_a_zero_timeout_means_the_runners_default():
    runner = _Runner()
    await _backend(runner).aexecute("true", timeout=0)
    assert runner.bodies()[0]["timeout_seconds"] is None


# ---------------------------------------------------------------------------
# What the model reads back
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("reason", "words"),
    [
        ("timeout", "ran past its time limit"),
        ("memory", "ran out of memory"),
        ("output_limit", "more output than allowed"),
        ("disk_limit", "more to /conversation/output than allowed"),
        ("error", "sandbox failed while running it"),
    ],
)
async def test_a_killed_command_says_why_in_plain_words(reason, words):
    runner = _Runner(
        _ok(
            exit_code=None,
            stdout="partial",
            killed_reason=reason,
            truncated=reason == "output_limit",
        )
    )
    result = await _backend(runner).aexecute("run")
    assert words in result.output
    assert "partial" in result.output
    assert result.exit_code is None
    assert result.truncated is (reason == "output_limit")


async def test_runner_output_is_stripped_of_control_characters():
    runner = _Runner(_ok(stdout="ok\x1b[31mred\x00\r\nnext\x07"))
    result = await _backend(runner).aexecute("x")
    assert not any(c in result.output for c in ("\x1b", "\x00", "\x07", "\r"))
    assert "ok[31mred\nnext" in result.output


async def test_runner_output_is_capped(monkeypatch):
    monkeypatch.setattr(sandbox_module, "MAX_RESULT_CHARS", 10)
    result = await _backend(_Runner(_ok(stdout="x" * 50))).aexecute("x")
    assert result.truncated is True
    assert result.output.startswith("x" * 10)
    assert "x" * 11 not in result.output


@pytest.mark.parametrize(
    ("answer", "words"),
    [
        (httpx.ConnectError("refused"), "unreachable"),
        (httpx.ReadTimeout("slow"), "did not answer in time"),
        (httpx.Response(503, json={"detail": "runsc unusable"}), "unavailable"),
        (httpx.Response(500, text="oops"), "HTTP 500"),
        (httpx.Response(422, json={"detail": "bad"}), "rejected the request"),
        (httpx.Response(403, json={"detail": "Forbidden"}), "HTTP 403"),
        (httpx.Response(200, text="not json"), "unreadable"),
        (httpx.Response(200, json={"exit_code": "zero"}), "unreadable"),
    ],
)
async def test_a_runner_failure_is_an_error_result_never_a_raise(answer, words):
    runner = _Runner(answer)
    result = await _backend(runner).aexecute("echo hi")
    assert result.output.startswith("Error:")
    assert words in result.output
    assert result.exit_code is None
    assert len(runner.requests) == 1  # tried once, nowhere else


def test_the_sync_path_fails_closed_too():
    result = _backend(_Runner(httpx.ConnectError("refused"))).execute("echo hi")
    assert result.output.startswith("Error:")
    assert "unreachable" in result.output


async def test_a_command_the_runner_would_refuse_never_leaves_the_service():
    runner = _Runner()
    backend = _backend(runner)
    assert (await backend.aexecute("   ")).output.startswith("Error:")
    too_long = "x" * (sandbox_module.MAX_COMMAND_CHARS + 1)
    assert (await backend.aexecute(too_long)).output.startswith("Error:")
    assert runner.requests == []


@pytest.mark.parametrize(
    "identity",
    [
        {"client_id": "../other"},
        {"agent_slug": "a/b"},
        {"conversation_id": ""},
        {"conversation_id": ".hidden"},
        {"client_id": "spaces are bad"},
    ],
)
def test_an_identity_that_could_address_another_tree_is_refused(identity):
    with pytest.raises(ValueError, match="Invalid sandbox"):
        _backend(_Runner(), **identity)


def test_the_backend_refuses_to_exist_without_a_runner():
    with pytest.raises(RuntimeError, match="SANDBOX_RUNNER_URL"):
        sandbox_module.RemoteSandboxBackend(
            client_id=CLIENT_ID, agent_slug="a", conversation_id="c", runner_url=""
        )


def test_the_backend_needs_both_the_files_and_their_mount(conversation_files):
    with pytest.raises(ValueError, match="or neither"):
        sandbox_module.RemoteSandboxBackend(
            client_id=CLIENT_ID,
            agent_slug="assistant",
            conversation_id=CONVERSATION_ID,
            files=conversation_files,
            runner_url=RUNNER_URL,
        )


def test_the_backend_refuses_another_runs_files(conversation_files):
    mount = ConversationFilesBackend(conversation_files, "/conversation")
    with pytest.raises(ValueError, match="different run"):
        sandbox_module.RemoteSandboxBackend(
            client_id=CLIENT_ID,
            agent_slug="assistant",
            conversation_id="other-conv",
            files=conversation_files,
            conversation_mount=mount,
            runner_url=RUNNER_URL,
        )


async def test_a_runner_outage_does_not_fall_back_to_another_default(
    monkeypatch, conversation_files
):
    """Flag on + runner down fails the call loudly, and the next build still
    routes ``execute`` to the sandbox: there is no default it could quietly
    degrade to."""
    _enable(monkeypatch)
    runner = _Runner(httpx.ConnectError("refused"))
    _wire_runner(monkeypatch, runner)

    first = _build(conversation_files, agent_slug="assistant")
    result = await first.aexecute("echo hi")
    again = _build(conversation_files, agent_slug="assistant")

    assert result.output.startswith("Error:")
    assert "unreachable" in result.output
    assert isinstance(again.default, sandbox_module.RemoteSandboxBackend)
    assert supports_execution(again)
    assert len(runner.requests) == 1


# ---------------------------------------------------------------------------
# Approval is platform-forced
# ---------------------------------------------------------------------------
def test_the_merge_forces_the_execute_gate_even_if_the_roster_drops_its_lock(monkeypatch):
    monkeypatch.setattr(gates, "locked_gates", dict)
    resolved = gates.resolve_interrupt_on({"execute": False})
    assert resolved["execute"] is True


def test_a_definition_cannot_clear_the_execute_gate():
    resolved = gates.resolve_interrupt_on({"execute": False, "write_file": False})
    assert resolved["execute"] is True
    assert resolved["write_file"] is False


def _definition(**overrides) -> dict:
    spec = {
        "id": "probe-v1",
        "slug": "probe",
        "name": "Probe",
        "version": "1.0.0",
        "type": "deep_agent",
        "prompt": "./AGENT.md",
        "model": {"main": PROBE_MODEL},
    }
    spec.update(overrides)
    return spec


def test_the_spec_loader_refuses_execute_false():
    """A cleared execute gate is refused at load time, not silently overridden."""
    spec = AgentSpec.model_validate(_definition(hitl={"execute": False}))
    errors = spec.reference_errors(
        is_known_model=lambda _m: True, is_known_native_tool=lambda _t: True
    )
    assert any("hitl.execute" in e and "cannot be set to false" in e for e in errors)


def test_the_spec_loader_accepts_execute_true():
    spec = AgentSpec.model_validate(_definition(hitl={"execute": True}))
    errors = spec.reference_errors(
        is_known_model=lambda _m: True, is_known_native_tool=lambda _t: True
    )
    assert not [e for e in errors if "hitl" in e]


# ---------------------------------------------------------------------------
# End to end: a real deep agent graph, a scripted model, a mocked runner
# ---------------------------------------------------------------------------
def _exec(call_id: str, command: str) -> dict:
    return {"id": call_id, "name": "execute", "args": {"command": command}}


def _task(call_id: str, subagent: str) -> dict:
    return {
        "id": call_id,
        "name": "task",
        "args": {"subagent_type": subagent, "description": "Do it."},
    }


def _tool_name(tool) -> str | None:
    return tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)


class _Scripted(FakeMessagesListChatModel):
    """Every agent's model, answering by the role its system prompt opens
    with, and recording the tool names each call was offered."""

    responses: list = Field(default_factory=list)
    model_name: str = "scripted-probe"
    scripts: dict = Field(default_factory=dict)
    cursor: dict = Field(default_factory=dict)
    offered: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.offered.append({_tool_name(t) for t in tools})
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = messages[0].text if messages else ""
        role = next((r for r in self.scripts if system.startswith(r)), None)
        if role is None:
            raise AssertionError(f"no script for system prompt: {system[:80]!r}")
        index = self.cursor.get(role, 0)
        self.cursor[role] = index + 1
        text, calls = self.scripts[role][min(index, len(self.scripts[role]) - 1)]
        message = AIMessage(
            id=f"msg-{role[-8:].strip()}-{index}",
            content=text,
            tool_calls=[{**call, "type": "tool_call"} for call in calls],
            usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
            response_metadata={"model_name": "scripted-probe"},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, *args, **kwargs):
        return self._generate(*args, **kwargs)


@pytest.fixture
def probe(monkeypatch, memory_file_store):
    """A real deep agent whose own gates try to switch execute approval off.
    Returns ``make(scripts, nested=False) -> (agent, model)``."""

    def _make(scripts: dict, *, nested: bool = False):
        model = _Scripted(scripts=scripts)
        monkeypatch.setattr(deepagents_models, "init_chat_model", lambda *a, **k: model)

        class Probe(DeepAgent):
            name = "sandbox-probe"
            instructions = "You are the probe main."

            def register_subagents(self):
                if not nested:
                    return None
                return [
                    subagent_tree.subagent(
                        "researcher",
                        "Researches.",
                        "You are the probe researcher.",
                        subagents=[
                            subagent_tree.subagent(
                                "coder",
                                "Codes.",
                                "You are the probe coder.",
                                interrupt_on={"execute": False},
                            )
                        ],
                    )
                ]

            def register_agent(self):
                return self.build_deep_agent(
                    model=PROBE_MODEL,
                    system_prompt=self.instructions,
                    subagents=self.sub_agents,
                    interrupt_on={"execute": False},
                    middleware=[],
                )

        agent = Probe(
            config={
                "context": {
                    "client_id": CLIENT_ID,
                    "conversation_id": CONVERSATION_ID,
                    "run_id": "run-1",
                },
                "run_config": {
                    "configurable": {"thread_id": "probe-thread"},
                    "recursion_limit": 100,
                },
            }
        )
        agent.checkpointer = MemorySaver()
        # The run's conversation files over the in-memory store.
        agent._conversation_files = ConversationFiles(
            client_id=CLIENT_ID,
            conversation_id=CONVERSATION_ID,
            agent_slug="sandbox-probe",
            store=memory_file_store,
            run_id="run-1",
        )
        return agent, model

    return _make


async def _drive(agent, *, on_pause, max_legs: int = 8) -> list[list[str]]:
    """Run until the graph finishes, calling ``on_pause(names)`` and then
    approving at every interrupt. Returns the tool names of each pause."""
    await agent.ensure_built()
    graph, config = agent.compiled, agent.run_config
    pauses: list[list[str]] = []
    payload: object = {"messages": [{"role": "user", "content": "Go."}]}
    for _ in range(max_legs):
        await graph.ainvoke(payload, config=config)
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            return pauses
        requests = (snapshot.interrupts[0].value or {}).get("action_requests") or []
        names = [r.get("name") for r in requests]
        pauses.append(names)
        on_pause(names)
        payload = Command(resume={"decisions": [{"type": "approve"}] * max(len(requests), 1)})
    raise AssertionError(f"run did not finish: {pauses}")


async def _messages(agent) -> list:
    return (await agent.compiled.aget_state(agent.run_config)).values["messages"]


async def test_flag_off_the_model_is_never_offered_execute(probe):
    agent, model = probe({"You are the probe main": [("Done.", [])]})
    await _drive(agent, on_pause=lambda _n: None)
    assert model.offered
    assert all("execute" not in names for names in model.offered)


async def test_execute_pauses_at_the_main_agent_then_round_trips(probe, monkeypatch):
    _enable(monkeypatch)
    runner = _Runner(_ok(stdout="hi from the box\n"))
    _wire_runner(monkeypatch, runner)
    agent, model = probe(
        {"You are the probe main": [("", [_exec("call-1", "echo hi")]), ("Done.", [])]}
    )

    def before_approval(names):
        # The pause comes BEFORE anything reaches the runner.
        assert names == ["execute"]
        assert runner.requests == []

    pauses = await _drive(agent, on_pause=before_approval)

    assert pauses == [["execute"]]
    assert any("execute" in names for names in model.offered)
    [body] = runner.bodies()
    assert (body["user_id"], body["agent_slug"], body["conversation_id"], body["command"]) == (
        hash_identifier(CLIENT_ID).removeprefix("h:"),
        "sandbox-probe",
        CONVERSATION_ID,
        "echo hi",
    )
    [result] = [
        m for m in await _messages(agent) if isinstance(m, ToolMessage) and m.name == "execute"
    ]
    assert "hi from the box" in result.content
    assert "exit code 0" in result.content


async def test_a_denied_command_never_reaches_the_runner(probe, monkeypatch):
    _enable(monkeypatch)
    runner = _Runner()
    _wire_runner(monkeypatch, runner)
    agent, _model = probe(
        {
            "You are the probe main": [
                ("", [_exec("call-1", "rm -rf /conversation/output")]),
                ("Ok.", []),
            ]
        }
    )
    await agent.ensure_built()
    graph, config = agent.compiled, agent.run_config

    await graph.ainvoke({"messages": [{"role": "user", "content": "Go."}]}, config=config)
    assert (await graph.aget_state(config)).interrupts
    await graph.ainvoke(
        Command(resume={"decisions": [{"type": "reject", "message": "No."}]}), config=config
    )
    snapshot = await graph.aget_state(config)

    assert not snapshot.interrupts
    assert runner.requests == []
    assert snapshot.values["messages"][-1].content == "Ok."  # the run continued


async def test_a_runner_outage_is_an_error_result_and_the_run_continues(probe, monkeypatch):
    _enable(monkeypatch)
    runner = _Runner(httpx.ConnectError("refused"))
    _wire_runner(monkeypatch, runner)
    agent, _model = probe(
        {"You are the probe main": [("", [_exec("call-1", "echo hi")]), ("Sorry.", [])]}
    )

    await _drive(agent, on_pause=lambda _n: None)

    messages = await _messages(agent)
    [result] = [m for m in messages if isinstance(m, ToolMessage) and m.name == "execute"]
    assert result.content.startswith("Error:")
    assert "unreachable" in result.content
    assert messages[-1].content == "Sorry."
    assert len(runner.requests) == 1


async def test_execute_pauses_two_levels_down_although_the_spec_says_false(probe, monkeypatch):
    _enable(monkeypatch)
    # Nested delegation here is the blocking `task` path.
    monkeypatch.setattr(settings.async_tasks, "enabled", False)
    runner = _Runner(_ok(stdout="nested ok\n"))
    _wire_runner(monkeypatch, runner)
    agent, _model = probe(
        {
            "You are the probe main": [("", [_task("call-r", "researcher")]), ("Done.", [])],
            "You are the probe researcher": [
                ("", [_task("call-c", "coder")]),
                ("Researched.", []),
            ],
            "You are the probe coder": [
                ("", [_exec("call-x", "python -c 'print(1)'")]),
                ("Coded.", []),
            ],
        },
        nested=True,
    )

    def check(names):
        if "execute" in names:
            assert runner.requests == [], "execute reached the runner before approval"

    pauses = await _drive(agent, on_pause=check)

    assert ["execute"] in pauses, pauses
    [body] = runner.bodies()
    assert body["command"] == "python -c 'print(1)'"
    assert body["conversation_id"] == CONVERSATION_ID


# ---------------------------------------------------------------------------
# The files travel with the call (rows <-> the request/response)
# ---------------------------------------------------------------------------
PNG = b"\x89PNG\r\n\x1a\n\x00\xff\xfe binary"
XLSX = b"PK\x03\x04\x00\x00\xde\xad\xbe\xef" * 300


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _returned(path: str, data: bytes) -> dict:
    return {"path": path, "content_b64": _b64(data), "size": len(data)}


@pytest.fixture
def wired(monkeypatch, conversation_files, memory_file_store):
    """Execution on, a scripted runner, and this run's composite backend over
    the in-memory conversation store. Returns ``make(*answers, uploads=)``
    -> ``(composite, runner)``."""
    _enable(monkeypatch)

    async def make(*answers, uploads: dict[str, bytes] | None = None):
        for name, data in (uploads or {}).items():
            await memory_file_store.replace(
                CLIENT_ID,
                CONVERSATION_ID,
                f"/conversation/input/{name}",
                data,
                agent_slug=UPLOAD_WRITER,
            )
        runner = _Runner(*answers)
        _wire_runner(monkeypatch, runner)
        return _build(conversation_files, agent_slug="assistant"), runner

    return make


async def test_inputs_and_outputs_are_sent_text_and_binary(wired, conversation_files):
    await conversation_files.create("/conversation/output/draft.md", b"# draft\n")
    composite, runner = await wired(_ok(), uploads={"data.csv": b"a,b\n1,2\n", "photo.png": PNG})

    await composite.aexecute("ls")

    [body] = runner.bodies()
    sent = {f["path"]: base64.b64decode(f["content_b64"]) for f in body["files"]}
    assert sent == {
        "input/data.csv": b"a,b\n1,2\n",
        "input/photo.png": PNG,
        "output/draft.md": b"# draft\n",
    }
    # Identity still comes from the run, never from a path.
    assert (body["agent_slug"], body["conversation_id"]) == ("assistant", CONVERSATION_ID)


async def test_scratch_and_offloads_never_travel(wired, conversation_files):
    await conversation_files.create("/conversation/notes.md", b"working notes")
    await conversation_files.create("/large_tool_results/call-1", b"offload")
    composite, runner = await wired(_ok())

    await composite.aexecute("ls")

    assert runner.bodies()[0]["files"] == []


async def test_returned_outputs_land_in_conversation_output_and_read_back(
    wired, conversation_files
):
    await conversation_files.create("/conversation/output/notes.md", b"old")
    composite, _runner = await wired(
        _ok(
            stdout="done\n",
            files=[
                _returned("output/report.xlsx", XLSX),
                _returned("output/charts/plot.png", PNG),
                _returned("output/notes.md", b"new notes"),
            ],
        )
    )

    result = await composite.aexecute("python make_report.py")

    read = conversation_files.read_bytes
    assert await read("/conversation/output/report.xlsx") == XLSX
    assert await read("/conversation/output/charts/plot.png") == PNG
    assert await read("/conversation/output/notes.md") == b"new notes"  # replaced
    # Readable afterwards through the agent's own mount, as read_file sees it.
    [download] = await composite.adownload_files(["/conversation/output/report.xlsx"])
    assert download.error is None
    assert download.content == XLSX
    assert "done" in result.output
    assert "Wrote /conversation/output/report.xlsx (" in result.output
    assert "/conversation/output/charts/plot.png" in result.output


async def test_a_returned_file_outside_output_is_never_written(wired, conversation_files):
    composite, _runner = await wired(
        _ok(
            files=[
                _returned("input/data.csv", b"overwrite the upload"),
                _returned("output/../../conversation_history/x.md", b"escape"),
                _returned("/conversation/output/abs.md", b"absolute"),
                _returned("output/.hidden", b"hidden"),
                {"path": "output/bad.bin", "content_b64": "%%% not base64 %%%", "size": 3},
                _returned("output/ok.txt", b"fine"),
            ]
        ),
        uploads={"data.csv": b"the original"},
    )

    result = await composite.aexecute("x")

    entries = await conversation_files.entries("/")
    assert [e.path for e in entries] == [
        "/conversation/input/data.csv",
        "/conversation/output/ok.txt",
    ]
    assert await conversation_files.read_bytes("/conversation/input/data.csv") == b"the original"
    assert "Ignored returned files outside output/" in result.output


@pytest.mark.parametrize(
    "answer",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(503),
        httpx.Response(500),
        httpx.Response(200, text="garbage"),
    ],
)
async def test_a_failed_call_writes_nothing(wired, conversation_files, answer):
    composite, runner = await wired(answer)
    result = await composite.aexecute("x")
    assert result.output.startswith("Error:")
    assert await conversation_files.entries("/conversation/output") == []
    assert len(runner.requests) == 1


async def test_a_disk_limit_kill_saves_no_outputs(wired, conversation_files):
    composite, _runner = await wired(
        _ok(exit_code=None, killed_reason="disk_limit", files=[_returned("output/huge.bin", b"x")])
    )
    result = await composite.aexecute("x")
    assert await conversation_files.entries("/conversation/output") == []
    assert "not saved" in result.output


async def test_the_send_caps_skip_files_and_say_so(wired, conversation_files, monkeypatch):
    monkeypatch.setattr(sandbox_module, "MAX_TRANSFER_FILES", 2)
    for name in ("a.txt", "b.txt", "c.txt"):
        await conversation_files.create(f"/conversation/output/{name}", b"x")
    composite, runner = await wired(_ok())

    result = await composite.aexecute("x")

    assert [f["path"] for f in runner.bodies()[0]["files"]] == ["output/a.txt", "output/b.txt"]
    assert "Not copied into the sandbox" in result.output
    assert "output/c.txt" in result.output


async def test_the_byte_cap_skips_a_file_that_would_cross_it(
    wired, conversation_files, monkeypatch
):
    monkeypatch.setattr(sandbox_module, "MAX_TRANSFER_BYTES", 10)
    await conversation_files.create("/conversation/output/big.bin", b"x" * 11)
    await conversation_files.create("/conversation/output/small.txt", b"y")
    composite, runner = await wired(_ok())

    result = await composite.aexecute("x")

    assert [f["path"] for f in runner.bodies()[0]["files"]] == ["output/small.txt"]
    assert "output/big.bin" in result.output


async def test_the_return_caps_hold_too(wired, conversation_files, monkeypatch):
    monkeypatch.setattr(sandbox_module, "MAX_TRANSFER_FILES", 1)
    composite, _runner = await wired(
        _ok(
            files_truncated=True,
            files=[_returned("output/one.txt", b"1"), _returned("output/two.txt", b"2")],
        )
    )
    result = await composite.aexecute("x")
    assert [e.path for e in await conversation_files.entries("/conversation/output")] == [
        "/conversation/output/one.txt"
    ]
    assert "Not every changed output file came back" in result.output


class _ExplodingStore:
    """Any file IO at all fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"file IO ({name}) while it must not happen")


@pytest.mark.parametrize("enabled", [False, True])
def test_minting_the_workspace_does_no_file_io(monkeypatch, enabled):
    """Flag off there is no sandbox backend to read anything; flag on it reads
    nothing until ``execute`` is called."""
    if enabled:
        _enable(monkeypatch)
    files = ConversationFiles(
        client_id=CLIENT_ID,
        conversation_id="conv-1",
        agent_slug="agent-1",
        store=_ExplodingStore(),
    )
    backend = _build(files)
    assert supports_execution(backend) is enabled
