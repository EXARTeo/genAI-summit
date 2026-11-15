"""Ask the reasoning models for their reasoning, so the chat shows it as thinking.

**OpenAI** never returns a reasoning model's reasoning: through the Responses API
(deepagents' default for ``openai:*``) it comes back only as an encrypted item,
which the next turn sends back unread. Asked with ``reasoning={"summary": ...}``,
the model adds its own short summary of it, in parts.

**Gemini** (``google_genai:*``, the product's only provider) thinks by default
but returns nothing of it unless asked with ``include_thoughts=True``; then each
response carries thought-summary parts (``{"type": "thinking", ...}``), each a
titled section. ``GEMINI_THINKING_LEVEL`` optionally sets how hard it thinks
(``gemini-3.5-flash-lite`` thinks minimally by default and returns no thought
parts even when asked; ``gemini-3.5-flash`` does).

Either way the normalizer turns each part into a thought in the chat's CoT,
beside the tool calls, and Langfuse shows it instead of "Thinking (redacted)".

Only reasoning models get it: a non-reasoning model (gpt-4o) rejects the
parameter. Which is which: the model's ``reasoning`` in ``AGENT_MODELS``, else
the pinned langchain-openai's model table (it knows the models older than it),
else, for Gemini, the model generation (2.5 and later think). The kwargs ride
deepagents' ``ProviderProfile``, the same registry the context windows ride
(``DeepAgent.register_model_windows``), so they apply wherever deepagents
resolves the spec — the agent, every sub-agent, its summarizer. Which specs an
agent uses is the caller's to say (``DeepAgent`` walks its sub-agent tree).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from deepagents import ProviderProfile, register_provider_profile

from core.logging import get_logger
from core.settings import settings

try:
    # Private, but it is the very table ``model.profile`` is filled from.
    from langchain_openai.chat_models.base import _get_default_model_profile as _openai_profile
except ImportError:  # without langchain-openai no OpenAI model is known to reason
    _openai_profile = None

logger = get_logger(__name__)

_DATED_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")
#: Gemini generations that think (2.5, 3.x and later); 1.x and 2.0 do not.
_GEMINI_THINKING = re.compile(r"^gemini-(?:2\.5|[3-9]|\d{2,})")
_GEMINI_PROVIDER = "google_genai"

#: Specs this process already asked for reasoning (registration merges, so once is enough).
_registered: set[str] = set()


def is_reasoning_model(spec: str) -> bool:
    """True for a reasoning model (gpt-5, o3, o4-mini, gemini-2.5+, …), by exact spec."""
    info = settings.registry.models.get(spec)
    if info is not None and info.reasoning is not None:
        return info.reasoning
    provider, _, name = spec.partition(":")
    if provider == _GEMINI_PROVIDER:
        return bool(_GEMINI_THINKING.match(name))
    if provider != "openai" or not name or _openai_profile is None:
        return False
    # A dated name (gpt-5-2025-08-07) is listed under its base name.
    for candidate in (name, _DATED_SUFFIX.sub("", name)):
        profile = _openai_profile(candidate) or {}
        if profile:
            return bool(profile.get("reasoning_output"))
    return False


def reasoning_kwargs(spec: str, mode: str) -> dict[str, Any]:
    """The constructor kwargs that make ``spec`` return its reasoning (``mode`` not off)."""
    if spec.startswith(f"{_GEMINI_PROVIDER}:"):
        kwargs: dict[str, Any] = {"include_thoughts": True}
        if settings.gemini.thinking_level:
            kwargs["thinking_level"] = settings.gemini.thinking_level
        return kwargs
    return {"reasoning": {"summary": mode}}


def register_reasoning_summaries(specs: Iterable[str]) -> None:
    """Ask every reasoning model among ``specs`` (``provider:model``) for its reasoning.

    Runs before anything resolves those specs; ``REASONING_SUMMARY=off`` asks
    for none. The caller names the specs — an agent, its whole sub-agent tree.
    """
    mode = settings.model_profiles.reasoning_summary
    if mode == "off":
        return
    for spec in sorted(set(specs)):
        if spec in _registered or not is_reasoning_model(spec):
            continue
        kwargs = reasoning_kwargs(spec, mode)
        register_provider_profile(spec, ProviderProfile(init_kwargs=kwargs))
        _registered.add(spec)
        logger.info(
            "reasoning_summary_registered",
            "Asked a reasoning model for its reasoning",
            model=spec,
            summary=mode,
            kwargs=sorted(kwargs),
        )
