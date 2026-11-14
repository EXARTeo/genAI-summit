"""Model access: Google Gemini only, through LangChain's Google GenAI integration.

Two roles, chosen by the step, never by the model:

* ``default``   ``GEMINI_MODEL`` (``gemini-3.5-flash-lite``): every step.
* ``reasoning`` ``GEMINI_MODEL_REASONING`` (empty = the default model): the
  judgement-heavy steps (planning, critic, change judge).

``AGENTS_FAKE_LLM=true`` returns a deterministic stub instead
(:mod:`harness.models.fake`), so a dry run or a demo without a key never calls
a provider. Without a key and without the flag, building a model raises
:class:`ModelNotConfiguredError`, whose ``public_message`` reaches the UI as the
run's error (never a crash, never a traceback).

Declarative chat agents name their model as a spec (``google_genai:<model>``);
:func:`ensure_specs_configured` checks those before deepagents resolves them and
exports the key where ``init_chat_model`` reads it.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel

from core.settings import settings

ModelRole = Literal["default", "reasoning"]

#: The LangChain provider prefix of a Gemini spec (``google_genai:gemini-...``).
GOOGLE_PROVIDER = "google_genai"


class ModelNotConfiguredError(RuntimeError):
    """No Gemini key: the run stops with a message the user can act on."""

    public_message = (
        "The language model is not configured: set GOOGLE_API_KEY in .env (Gemini), "
        "or AGENTS_FAKE_LLM=true for a dry run, and restart the agents service."
    )

    def __init__(self) -> None:
        super().__init__(self.public_message)


def model_name(role: ModelRole = "default") -> str:
    """The Gemini model id a role runs on."""
    gemini = settings.gemini
    if role == "reasoning" and gemini.reasoning_model:
        return gemini.reasoning_model
    return gemini.model


def model_spec(role: ModelRole = "default") -> str:
    """The ``provider:model`` spec of a role (Langfuse tags, provenance, artifacts)."""
    if settings.gemini.fake_llm:
        return f"fake:{model_name(role)}"
    return f"{GOOGLE_PROVIDER}:{model_name(role)}"


def is_fake() -> bool:
    return settings.gemini.fake_llm


def _api_key() -> str:
    return settings.api_keys.google.get_secret_value()


def is_configured() -> bool:
    """A real model can be built (a key is set) or the stub is on."""
    return is_fake() or bool(_api_key())


def build_chat_model(role: ModelRole = "default", **overrides: Any) -> BaseChatModel:
    """A Gemini chat model for ``role``; raises :class:`ModelNotConfiguredError` without a key.

    In fake mode the caller supplies the stub (it knows the step's expected
    output); this function is for real models only.
    """
    key = _api_key()
    if not key:
        raise ModelNotConfiguredError()
    # Imported here: the package is heavy and only a real run needs it.
    from langchain_google_genai import ChatGoogleGenerativeAI

    gemini = settings.gemini
    kwargs: dict[str, Any] = {
        "model": model_name(role),
        "google_api_key": key,
        "timeout": gemini.timeout_seconds,
        "max_retries": gemini.max_retries,
    }
    if gemini.temperature is not None:
        kwargs["temperature"] = gemini.temperature
    kwargs.update(overrides)
    return ChatGoogleGenerativeAI(**kwargs)


def ensure_specs_configured(specs: Iterable[str]) -> None:
    """Before a declarative agent resolves ``google_genai:*`` specs: key present, exported.

    ``init_chat_model`` reads ``GOOGLE_API_KEY`` from the environment, while the
    settings also accept ``GOOGLE_API_KEY_FILE``; exporting closes that gap.
    """
    if not any(str(spec).startswith(f"{GOOGLE_PROVIDER}:") for spec in specs):
        return
    key = _api_key()
    if not key:
        raise ModelNotConfiguredError()
    os.environ.setdefault("GOOGLE_API_KEY", key)


__all__ = [
    "GOOGLE_PROVIDER",
    "ModelNotConfiguredError",
    "ModelRole",
    "build_chat_model",
    "ensure_specs_configured",
    "is_configured",
    "is_fake",
    "model_name",
    "model_spec",
]
