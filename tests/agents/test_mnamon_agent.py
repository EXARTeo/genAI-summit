"""The chat copilot the image ships, ``mnamon/agents/definitions/mnamon/`` (Mnamon Copilot).

* the definition loads and validates through the real registry scan;
* it is the default agent everywhere the default is configured, and a chat agent,
  while ``audit-pipeline`` is listed as a ``workflow`` (the UI hides it from chat);
* its product-API tools are bound to the run's client and scope, and the writes
  are gated and land as ``proposed``;
* a fake-LLM (``AGENTS_FAKE_LLM``) stream through ``/agents/mnamon/stream``
  completes, unscoped and scoped to a system, with no network.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import route_fakes
from conftest import CLIENT_ID, SERVICE_ROOT, run_config
from langgraph.checkpoint.memory import MemorySaver

from core.settings import settings
from harness.checkpointer.store import set_checkpointer
from harness.models.fake import DRY_RUN_NOTE
from harness.tools import builtins
from harness.tools.workspace_api import WorkspaceAPI, WorkspaceScope, build_workspace_tool
from harness.tools.workspace_api import client as workspace_client
from utils import agents as agents_module
from utils import inference
from utils.agents import build_registry, list_agent_manifests

REPO_ROOT = SERVICE_ROOT.parents[1]
DEFINITIONS = SERVICE_ROOT / "definitions"
SLUG = "mnamon"


@pytest.fixture
def shipped():
    """The shipped definitions, scanned the way the service scans them at boot."""
    return build_registry(DEFINITIONS)


@pytest.fixture
def with_copilot(monkeypatch, shipped):
    """The suite's registry (fixture agents) plus the shipped copilot, as the default."""
    monkeypatch.setitem(agents_module.AGENT_REGISTRY, SLUG, shipped[SLUG])
    monkeypatch.setattr(settings.registry, "default_agent_slug", SLUG)
    return shipped[SLUG]


# ---------------------------------------------------------------------------
# The definition
# ---------------------------------------------------------------------------
def test_the_definition_loads_and_validates(shipped):
    assert set(shipped) == {SLUG, "audit-pipeline"}
    spec = shipped[SLUG].spec
    assert spec is not None
    assert spec.name == "Mnamon Copilot"
    assert spec.model.main == "google_genai:${GEMINI_MODEL}"
    assert [sa.name for sa in spec.subagents] == ["regulation-researcher", "evidence-analyst"]
    natives = {t.native for t in spec.tools}
    assert {"list_systems", "read_audit", "lookup_provision", "propose_system_note"} <= natives
    # The writes ask first; delegation to the read-only sub-agents does not.
    assert spec.hitl["propose_system_note"] is True
    assert spec.hitl["start_audit"] is True
    assert spec.hitl["execute"] is True
    assert spec.hitl["task"] is False


def test_the_prompt_is_layered_short_and_states_its_precedence():
    text = (DEFINITIONS / SLUG / "AGENT.md").read_text(encoding="utf-8")
    assert text.index("<platform_rules>") < text.index("<agent_instructions>")
    assert "where they differ from the platform defaults" in text
    assert "kb_version" in text and "not the AI Act's" in text and "legal certainty" in text
    assert len(text.split()) < 650


def test_the_model_follows_gemini_model(with_copilot, monkeypatch):
    monkeypatch.setattr(settings.gemini, "model", "gemini-test-model")
    agent = with_copilot.build(run_config())
    assert agent._main_model() == "google_genai:gemini-test-model"


# ---------------------------------------------------------------------------
# Catalog: default, chat, workflow
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        (".env.example", r"^DEFAULT_AGENT_SLUG=mnamon\b"),
        ("mnamon/docker-compose.yaml", r"DEFAULT_AGENT_SLUG: \$\{DEFAULT_AGENT_SLUG:-mnamon\}"),
        (
            "deploy/denis/docker-compose-denis.yaml",
            r"DEFAULT_AGENT_SLUG: \$\{DEFAULT_AGENT_SLUG:-mnamon\}",
        ),
    ],
)
def test_the_copilot_is_the_configured_default(path, pattern):
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    assert re.search(pattern, text, re.MULTILINE)


def test_the_copilot_is_the_default_chat_agent_and_the_pipeline_a_workflow(with_copilot):
    manifests = {m.slug: m for m in list_agent_manifests()}
    assert manifests[SLUG].default is True
    assert manifests[SLUG].kind == "chat"
    assert manifests["audit-pipeline"].kind == "workflow"
    assert manifests["audit-pipeline"].default is False


async def test_get_agents_flags_the_pipeline_as_not_a_chat_agent(
    client, internal_headers, with_copilot
):
    response = await client.get("/agents", headers=internal_headers)
    assert response.status_code == 200
    by_slug = {item["slug"]: item for item in response.json()}
    assert by_slug[SLUG]["kind"] == "chat" and by_slug[SLUG]["default"] is True
    assert by_slug["audit-pipeline"]["kind"] == "workflow"
    chat = [item["slug"] for item in response.json() if item["kind"] == "chat"]
    assert "audit-pipeline" not in chat


