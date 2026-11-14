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
from langchain_core.messages import AIMessage, BaseMessage
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


__all__ = ["ScriptedChatModel", "tool_call_message"]
