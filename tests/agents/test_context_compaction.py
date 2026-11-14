"""Automatic context compaction: when it cuts, how it is stamped, and that a fork keeps it.

Pinned:

* a compaction cuts at the newest question: the latest exchange (question,
  tool calls, answer) is kept whole, and only what the person sees is counted;
* the summary call reads everything it folds (no 4000-token trim);
* an automatic compaction is stamped on the reply it ran in front of, the
  offloaded history is named after the branch thread, and the next model call
  sees ``summary + recent``; on a plain LangChain agent and on a real deep
  agent (whose ``messages`` is a delta channel) alike;
* an edit/retry fork of a compacted branch keeps the compaction: private
  channels do not survive a write through the input, so the fork carries
  ``_summarization_event`` itself;
* the normalizer turns a compaction into ``CONTEXT_COMPACTION`` started/done
  plus a ``TOKEN_USAGE`` with ``purpose: compaction``, never the summary text;
* the tuned summarizer's thresholds, the stock summarizer's exclusion, and a
  model newer than LangChain getting its declared window.
"""

from __future__ import annotations

import json

import pytest
from deepagents import create_deep_agent
from deepagents._models import get_model_provider, resolve_model
from deepagents.backends import FilesystemBackend
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from core.settings import settings
from harness.abstractions import DeepAgent
from harness.agui.normalizer import AGUIStreamNormalizer
from harness.checkpointer import fork as fork_module
from harness.checkpointer.fork import carry_compaction, seed_thread_from_checkpoint
from harness.middlewares import (
    COMPACTION_KEY,
    EVENT_KEY,
    ConfigurableSummarizationMiddleware,
    build_summarization_middleware,
    exclude_stock_summarization,
)
from harness.middlewares import summarization as summarization_module
from harness.middlewares.summarization import (
    is_summary,
    summarized_slice,
    summary_cutoff,
    tokens_freed,
    visible_messages,
)

USAGE = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
SUMMARY_USAGE = {"input_tokens": 900, "output_tokens": 40, "total_tokens": 940}
#: Fires after the fifth message: q0 r1 q1 r2 q2 compacts before the third reply.
AUTO_TRIGGER = ("messages", 5)


def _replies():
    turn = 0
    while True:
        turn += 1
        yield AIMessage(content=f"reply {turn} " + "word " * 40, usage_metadata=USAGE)


class _Seen:
    """Records what the agent's model was shown on each call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []


class _ToolTolerantFake(GenericFakeChatModel):
    """A fake chat model a deep agent can bind its built-in tools to."""

    def bind_tools(self, tools, **kwargs):
        return self


def _summary_model(text: str = "THE SUMMARY") -> GenericFakeChatModel:
    return GenericFakeChatModel(
        messages=iter([AIMessage(content=text, usage_metadata=SUMMARY_USAGE)] * 4)
    )


def _graph(tmp_path, *, seen: _Seen, trigger=AUTO_TRIGGER, kind: str = "plain"):
    """A plain LangChain agent, or (``kind="deep"``) a real deep agent, the
    graph production runs, with its delta ``messages`` channel."""

    class Spy(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            seen.calls.append([str(m.content)[:12] for m in request.messages])
            return await handler(request)

    summarizer = ConfigurableSummarizationMiddleware(
        _summary_model(),
        backend=FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True),
        trigger=trigger,
        keep=("messages", 2),
    )
    if kind == "deep":
        model = _ToolTolerantFake(messages=_replies())
        # As build_deep_agent does: drop deepagents' stock summarizer, or it
        # compacts a second time. The fake has no model spec, so its profile
        # resolves through its provider key.
        exclude_stock_summarization(get_model_provider(model))
        return create_deep_agent(
            model=model, middleware=[summarizer, Spy()], checkpointer=InMemorySaver()
        )
    return create_agent(
        model=GenericFakeChatModel(messages=_replies()),
        middleware=[summarizer, Spy()],
        checkpointer=InMemorySaver(),
    )


async def _turns(graph, thread_id: str, count: int):
    cfg = {"configurable": {"thread_id": thread_id}}
    for i in range(count):
        await graph.ainvoke({"messages": [HumanMessage(content=f"question {i}")]}, cfg)
    head = await graph.checkpointer.aget_tuple(cfg)
    return cfg, head.config["configurable"]["checkpoint_id"]


@pytest.fixture
def no_scratch_copy(monkeypatch):
    """The fork's scratch copy needs Postgres; these tests only pin the state seed."""

    async def fake_copy(_source: str, _target: str) -> int:
        return 0

    monkeypatch.setattr(fork_module, "copy_branch_scratch", fake_copy)


