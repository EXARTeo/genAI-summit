"""The decision model: narrow, multiple-choice judgements, Oumi *Iris* first, Gemini as fallback.

Oumi's **Iris** is a *decision model* (docs.oumi.ai, "Decision models" and "Iris"):
it does not generate text, it scores the options of each question about a state.

* ``POST {OUMI_BASE_URL}/systemone`` (default ``https://inference.oumi.ai/v1``),
  header ``X-API-Key``, body ``{model, state, questions}``;
  ``model = projects/<project_id>/models/iris-latest`` (``OUMI_MODEL``).
* A question is ``{type: noul | choice | score, instructions, criteria}``; the
  answer is ``{choice, confidence, probabilities}`` for a choice and ``{noul}``
  (P(true)) for a yes/no question.

:meth:`DecisionModel.decide` runs one :class:`DecisionTask` (the questions, how
the answers become the task's result model, the Gemini step and the fake) and
returns a typed :class:`Decision`. Any Iris failure (not configured, an HTTP
error, an answer that does not parse or validate) falls back to the task's
Gemini step (the scripted fake under ``AGENTS_FAKE_LLM``), logged, so swapping
the decision model never breaks a pipeline. Iris is a separate provider: it is
called whenever it is configured, also in fake-LLM mode (only Gemini is faked).

Every call is one Langfuse span ``iris.decide`` (model, verdict, latency,
fallback flag) in the audit's trace, fail-open.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal, TypeVar

import httpx
import yaml
from pydantic import BaseModel

from core.logging import get_logger
from core.settings import settings
from harness.observability import end_span, start_span
from pipeline.steps import StepRunner, StepScope

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)
ModelName = Literal["iris", "gemini"]

DECISIONS_DIR = Path(__file__).resolve().parent / "prompts" / "decisions"
SPAN_NAME = "iris.decide"


@cache
def load_questions(name: str) -> dict[str, Any]:
    """``prompts/decisions/<name>.yaml``: the Iris questions of one task (parameters)."""
    data = yaml.safe_load((DECISIONS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{name}.yaml holds no questions")
    return data


class IrisError(RuntimeError):
    """Iris could not answer (not configured, HTTP error, malformed answer)."""


@dataclass(frozen=True)
class DecisionTask[T: BaseModel]:
    """One kind of decision: what Iris is asked and how its answer becomes ``T``.

    ``iris_request(brief) -> (state, questions)``; ``from_iris(answers, brief) -> T``
    (raises on an answer it cannot use); ``step`` is the Gemini fallback's
    ``StepRunner`` step (its result model is ``T``); ``fake(brief) -> T`` is the
    scripted output under ``AGENTS_FAKE_LLM``; ``verdict(result)`` names the
    outcome on the span and in the log.
    """

    name: str
    step: str
    iris_request: Callable[[dict[str, Any]], tuple[Any, dict[str, Any]]]
    from_iris: Callable[[dict[str, Any], dict[str, Any]], T]
    fake: Callable[[dict[str, Any]], T]
    verdict: Callable[[T], str]


@dataclass(frozen=True)
class Decision[T: BaseModel]:
    """A decision and who made it (``fallback``: Iris was asked and failed)."""

    result: T
    model: ModelName
    fallback: bool
    latency_ms: int
    failure: str | None = None


class IrisClient:
    """Oumi's ``/systemone`` endpoint (the key goes only to ``OUMI_BASE_URL``)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings.pipeline
        self.base_url = (base_url if base_url is not None else cfg.oumi_base_url).rstrip("/")
        self.model = model if model is not None else cfg.oumi_model
        self._key = api_key if api_key is not None else cfg.oumi_api_key.get_secret_value()
        self.timeout = timeout or cfg.oumi_timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self._key)

    async def ask(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        """The ``answers`` map, checked against the questions (else :class:`IrisError`)."""
        if not self.configured:
            raise IrisError("not_configured")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(
                f"{self.base_url}/systemone",
                headers={"X-API-Key": self._key, "Content-Type": "application/json"},
                json={"model": self.model, "state": state, "questions": questions},
            )
        if response.status_code >= 400:
            raise IrisError(f"http_{response.status_code}")
        try:
            answers = response.json()["answers"]
        except (ValueError, KeyError, TypeError) as exc:
            raise IrisError("malformed_response") from exc
        if not isinstance(answers, dict):
            raise IrisError("malformed_response")
        for key, question in questions.items():
            answer = answers.get(key)
            if not isinstance(answer, dict):
                raise IrisError(f"missing_answer:{key}")
            kind = question.get("type")
            if kind == "choice" and answer.get("choice") not in (question.get("criteria") or {}):
                raise IrisError(f"bad_choice:{key}")
            if kind == "noul" and not isinstance(answer.get("noul"), (int, float)):
                raise IrisError(f"bad_noul:{key}")
        return answers


def choice_confidence(answer: dict[str, Any]) -> float | None:
    """Iris's confidence in its pick, clamped to [0, 1] (None when absent)."""
    value = answer.get("confidence")
    if not isinstance(value, (int, float)):
        value = (answer.get("probabilities") or {}).get(answer.get("choice"))
    return None if not isinstance(value, (int, float)) else max(0.0, min(1.0, float(value)))


class DecisionModel:
    """Runs decision tasks on the preferred model with the Gemini fallback."""

    def __init__(
        self,
        preferred: ModelName = "iris",
        *,
        steps: StepRunner | None = None,
        iris: IrisClient | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.preferred: ModelName = preferred
        self.steps = steps or StepRunner()
        self.iris = iris or IrisClient()
        self.trace_id = trace_id

    @property
    def name(self) -> ModelName:
        return self.preferred

    async def decide(
        self, task: DecisionTask[T], brief: dict[str, Any], schema: type[T], scope: StepScope
    ) -> Decision[T]:
        """One decision: Iris when preferred (validated as ``schema``), else/fallback Gemini."""
        started = time.monotonic()
        span = start_span(
            SPAN_NAME,
            trace_id=self.trace_id,
            input={"task": task.name, "brief": brief},
            metadata={"task": task.name, "preferred": self.preferred},
        )
        result: T | None = None
        model: ModelName = "gemini"
        failure: str | None = None
        if self.preferred == "iris":
            try:
                state, questions = task.iris_request(brief)
                answers = await self.iris.ask(state, questions)
                result = schema.model_validate(task.from_iris(answers, brief).model_dump())
                model = "iris"
            except Exception as exc:
                failure = str(exc) if isinstance(exc, IrisError) else type(exc).__name__
                logger.warning(
                    "iris_decision_failed",
                    "Iris could not decide; falling back to Gemini",
                    task=task.name,
                    failure_reason=failure,
                )
        if result is None:
            raw = await self.steps.run(task.step, brief, scope, fake=lambda: task.fake(brief))
            result = raw if isinstance(raw, schema) else schema.model_validate(raw.model_dump())
        latency_ms = int((time.monotonic() - started) * 1000)
        fallback = self.preferred == "iris" and model != "iris"
        verdict = task.verdict(result)
        logger.info(
            "decision_made",
            "Decision model answered",
            task=task.name,
            model=model,
            verdict=verdict,
            fallback=fallback,
            latency_ms=latency_ms,
        )
        end_span(
            span,
            output=result.model_dump(mode="json"),
            metadata={
                "task": task.name,
                "model": model,
                "verdict": verdict,
                "latency_ms": latency_ms,
                "fallback": fallback,
                "failure": failure,
                "iris_model": self.iris.model if model == "iris" else None,
            },
            level="WARNING" if fallback else None,
        )
        return Decision(
            result=result, model=model, fallback=fallback, latency_ms=latency_ms, failure=failure
        )


__all__ = [
    "Decision",
    "DecisionModel",
    "DecisionTask",
    "IrisClient",
    "IrisError",
    "ModelName",
    "choice_confidence",
    "load_questions",
]