# ---------------------------------------------------------------------------
# The product-API tools
# ---------------------------------------------------------------------------
class _Backend:
    """A mock backend + reg-memory: records each request and answers canned bodies."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/systems":
            return httpx.Response(200, json=[{"id": "SYS-001", "name": "CV Screener", "data": {}}])
        if path.endswith("/files") and path.startswith("/v1/systems/"):
            return httpx.Response(200, json=[{"path": "system-card.yaml", "version": 2}])
        if path.startswith("/v1/systems/") and request.method == "PUT":
            return httpx.Response(201, json={"file": {"version": 1}, "changed": True})
        if path.startswith("/v1/systems/") and "/files/" in path:
            return httpx.Response(200, json={"text": "id: SYS-001\n"})
        if path == "/v1/releases":
            return httpx.Response(200, json={"active": "kb-2026-11-14"})
        if path.startswith("/v1/provisions/"):
            return httpx.Response(200, json={"id": "AIA.10.2.f", "title": "Bias", "text": "..."})
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def backend(monkeypatch) -> _Backend:
    fake = _Backend()
    monkeypatch.setattr(workspace_client, "transport", httpx.MockTransport(fake))
    return fake


def _tool(name: str, **scope):
    bound = WorkspaceScope(client_id=CLIENT_ID, agent_slug=SLUG, **scope)
    api = WorkspaceAPI(client_id=CLIENT_ID, agent_slug=SLUG)
    return build_workspace_tool(name, bound, api)


async def test_the_tools_default_to_the_scope_and_carry_the_client_id(backend):
    result = await _tool("list_system_files", system_id="SYS-001").ainvoke({})
    assert "system-card.yaml (v2)" in result
    request = backend.requests[-1]
    assert request.url.path == "/v1/systems/SYS-001/files"
    assert request.headers["X-Client-Id"] == CLIENT_ID


async def test_an_unscoped_tool_without_a_system_asks_for_one(backend):
    result = await _tool("read_system_file").ainvoke({"path": "system-card.yaml"})
    assert "list_systems" in result
    assert backend.requests == []


async def test_regulation_lookups_are_pinned_to_the_active_kb_version(backend):
    result = json.loads(await _tool("lookup_provision").ainvoke({"provision_id": "AIA.10.2.f"}))
    assert result["kb_version"] == "kb-2026-11-14"
    lookup = backend.requests[-1]
    assert lookup.url.params["kb_version"] == "kb-2026-11-14"


async def test_a_note_is_written_as_proposed_under_proposed(backend):
    tool = _tool("propose_system_note", system_id="SYS-001")
    result = await tool.ainvoke({"kind": "gap", "name": "Postcode Proxy!", "content": "# Gap"})
    assert "as proposed" in result
    request = backend.requests[-1]
    assert request.method == "PUT"
    assert request.url.path == "/v1/systems/SYS-001/files/proposed/gaps/postcode-proxy.md"
    body = json.loads(request.content)
    assert body["data"]["status"] == "proposed"
    assert body["content"].startswith("---\nstatus: proposed\n")


def test_the_writes_are_gated_and_no_mcp_tool_can_shadow_them():
    defaults = builtins.builtin_hitl_defaults()
    assert defaults["propose_system_note"] is True and defaults["start_audit"] is True
    assert {"list_systems", "read_audit", "lookup_provision"} <= set(builtins.BUILTIN_BY_NAME)


# ---------------------------------------------------------------------------
# A fake-LLM stream end to end
# ---------------------------------------------------------------------------
@pytest.fixture
def dry_run(monkeypatch, memory_file_store, with_copilot, backend):
    """Fake mode, an in-memory saver and file store, async sub-agents off."""
    monkeypatch.setattr(settings.gemini, "fake_llm", True)
    monkeypatch.setattr(settings.async_tasks, "enabled", False)
    monkeypatch.setattr(inference, "ConversationFileStore", lambda _pool: memory_file_store)
    saver = MemorySaver()
    set_checkpointer(saver)
    yield backend
    set_checkpointer(None)


def _text(events: list[dict]) -> str:
    return "".join(e.get("delta", "") for e in events if e["type"].startswith("TEXT_MESSAGE"))


def _tool_calls(events: list[dict]) -> list[str]:
    return [e.get("toolCallName") for e in events if e["type"] == "TOOL_CALL_START"]


async def test_an_unscoped_dry_run_lists_the_systems_and_completes(
    client, internal_headers, dry_run
):
    response = await client.post(
        f"/agents/{SLUG}/stream",
        headers=internal_headers,
        json={
            "messages": [{"id": "m1", "role": "user", "content": "What does Art. 10 require?"}],
            "config": run_config(thread_id="dry-1"),
        },
    )
    assert response.status_code == 200
    events = route_fakes.sse_events(response.text)
    types = [e["type"] for e in events]
    assert "RUN_ERROR" not in types
    assert events[-1]["name"] == "CHECKPOINT_COMMITTED"
    assert "list_systems" in _tool_calls(events)
    text = _text(events)
    assert DRY_RUN_NOTE in text and "SYS-001" in text


async def test_a_dry_run_scoped_to_a_system_opens_its_folder_first(
    client, internal_headers, dry_run, monkeypatch
):
    config = run_config(thread_id="dry-2")
    config["context"]["system_id"] = "SYS-001"
    response = await client.post(
        f"/agents/{SLUG}/stream",
        headers=internal_headers,
        json={
            "messages": [{"id": "m1", "role": "user", "content": "Where do we stand?"}],
            "config": config,
        },
    )
    assert response.status_code == 200
    events = route_fakes.sse_events(response.text)
    types = [e["type"] for e in events]
    assert "RUN_ERROR" not in types
    assert events[-1]["name"] == "CHECKPOINT_COMMITTED"
    assert _tool_calls(events)[0] == "list_system_files"
    text = _text(events)
    assert "Scoped to system SYS-001" in text and "system-card.yaml" in text
    assert any(r.url.path == "/v1/systems/SYS-001/files" for r in dry_run.requests)


def test_the_scope_reaches_the_prompt(with_copilot):
    config = run_config()
    config["context"].update(system_id="SYS-001", audit_id="SYS-001-20261115-0900")
    agent = with_copilot.build(config)
    context = agent.prompt_context()
    assert context.scope_system_id == "SYS-001"
    assert context.scope_audit_id == "SYS-001-20261115-0900"