def _events(frames):
    out = []
    for frame in frames:
        for line in frame.decode("utf-8").splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                out.append((payload.get("name") or payload.get("type"), payload.get("value")))
    return out


# ------------------------------------------------------------------- the cut
def test_the_cut_keeps_the_latest_exchange_whole_and_counts_what_is_seen():
    summary = HumanMessage(content="S", additional_kwargs={"lc_source": "summarization"})
    messages = [
        summary,
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "search", "args": {}}]),
        ToolMessage(content="User rejected this action.", tool_call_id="c1"),
        AIMessage(content="answer to again"),
        HumanMessage(content="summarize it"),
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "search", "args": {}}]),
        ToolMessage(content="[]", tool_call_id="c2"),
        AIMessage(content="the summary"),
    ]
    cut = summary_cutoff(messages)
    assert cut == 4  # "summarize it" and everything after it stay whole
    # Before the cut the person sees one bubble (the answer); never the earlier
    # summary, the tool call or its result.
    assert visible_messages(messages, 0, cut) == 1
    assert visible_messages(messages, cut, len(messages)) == 2


def test_nothing_to_fold_cuts_nothing():
    summary = HumanMessage(content="S", additional_kwargs={"lc_source": "summarization"})
    # Only the previous summary before the newest question.
    assert summary_cutoff([summary, HumanMessage(content="q"), AIMessage(content="a")]) == 0
    # One exchange: the question is the first message.
    assert summary_cutoff([HumanMessage(content="q"), AIMessage(content="a")]) == 0
    # No question at all.
    assert summary_cutoff([AIMessage(content="a")]) == 0
    assert summary_cutoff([]) == 0


def test_only_a_tagged_human_message_is_a_summary():
    assert is_summary(HumanMessage(content="S", additional_kwargs={"lc_source": "summarization"}))
    assert not is_summary(HumanMessage(content="S"))
    assert not is_summary(AIMessage(content="S", additional_kwargs={"lc_source": "summarization"}))


def test_visible_messages_clamps_its_range():
    messages = [HumanMessage(content="q"), AIMessage(content="a")]
    assert visible_messages(messages, -3, 99) == 2
    assert visible_messages(messages, 1, 1) == 0


def test_the_summarized_slice_inverts_the_absolute_cutoff():
    effective = [HumanMessage(content=str(i)) for i in range(6)]
    # No earlier compaction: the cutoff is the count.
    assert summarized_slice(effective, None, {"cutoff_index": 4}) == 4
    # An older summary sat in front: deepagents stored old + effective - 1.
    assert summarized_slice(effective, {"cutoff_index": 10}, {"cutoff_index": 13}) == 4
    # Never past the list, never negative, nothing without a cutoff.
    assert summarized_slice(effective, None, {"cutoff_index": 40}) == 6
    assert summarized_slice(effective, {"cutoff_index": 10}, {"cutoff_index": 2}) == 0
    assert summarized_slice(effective, None, {}) == 0


def test_tokens_freed_never_goes_negative_or_raises():
    def counter(messages):
        return 10 * len(messages)

    def broken(_messages):
        raise TypeError("no count")

    two = [HumanMessage(content="a"), HumanMessage(content="b")]
    assert tokens_freed(counter, two, HumanMessage(content="s")) == 10
    assert tokens_freed(counter, [], HumanMessage(content="s")) == 0
    assert tokens_freed(broken, two, HumanMessage(content="s")) == 0


def test_the_summarizer_cuts_at_the_question_and_reads_everything_it_folds(tmp_path):
    summarizer = ConfigurableSummarizationMiddleware(
        _summary_model(),
        backend=FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True),
        trigger=AUTO_TRIGGER,
        keep=("messages", 2),
    )
    messages = [HumanMessage(content="q1"), AIMessage(content="a1"), HumanMessage(content="q2")]
    assert summarizer._determine_cutoff_index(messages) == 2
    assert summarizer._lc_helper.trim_tokens_to_summarize is None
    assert (summarizer.trigger_spec, summarizer.keep_spec) == (AUTO_TRIGGER, ("messages", 2))


