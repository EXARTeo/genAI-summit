"""The service's helpers: MCP tool keys and the optional gateway session, prompt and
manifest helpers for declarative agents, the agent registry, and the path guard.

The registry is driven over throwaway ``tmp_path`` agent folders, so each
loader rule (structure, references, locked gates, folder = slug) is pinned
without touching the shipped ``agents_seed/``. The MCP session is driven with
a stubbed SSE client and ``ClientSession``: no network.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from conftest import run_config

from core.settings import settings
from harness.abstractions import AgentSpec, YamlDeepAgent
from harness.abstractions.base_agent import BaseAgent
from harness.filesystem import layout
from utils import agents as agents_util
from utils import mcp_tools
from utils.declarative import manifest_from_spec, read_prompt


def _spec_dict(slug: str = "probe", **overrides: Any) -> dict[str, Any]:
    return {
        "id": slug,
        "slug": slug,
        "name": slug.title(),
        "version": "1.0.0",
        "type": "deep_agent",
        "description": "A probe agent",
        "icon": "Bot",
        "prompt": "./AGENT.md",
        "model": {"main": "openai:gpt-4o"},
        **overrides,
    }


def _write_agent(root: Path, folder: str, spec: dict[str, Any] | str) -> Path:
    agent_dir = root / folder
    agent_dir.mkdir(parents=True)
    text = spec if isinstance(spec, str) else yaml.safe_dump(spec)
    (agent_dir / "agent.yaml").write_text(text, encoding="utf-8")
    (agent_dir / "AGENT.md").write_text("You are a probe.", encoding="utf-8")
    return agent_dir


class _FakeTool:
    def __init__(self, name: Any) -> None:
        self.name = name


# ===========================================================================
# utils/mcp_tools.py: tool keys
# ===========================================================================
def test_build_tool_cache_key_with_and_without_server():
    assert mcp_tools.build_tool_cache_key("arxiv", "read_paper") == "arxiv/read_paper"
    assert mcp_tools.build_tool_cache_key("", "loose-tool") == "loose-tool"
    assert mcp_tools.build_tool_cache_key("  ", "  bare  ") == "bare"
    assert mcp_tools.build_tool_cache_key(" tavily ", " tavily-map ") == "tavily/tavily-map"


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("tavily-search", "tavily/tavily-search"),
        ("download_paper", "arxiv/download_paper"),
        # The server is looked up case-insensitively; the name is kept as served.
        ("TAVILY-MAP", "tavily/TAVILY-MAP"),
        ("unknown-tool", "unknown-tool"),
        (12345, "12345"),
        (None, ""),
    ],
)
def test_get_tool_cache_key_infers_the_server(name, key):
    assert mcp_tools.get_tool_cache_key(_FakeTool(name)) == key


def test_a_tool_without_a_name_has_an_empty_key():
    assert mcp_tools.get_tool_cache_key(object()) == ""


# ===========================================================================
# utils/mcp_tools.py: the optional session
# ===========================================================================
class _FakeSession:
    def __init__(self, *, fail_initialize: bool = False) -> None:
        self.initialized = False
        self._fail = fail_initialize

    async def initialize(self) -> None:
        if self._fail:
            raise ConnectionError("handshake failed")
        self.initialized = True


@pytest.fixture
def gateway(monkeypatch):
    """A configured gateway served by stubs; returns what the stubs saw."""
    settings.mcp.mcp_gateway_url = "http://gateway.test:8005/sse"
    seen: dict[str, Any] = {"session": _FakeSession()}

    @asynccontextmanager
    async def fake_sse_client(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        yield ("read", "write")

    @asynccontextmanager
    async def fake_client_session(read_stream, write_stream):
        assert (read_stream, write_stream) == ("read", "write")
        yield seen["session"]

    monkeypatch.setattr(mcp_tools, "sse_client", fake_sse_client)
    monkeypatch.setattr(mcp_tools, "mcp", SimpleNamespace(ClientSession=fake_client_session))
    return seen


async def test_optional_session_unconfigured_yields_none():
    assert settings.mcp.enabled is False
    async with mcp_tools.optional_mcp_session() as session:
        assert session is None


async def test_optional_session_yields_an_initialized_session(gateway):
    async with mcp_tools.optional_mcp_session() as session:
        assert session is gateway["session"]
        assert session.initialized is True
    assert gateway["url"] == "http://gateway.test:8005/sse"
    # The shared connect deadline, not an open-ended wait.
    assert gateway["timeout"] == settings.mcp.connect_timeout_seconds


async def test_a_failed_handshake_degrades_to_no_session(gateway):
    gateway["session"] = _FakeSession(fail_initialize=True)
    async with mcp_tools.optional_mcp_session() as session:
        assert session is None


async def test_an_unreachable_gateway_degrades_to_no_session(monkeypatch):
    settings.mcp.mcp_gateway_url = "http://gateway.test:8005/sse"

    @asynccontextmanager
    async def boom_sse_client(url, timeout):
        raise ConnectionError("gateway down")
        yield  # pragma: no cover

    monkeypatch.setattr(mcp_tools, "sse_client", boom_sse_client)
    async with mcp_tools.optional_mcp_session() as session:
        assert session is None


async def test_the_callers_own_error_is_not_mistaken_for_an_outage(gateway):
    # Work inside a live session failing is the caller's error, raised as is.
    with pytest.raises(ValueError, match="caller"):
        async with mcp_tools.optional_mcp_session() as session:
            assert session is not None
            raise ValueError("caller failed")


# ===========================================================================
# utils/declarative.py
# ===========================================================================
def test_read_prompt_inline_string_passes_through(tmp_path):
    assert read_prompt("You are helpful.", tmp_path) == "You are helpful."


def test_read_prompt_reads_a_file_in_the_agent_folder(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "p.md").write_text("from file", encoding="utf-8")
    assert read_prompt("./sub/p.md", tmp_path) == "from file"
    assert read_prompt("sub/p.md", tmp_path) == "from file"


def test_read_prompt_refuses_a_path_outside_the_agent_folder(tmp_path):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (tmp_path / "secret.md").write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        read_prompt("../secret.md", agent_dir)


def test_manifest_from_spec_normalises_the_type():
    spec = AgentSpec.model_validate(_spec_dict())
    assert manifest_from_spec(spec) == {
        "id": "probe",
        "slug": "probe",
        "name": "Probe",
        "version": "1.0.0",
        "type": "deep agent",
        "description": "A probe agent",
        "icon": "Bot",
    }


# ===========================================================================
# harness/filesystem/layout.py
# ===========================================================================
@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", "..", "x..y", ".hidden"])
def test_safe_segment_refuses_path_breakouts(bad):
    with pytest.raises(ValueError):
        layout.safe_segment(bad)


def test_agent_dir_is_under_the_agents_root(tmp_path):
    settings.registry.agents_dir = tmp_path
    assert layout.agents_root() == tmp_path
    assert layout.agent_dir("assistant") == tmp_path / "assistant"
    with pytest.raises(ValueError):
        layout.agent_dir("../etc")


# ===========================================================================
# utils/agents.py: the registry
# ===========================================================================
def test_a_valid_folder_registers(tmp_path):
    agent_dir = _write_agent(tmp_path, "probe", _spec_dict())
    registry = agents_util.build_registry(tmp_path)

    assert set(registry) == {"probe"}
    definition = registry["probe"]
    assert definition.slug == "probe"
    assert definition.spec.slug == "probe"
    assert definition.manifest["type"] == "deep agent"
    agent = definition.build(run_config())
    assert isinstance(agent, YamlDeepAgent)
    assert agent.name == "probe"
    assert agent.instructions == "You are a probe."
    assert agent.reference_dir == agent_dir


@pytest.mark.parametrize(
    ("folder", "spec"),
    [
        # Folder name and slug must agree (the folder is mounted by slug).
        ("other-name", _spec_dict()),
        # Structure: unknown key, bad slug.
        ("probe", _spec_dict(memory=True)),
        ("Bad_Slug", _spec_dict(slug="Bad_Slug")),
        # References: a model id without a provider, an unknown native tool.
        ("probe", _spec_dict(model={"main": "gpt-4o"})),
        ("probe", _spec_dict(tools=[{"native": "no_such_tool"}])),
        # A locked gate cannot be cleared from YAML.
        ("probe", _spec_dict(hitl={"execute": False})),
        # Not YAML at all.
        ("probe", "id: [unclosed"),
    ],
)
def test_an_invalid_folder_is_skipped(tmp_path, folder, spec):
    _write_agent(tmp_path, folder, spec)
    assert agents_util.build_registry(tmp_path) == {}


def test_one_bad_folder_does_not_take_the_others_down(tmp_path):
    _write_agent(tmp_path, "alpha", _spec_dict("alpha"))
    _write_agent(tmp_path, "beta", _spec_dict("beta", hitl={"execute": False}))
    _write_agent(tmp_path, "gamma", _spec_dict("gamma"))
    (tmp_path / "notes").mkdir()  # no agent.yaml: ignored
    assert sorted(agents_util.build_registry(tmp_path)) == ["alpha", "gamma"]


def test_a_missing_agents_folder_is_an_empty_registry(tmp_path):
    assert agents_util.build_registry(tmp_path / "missing") == {}


class _CodeAgent(BaseAgent):
    name = "probe"
    agent_id = "probe-code"
    label = "Code probe"


class _OtherCodeAgent(BaseAgent):
    name = "coded"
    label = "Coded"


def test_python_agents_register_and_yaml_wins_a_clash(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_util, "PYTHON_AGENTS", (_CodeAgent, _OtherCodeAgent))
    _write_agent(tmp_path, "probe", _spec_dict())
    registry = agents_util.build_registry(tmp_path)

    assert sorted(registry) == ["coded", "probe"]
    assert registry["probe"].spec is not None  # the YAML one
    assert registry["coded"].spec is None
    assert registry["coded"].manifest["name"] == "Coded"
    assert isinstance(registry["coded"].build(None), _OtherCodeAgent)


def test_resolve_agent_definition(monkeypatch, tmp_path):
    _write_agent(tmp_path, "probe", _spec_dict())
    monkeypatch.setattr(agents_util, "AGENT_REGISTRY", agents_util.build_registry(tmp_path))
    assert agents_util.resolve_agent_definition("probe").slug == "probe"
    assert agents_util.resolve_agent_definition("missing") is None


async def test_definition_candidates_are_the_current_definition(monkeypatch, tmp_path):
    _write_agent(tmp_path, "probe", _spec_dict())
    monkeypatch.setattr(agents_util, "AGENT_REGISTRY", agents_util.build_registry(tmp_path))

    found = [d.slug async for d in agents_util.definition_candidates("probe")]
    missing = [d async for d in agents_util.definition_candidates("missing")]
    assert found == ["probe"]
    assert missing == []


def test_list_agent_manifests_is_sorted_with_the_default_marked(monkeypatch, tmp_path):
    for slug in ("zeta", "alpha", "mid"):
        _write_agent(tmp_path, slug, _spec_dict(slug))
    monkeypatch.setattr(agents_util, "AGENT_REGISTRY", agents_util.build_registry(tmp_path))
    settings.registry.default_agent_slug = "mid"

    manifests = agents_util.list_agent_manifests()

    assert [m.name for m in manifests] == ["Alpha", "Mid", "Zeta"]
    assert [m.slug for m in manifests if m.default] == ["mid"]


def test_an_unknown_default_marks_nothing(monkeypatch, tmp_path):
    _write_agent(tmp_path, "probe", _spec_dict())
    monkeypatch.setattr(agents_util, "AGENT_REGISTRY", agents_util.build_registry(tmp_path))
    settings.registry.default_agent_slug = "absent"
    assert [m.default for m in agents_util.list_agent_manifests()] == [False]


def test_the_fingerprint_follows_the_definition(tmp_path):
    first = _write_agent(tmp_path / "a", "probe", _spec_dict())
    second = _write_agent(tmp_path / "b", "probe", _spec_dict(version="1.0.1"))
    spec_a = AgentSpec.model_validate(_spec_dict())
    spec_b = AgentSpec.model_validate(_spec_dict(version="1.0.1"))

    same = YamlDeepAgent(spec_a, first).definition_fingerprint()
    assert same == YamlDeepAgent(spec_a, first).definition_fingerprint()
    assert same != YamlDeepAgent(spec_b, second).definition_fingerprint()

    # A prompt edit changes what runs, so it changes the fingerprint too.
    (first / "AGENT.md").write_text("You are a changed probe.", encoding="utf-8")
    assert same != YamlDeepAgent(spec_a, first).definition_fingerprint()
    assert len(same) == 16
