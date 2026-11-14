"""A deterministic stand-in chat model (``AGENTS_FAKE_LLM=true`` and the tests).

It answers from a fixed script of messages, one per call; past the end it
repeats the last one. A pipeline step scripts it to call its structured-result
tool with a canned payload, so the step runs through the same deep agent,
middleware, tool strategy and traces as with Gemini, but never leaves the
process. ``bind_tools`` keeps the script (the tools change nothing).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field


class ScriptedChatModel(BaseChatModel):
    """Replies with ``script[i]`` on the i-th call (the last one repeats)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    script: list[AIMessage] = Field(default_factory=list)
    model: str = "fake-gemini"
    calls: int = 0
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        if not self.script:
            message = AIMessage(content="")
        else:
            message = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        # A fresh id per call: a repeated tool call must not collide with the last.
        reply = message.model_copy(deep=True)
        if reply.tool_calls:
            reply.tool_calls = [
                {**call, "id": f"call_{uuid4().hex[:12]}"} for call in reply.tool_calls
            ]
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        return self


def tool_call_message(name: str, args: dict[str, Any], text: str = "") -> AIMessage:
    """One AI message calling ``name`` with ``args`` (the id is replaced per call)."""
    return AIMessage(
        content=text, tool_calls=[{"name": name, "args": args, "id": "call_0", "type": "tool_call"}]
    )


#: How much of the tool result a dry-run reply quotes.
DRY_RUN_QUOTE_CHARS = 1500

DRY_RUN_NOTE = "Dry run (AGENTS_FAKE_LLM=true): no language model was called."


class DryRunChatModel(BaseChatModel):
    """A chat agent's stand-in in fake mode: one optional tool call, then a text answer.

    Each turn (after the last human message) it calls ``first_tool`` once, when
    set, so a dry run still exercises the real tools and APIs, then answers with
    a fixed note, ``preface`` and an excerpt of the tool's result. Deterministic:
    the reply depends only on the messages it is given.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    first_tool: str | None = None
    first_args: dict[str, Any] = Field(default_factory=dict)
    preface: str = ""
    model: str = "fake-gemini"

    @property
    def _llm_type(self) -> str:
        return "dry-run-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
        )
        turn = messages[last_human + 1 :]
        results = [m for m in turn if isinstance(m, ToolMessage)]
        if self.first_tool and not results:
            message = tool_call_message(self.first_tool, dict(self.first_args))
            message.tool_calls = [
                {**call, "id": f"call_{uuid4().hex[:12]}"} for call in message.tool_calls
            ]
        else:
            parts = [DRY_RUN_NOTE, self.preface]
            if results:
                quoted = str(results[-1].content)[:DRY_RUN_QUOTE_CHARS]
                parts.append(f"`{results[-1].name}` returned:\n\n```\n{quoted}\n```")
            message = AIMessage(content="\n\n".join(p for p in parts if p))
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> DryRunChatModel:
        return self


__all__ = [
    "DRY_RUN_NOTE",
    "DryRunChatModel",
    "ScriptedChatModel",
    "tool_call_message",
]