# ------------------------------------------------------- automatic compaction
@pytest.mark.parametrize("kind", ["plain", "deep"])
async def test_an_automatic_compaction_is_stamped_on_the_reply(tmp_path, kind):
    seen = _Seen()
    graph = _graph(tmp_path, seen=seen, kind=kind)
    cfg, _head = await _turns(graph, "t-auto", 3)

    state = await graph.aget_state(cfg)
    stamped = [
        m.response_metadata[COMPACTION_KEY]
        for m in state.values["messages"]
        if isinstance(m, AIMessage) and COMPACTION_KEY in (m.response_metadata or {})
    ]
    assert len(stamped) == 1
    # q0 r1 q1 r2 q2 hit the trigger; the cut keeps the newest question.
    assert (stamped[0]["summarized_messages"], stamped[0]["kept_messages"]) == (4, 1)
    assert stamped[0]["freed"] >= 0
    saved = await graph.checkpointer.aget_tuple(cfg)
    assert saved.checkpoint["channel_values"][EVENT_KEY]["cutoff_index"] == 4
    # The full history went to disk under the branch thread's name.
    assert (tmp_path / "conversation_history" / "t-auto.md").exists()
    # The compacted call itself saw the summary and the newest question only.
    assert seen.calls[2][1:] == ["question 2"]


@pytest.mark.parametrize("kind", ["plain", "deep"])
async def test_the_next_turn_sees_the_summary_and_what_followed(tmp_path, kind):
    seen = _Seen()
    graph = _graph(tmp_path, seen=seen, kind=kind)
    cfg, _head = await _turns(graph, "t-next", 3)

    seen.calls.clear()
    await graph.ainvoke({"messages": [HumanMessage(content="question 3")]}, cfg)
    shown = seen.calls[0]
    assert "THE SUMMARY" in shown[0] or shown[0].startswith("You are in")
    assert shown[1:] == ["question 2", "reply 3 word", "question 3"]


async def test_below_the_trigger_nothing_is_compacted(tmp_path):
    graph = _graph(tmp_path, seen=_Seen(), trigger=("tokens", 10**9))
    cfg, _head = await _turns(graph, "t-quiet", 3)

    saved = await graph.checkpointer.aget_tuple(cfg)
    assert saved.checkpoint["channel_values"].get(EVENT_KEY) is None
    state = await graph.aget_state(cfg)
    assert not any(COMPACTION_KEY in (m.response_metadata or {}) for m in state.values["messages"])


# ---------------------------------------------------------------- fork carry
@pytest.mark.parametrize("kind", ["plain", "deep"])
async def test_a_fork_keeps_the_compaction(tmp_path, kind, no_scratch_copy):
    seen = _Seen()
    graph = _graph(tmp_path, seen=seen, kind=kind)
    _cfg, head = await _turns(graph, "src", 3)

    seeded = await seed_thread_from_checkpoint(
        graph=graph, source_thread_id="src", source_checkpoint_id=head, target_thread_id="branch"
    )

    assert seeded
    branch = {"configurable": {"thread_id": "branch"}}
    assert (await graph.checkpointer.aget_tuple(branch)).checkpoint["channel_values"].get(EVENT_KEY)
    seen.calls.clear()
    await graph.ainvoke({"messages": [HumanMessage(content="edited")]}, branch)
    assert seen.calls[0][1:] == ["question 2", "reply 3 word", "edited"]


async def test_the_carry_reads_the_saved_checkpoint_when_the_snapshot_lacks_it(tmp_path):
    graph = _graph(tmp_path, seen=_Seen())
    src_cfg, _head = await _turns(graph, "src", 3)
    target = {"configurable": {"thread_id": "target"}}
    await graph.aupdate_state(target, {"messages": [HumanMessage(content="seed")]})

    assert await carry_compaction(graph, src_cfg, {}, target) is True
    saved = await graph.checkpointer.aget_tuple(target)
    assert saved.checkpoint["channel_values"][EVENT_KEY]["cutoff_index"] == 4


async def test_an_uncompacted_source_carries_nothing(tmp_path):
    graph = _graph(tmp_path, seen=_Seen(), trigger=("tokens", 10**9))
    src_cfg, _head = await _turns(graph, "src", 2)
    target = {"configurable": {"thread_id": "target"}}

    assert await carry_compaction(graph, src_cfg, {}, target) is False


