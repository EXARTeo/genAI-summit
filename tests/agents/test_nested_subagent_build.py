"""Sub-agents with sub-agents of their own: the definition and the build.

deepagents builds the main agent's own sub-agents and nothing below them. A
sub-agent that delegates in turn gets a ``SubAgentMiddleware`` from our build
path, and every spec below depth 1 is built there in full. Pinned here:

* **the definition**: at most ``MAX_SUBAGENT_DEPTH`` levels, unique sibling
  names, no name repeated below itself, and tools only ever narrowing on the
  way down (``AgentSpec`` for YAML agents, ``validate_subagent_tree`` for
  agents written in code);
* **the build** (blocking ``task`` path): every level carries the platform
  middleware, the base stack deepagents gives depth 1 (planning, filesystem
  with the workspace's rules, summarization, PatchToolCalls), the run's
  approval gates (which a spec can add to but never clear a locked one from),
  and never ``ask_user``;
* **the YAML agent** declares the same tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.tools import tool
from pydantic import ValidationError

from core.settings import settings
from harness.abstractions import deep_agent as deep_agent_module
from harness.abstractions import subagent_tree as tree_module
from harness.abstractions.agent_spec import MAX_SUBAGENT_DEPTH, AgentSpec
from harness.abstractions.yaml_agent import YamlDeepAgent
from harness.middlewares import RetryOnRateLimitMiddleware, ToolErrorMiddleware
from harness.prompt_engineering.prompts.capabilities_prompt import DELEGATING_SUBAGENT_PROMPT


@tool
def search(query: str) -> str:
    """Search the web."""
    return query


@tool
def lookup(claim: str) -> str:
    """Look a claim up."""
    return claim


@tool
def ask_user(question: str) -> str:
    """Ask the user (stands in for the real tool: only its name matters here)."""
    return question


MODEL = "openai:gpt-4.1-mini"
PLATFORM = (ToolErrorMiddleware, RetryOnRateLimitMiddleware)


def _agent_spec(*, tools=(), subagents=()) -> AgentSpec:
    return AgentSpec.model_validate(
        {
            "id": "nested-demo-v1",
            "slug": "nested-demo",
            "name": "Nested demo",
            "version": "1.0.0",
            "type": "deep_agent",
            "prompt": "You answer questions.",
            "model": {"main": MODEL},
            "tools": list(tools),
            "subagents": list(subagents),
        }
    )


def _sa(name: str, *children: dict, tools=None) -> dict:
    out: dict[str, Any] = {
        "name": name,
        "description": f"The {name}.",
        "prompt": f"You are the {name}.",
    }
    if tools is not None:
        out["tools"] = tools
    if children:
        out["subagents"] = list(children)
    return out


NATIVE_CHART = {"native": "render_chart"}
NATIVE_PRESENT = {"native": "present_artifact"}


# ---------------------------------------------------------------------------
# The definition (YAML agents)
# ---------------------------------------------------------------------------
def test_three_levels_below_the_agent_are_allowed():
    spec = _agent_spec(subagents=[_sa("researcher", _sa("fact-checker", _sa("source-verifier")))])
    assert [path for path, _ in spec.walk_subagents()] == [
        ("researcher",),
        ("researcher", "fact-checker"),
        ("researcher", "fact-checker", "source-verifier"),
    ]
    assert MAX_SUBAGENT_DEPTH == 3


def test_a_fourth_level_is_refused():
    deep = _sa("a", _sa("b", _sa("c", _sa("d"))))
    with pytest.raises(
        ValidationError, match="'a > b > c > d' is 4 levels below the agent; at most 3"
    ):
        _agent_spec(subagents=[deep])


def test_siblings_need_distinct_names():
    with pytest.raises(ValidationError, match="under 'researcher' share a name: checker"):
        _agent_spec(subagents=[_sa("researcher", _sa("checker"), _sa("checker"))])
    with pytest.raises(ValidationError, match="of the agent share a name: researcher"):
        _agent_spec(subagents=[_sa("researcher"), _sa("researcher")])


def test_a_name_cannot_repeat_below_itself():
    with pytest.raises(
        ValidationError, match="'researcher > checker > researcher' repeats a name above it"
    ):
        _agent_spec(subagents=[_sa("researcher", _sa("checker", _sa("researcher")))])
    # The same name in two branches is not a loop.
    spec = _agent_spec(subagents=[_sa("a", _sa("checker")), _sa("b", _sa("checker"))])
    assert len(list(spec.walk_subagents())) == 4


def test_tools_only_narrow_on_the_way_down():
    declared = [NATIVE_CHART, NATIVE_PRESENT]
    # Inheriting at every level, or narrowing step by step, is fine.
    _agent_spec(tools=declared, subagents=[_sa("r", _sa("c", tools=[NATIVE_PRESENT]))])
    _agent_spec(
        tools=declared,
        subagents=[
            _sa("r", _sa("c", tools=[NATIVE_PRESENT]), tools=[NATIVE_PRESENT, NATIVE_CHART])
        ],
    )
    # A child cannot take back what its parent gave up.
    with pytest.raises(
        ValidationError, match="'r > c' lists tools sub-agent 'r' does not have: render_chart"
    ):
        _agent_spec(
            tools=declared,
            subagents=[_sa("r", _sa("c", tools=[NATIVE_CHART]), tools=[NATIVE_PRESENT])],
        )
    # Nor anything the agent itself was never given.
    with pytest.raises(
        ValidationError, match="lists tools sub-agent 'r' does not have: view_image"
    ):
        _agent_spec(
            tools=declared, subagents=[_sa("r", _sa("c", tools=[{"native": "view_image"}]))]
        )


def test_references_are_collected_at_every_depth():
    inner = {**_sa("c", tools=[NATIVE_PRESENT]), "model": "openai:gpt-4o"}
    spec = _agent_spec(tools=[NATIVE_PRESENT], subagents=[_sa("r", inner)])
    assert spec.all_model_ids() == sorted({MODEL, "openai:gpt-4o"})
    assert spec.native_tool_names() == ["present_artifact"]


# ---------------------------------------------------------------------------
# The definition (agents written in code)
# ---------------------------------------------------------------------------
def test_a_code_defined_tree_is_held_to_the_same_rules():
    sub = tree_module.subagent
    tree_module.validate_subagent_tree(
        [sub("r", "d", "p", subagents=[sub("c", "d", "p", subagents=[sub("s", "d", "p")])])]
    )
    too_deep = sub(
        "a",
        "d",
        "p",
        subagents=[
            sub("b", "d", "p", subagents=[sub("c", "d", "p", subagents=[sub("d", "d", "p")])])
        ],
    )
    with pytest.raises(ValueError, match="4 levels below the agent"):
        tree_module.validate_subagent_tree([too_deep])
    with pytest.raises(ValueError, match="repeats a name above it"):
        tree_module.validate_subagent_tree([sub("r", "d", "p", subagents=[sub("r", "d", "p")])])
    with pytest.raises(ValueError, match="share a name: r"):
        tree_module.validate_subagent_tree([sub("r", "d", "p"), sub("r", "d", "p")])
    looped = sub("r", "d", "p")
    looped["subagents"] = [looped]
    with pytest.raises(ValueError, match="contains itself"):
        tree_module.validate_subagent_tree([looped])
    compiled = {
        "name": "x",
        "description": "d",
        "runnable": object(),
        "subagents": [sub("c", "d", "p")],
    }
    with pytest.raises(ValueError, match="cannot declare sub-agents"):
        tree_module.validate_subagent_tree([compiled])


def test_the_subagent_helper_leaves_omitted_values_out():
    # An omitted key means "inherit" downstream, so it must be absent, not None.
    assert tree_module.subagent("r", "d", "p") == {
        "name": "r",
        "description": "d",
        "system_prompt": "p",
    }
    full = tree_module.subagent(
        "r", "d", "p", model="m", tools=[], interrupt_on={"x": True}, subagents=[{"name": "c"}]
    )
    assert full["tools"] == [] and full["interrupt_on"] == {"x": True}
    assert full[tree_module.SUBAGENTS_KEY] == [{"name": "c"}]


# ---------------------------------------------------------------------------
# The build (blocking `task` path)
# ---------------------------------------------------------------------------
@pytest.fixture
def build(monkeypatch):
    """Run the real build_deep_agent; capture what reaches create_deep_agent."""
    # The blocking path is under test; an agent without a client would take it
    # anyway, but the switch says so explicitly.
    settings.async_tasks.enabled = False

    class Bare(deep_agent_module.DeepAgent):
        name = "nested-build"

        def register_agent(self):
            return None

    def _build(subagents, *, interrupt_on=None):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            deep_agent_module, "create_deep_agent", lambda **kwargs: captured.update(kwargs)
        )
        agent = Bare()
        monkeypatch.setattr(agent, "_build_composite_backend", lambda: StateBackend())
        agent.tools = [search, lookup, ask_user]
        agent.build_deep_agent(
            model=MODEL, middleware=[], interrupt_on=interrupt_on or {}, subagents=subagents
        )
        return captured

    return _build


def _nested(spec: dict) -> dict[str, dict]:
    """The specs a top-level (or nested) spec delegates to, by name."""
    [task] = [m for m in spec["middleware"] if isinstance(m, SubAgentMiddleware)]
    return {child["name"]: child for child in task._subagents}


def _tree() -> list[dict]:
    sub = tree_module.subagent
    return [
        sub(
            "researcher",
            "Researches.",
            "You are the researcher.",
            subagents=[
                sub(
                    "fact-checker",
                    "Checks facts.",
                    "You are the fact-checker.",
                    tools=[lookup, ask_user],
                    interrupt_on={"lookup": True, "execute": False},
                    subagents=[sub("source-verifier", "Finds sources.", "You are the verifier.")],
                ),
                sub("citer", "Cites.", "You are the citer.", tools=[]),
            ],
        ),
        sub("writer", "Writes.", "You are the writer."),
    ]


def test_every_level_carries_the_platform_middleware(build):
    top = {s["name"]: s for s in build(_tree())["subagents"]}
    researcher = top["researcher"]
    checker = _nested(researcher)["fact-checker"]
    verifier = _nested(checker)["source-verifier"]
    citer = _nested(researcher)["citer"]

    for spec in (top["general-purpose"], researcher, top["writer"], checker, verifier, citer):
        stack = spec["middleware"]
        for cls in PLATFORM:
            assert sum(isinstance(m, cls) for m in stack) == 1, (spec["name"], cls.__name__)
        # The rate-limit retry is outermost, so a 429 anywhere is waited out.
        assert isinstance(stack[0], RetryOnRateLimitMiddleware), spec["name"]
    # Below depth 1 our build adds what deepagents adds at depth 1.
    for spec in (checker, verifier, citer):
        stack = spec["middleware"]
        for cls in (TodoListMiddleware, FilesystemMiddleware, PatchToolCallsMiddleware):
            assert sum(isinstance(m, cls) for m in stack) == 1, (spec["name"], cls.__name__)
        assert any(type(m).__name__.endswith("SummarizationMiddleware") for m in stack)
    # Only a sub-agent with sub-agents has a `task` tool of its own.
    delegating = [
        s["name"]
        for s in (researcher, checker, verifier, citer, top["writer"])
        if any(isinstance(m, SubAgentMiddleware) for m in s["middleware"])
    ]
    assert delegating == ["researcher", "fact-checker"]
    assert "subagents" not in researcher


def test_the_general_purpose_subagent_is_declared_once(build):
    names = [s["name"] for s in build(_tree())["subagents"]]
    assert names == ["general-purpose", "researcher", "writer"]


def test_no_subagent_at_any_depth_has_ask_user(build):
    top = {s["name"]: s for s in build(_tree())["subagents"]}
    researcher = top["researcher"]
    checker = _nested(researcher)["fact-checker"]
    verifier = _nested(checker)["source-verifier"]
    citer = _nested(researcher)["citer"]

    for spec in (*top.values(), checker, verifier, citer):
        assert "ask_user" not in [t.name for t in spec["tools"]], spec["name"]
    # Inheriting means the tools of the agent above, minus ask_user; an explicit
    # list is kept (minus ask_user); an empty one stays empty.
    assert [t.name for t in researcher["tools"]] == ["search", "lookup"]
    assert [t.name for t in checker["tools"]] == ["lookup"]
    assert [t.name for t in verifier["tools"]] == ["lookup"]
    assert citer["tools"] == []


def test_the_main_agent_keeps_ask_user(build):
    captured = build(_tree())
    assert "ask_user" in [t.name for t in captured["tools"]]


def test_gates_apply_at_every_depth_and_a_locked_one_cannot_be_cleared(build):
    top = {s["name"]: s for s in build(_tree(), interrupt_on={"search": True})["subagents"]}
    checker = _nested(top["researcher"])["fact-checker"]
    verifier = _nested(checker)["source-verifier"]

    # The run's gates reach depth 3 (the agent's own `search`, the builtin
    # defaults such as `task`), the spec adds its own, and `execute` stays
    # locked although the spec tried to clear it.
    for spec in (checker, verifier):
        gated = spec["interrupt_on"]
        assert gated["search"] is True, spec["name"]
        assert gated["task"] is True, spec["name"]
        assert gated["execute"] is True, spec["name"]
    assert checker["interrupt_on"]["lookup"] is True
    assert "lookup" not in verifier["interrupt_on"]
    assert "ask_user" not in checker["interrupt_on"]


def test_a_delegating_subagent_is_told_how_to_use_its_own_subagents(build):
    top = {s["name"]: s for s in build(_tree())["subagents"]}
    researcher = top["researcher"]
    checker = _nested(researcher)["fact-checker"]

    assert researcher["system_prompt"].startswith("You are the researcher.")
    assert DELEGATING_SUBAGENT_PROMPT in researcher["system_prompt"]
    assert DELEGATING_SUBAGENT_PROMPT in checker["system_prompt"]
    assert DELEGATING_SUBAGENT_PROMPT not in _nested(checker)["source-verifier"]["system_prompt"]
    assert DELEGATING_SUBAGENT_PROMPT not in top["writer"]["system_prompt"]


def test_a_tree_too_deep_fails_the_build(build):
    sub = tree_module.subagent
    deep = sub(
        "a",
        "d",
        "p",
        subagents=[
            sub("b", "d", "p", subagents=[sub("c", "d", "p", subagents=[sub("d", "d", "p")])])
        ],
    )
    with pytest.raises(ValueError, match="4 levels below the agent"):
        build([deep])


# ---------------------------------------------------------------------------
# The YAML agent
# ---------------------------------------------------------------------------
def test_the_yaml_agent_declares_the_tree(tmp_path: Path):
    spec = _agent_spec(
        tools=[NATIVE_PRESENT],
        subagents=[
            _sa(
                "researcher",
                {**_sa("fact-checker", _sa("source-verifier")), "model": "openai:gpt-4o"},
            )
        ],
    )
    agent = YamlDeepAgent(spec, tmp_path)

    [researcher] = agent.register_subagents()
    [checker] = researcher["subagents"]
    [verifier] = checker["subagents"]
    assert (researcher["name"], checker["name"], verifier["name"]) == (
        "researcher",
        "fact-checker",
        "source-verifier",
    )
    assert checker["model"] == "openai:gpt-4o"
    assert verifier["model"] == MODEL
    assert verifier["system_prompt"] == "You are the source-verifier."
    assert "tools" not in checker  # inherits
    assert "subagents" not in verifier


def test_a_yaml_tree_builds_through_the_same_path(build, tmp_path: Path):
    spec = _agent_spec(subagents=[_sa("researcher", _sa("fact-checker")), _sa("writer")])
    specs = YamlDeepAgent(spec, tmp_path).register_subagents()
    built = {s["name"]: s for s in build(specs)["subagents"]}
    assert list(built) == ["general-purpose", "researcher", "writer"]
    checker = _nested(built["researcher"])["fact-checker"]
    assert not any(isinstance(m, SubAgentMiddleware) for m in checker["middleware"])
    assert checker["interrupt_on"]["execute"] is True