async def test_a_failed_carry_still_seeds_the_branch(tmp_path, monkeypatch, no_scratch_copy):
    # Without the compaction the branch only starts from the full history again.
    async def broken_carry(*_args, **_kwargs):
        raise RuntimeError("checkpointer hiccup")

    monkeypatch.setattr(fork_module, "carry_compaction", broken_carry)
    graph = _graph(tmp_path, seen=_Seen())
    _cfg, head = await _turns(graph, "src", 3)

    assert await seed_thread_from_checkpoint(
        graph=graph, source_thread_id="src", source_checkpoint_id=head, target_thread_id="branch"
    )
    branch = {"configurable": {"thread_id": "branch"}}
    state = await graph.aget_state(branch)
    assert state.values["messages"]
    assert (await graph.checkpointer.aget_tuple(branch)).checkpoint["channel_values"].get(
        EVENT_KEY
    ) is None


# ---------------------------------------------------------------- normalizer
def test_the_normalizer_reports_an_automatic_compaction():
    norm = AGUIStreamNormalizer(thread_id="run-1")
    meta = {"lc_source": "summarization"}

    started = norm.handle_chunk(
        ((), "messages", (AIMessageChunk(content="SESSION SUMMARY", id="sum-1"), meta))
    )
    usage = norm.handle_chunk(
        ((), "messages", (AIMessageChunk(content="", id="sum-1", usage_metadata=USAGE), meta))
    )
    again = norm.handle_chunk(
        (
            (),
            "messages",
            (AIMessage(content="SESSION SUMMARY", id="sum-1", usage_metadata=USAGE), meta),
        )
    )
    reply = AIMessage(
        content="answer",
        id="ai-1",
        usage_metadata={"input_tokens": 40_000, "output_tokens": 10, "total_tokens": 40_010},
        response_metadata={
            COMPACTION_KEY: {"freed": 90_000, "summarized_messages": 30, "kept_messages": 4}
        },
    )
    done = norm.handle_chunk(((), "updates", {"model": {"messages": [reply]}}))

    assert _events(started) == [("CONTEXT_COMPACTION", {"phase": "started", "trigger": "auto"})]
    [(name, value)] = _events(usage)
    assert name == "TOKEN_USAGE"
    assert value["purpose"] == "compaction"
    assert value["message_id"] == "sum-1"
    assert _events(again) == []  # same call, counted once; its text never surfaces
    names = [name for name, _ in _events(done)]
    assert names.index("CONTEXT_COMPACTION") < names.index("TOKEN_USAGE")
    value = dict(_events(done))["CONTEXT_COMPACTION"]
    assert (value["phase"], value["trigger"]) == ("done", "auto")
    assert (value["tokens_after"], value["freed"], value["tokens_before"]) == (
        40_000,
        90_000,
        130_000,
    )
    assert (value["summarized_messages"], value["kept_messages"]) == (30, 4)
    assert all("SESSION SUMMARY" not in json.dumps(v) for _, v in _events(started + done))


# ------------------------------------------------------------------- wiring
def test_a_model_with_a_window_compacts_by_fraction(tmp_path):
    model = GenericFakeChatModel(messages=iter([]))
    model.profile = {"max_input_tokens": 100_000}
    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    built = build_summarization_middleware(model, backend)
    assert built.trigger_spec == ("fraction", settings.summarization.trigger_fraction)
    assert built.keep_spec == ("fraction", settings.summarization.keep_fraction)


def test_a_model_without_a_window_falls_back_to_tokens_and_messages(tmp_path):
    settings.summarization.trigger_tokens = 12_345
    settings.summarization.keep_messages = 7
    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    built = build_summarization_middleware(GenericFakeChatModel(messages=iter([])), backend)
    assert built.trigger_spec == ("tokens", 12_345)
    assert built.keep_spec == ("messages", 7)


def test_the_stock_summarizer_is_excluded_once_per_spec(monkeypatch):
    registered: list[str] = []
    monkeypatch.setattr(summarization_module, "_excluded_keys", set())
    monkeypatch.setattr(
        summarization_module,
        "register_harness_profile",
        lambda spec, profile: registered.append(spec),
    )
    exclude_stock_summarization("openai:test-model")
    exclude_stock_summarization("openai:test-model")
    # Without a string spec there is no profile key to register against.
    exclude_stock_summarization("")
    exclude_stock_summarization(None)  # type: ignore[arg-type]
    assert registered == ["openai:test-model"]


def test_a_model_newer_than_langchain_gets_its_declared_window():
    # gpt-6-luna has no profile in the pinned langchain-openai: without the
    # declared window, fraction-based compaction would have nothing to read.
    DeepAgent.register_model_windows()
    model = resolve_model("openai:gpt-6-luna")
    declared = settings.registry.models["openai:gpt-6-luna"].context_window
    assert model.profile["max_input_tokens"] == declared
