"""The risk-classification agent (plan 02): code, one Gemini step, code, Iris, code.

A separate agent from the audit pipeline (``pipeline/``): it shares only
infrastructure (the Gemini model factory, deepagents, the reg-memory client,
the Iris client, Langfuse helpers), never the audit's step tables. Not a graph;
one fast pass, target under 60 s.

1. **Pin** the ``kb_version`` (the request's, else reg-memory's active release).
2. **Pre-checks** (code, ``prechecks.py`` + ``hints.yaml``). Hints, never answers.
3. **Provision texts** (code): the classification provisions and the guidance
   related to them, fetched concurrently at the pinned kb, go into the brief.
4. **classify_risk** (one Gemini deep agent; tools ``lookup_provision``,
   ``search_regulation``, ``read_guidance``) returns a :class:`RiskProposal`.
5. **Verifier** (code, ``verify.py``). Problems -> one automatic redo; still
   failing -> kept, listed, ``needs_human``.
6. **Iris** (Oumi, ``prompts/risk_classification.yaml``): an independent
   multiple-choice answer on the class + a profiling score. No Gemini fallback
   (it would grade itself): unavailable -> ``needs_human``.
7. **Compare** and **dates** (code).

Every phase is a Langfuse span under the run's own root span ``classify:<id>``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage
from pipeline.clients import PipelineHTTPError, RegMemory
from pipeline.decision import IrisClient, IrisError, choice_confidence

from classification import fakes
from classification.prechecks import (
    KbCache,
    brief_documents,
    brief_provisions,
    prechecks,
    provision_ids,
    related_guidance,
    resolve,
)
from classification.schemas import ClassificationResult, IrisCheck, KeyDate, RiskProposal
from classification.tools import regulation_tools
from classification.verify import classification_problems, normalise_citations
from core.logging import get_logger
from core.settings import settings
from harness.models.fake import ScriptedChatModel, tool_call_message
from harness.models.gemini import ModelRole, build_chat_model, is_fake, model_spec
from harness.observability import end_span, start_span

logger = get_logger(__name__)

STEP = "classify_risk"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
#: Model role of the step (parameters, not prose).
ROLE: ModelRole = "reasoning"
#: Recursion cap of the step's agent loop (model + tool turns).
RECURSION_LIMIT = 24
#: Attempts of one agent run (a provider hiccup or a missing result is retried once).
ATTEMPTS = 2
#: Longest text value in the brief.
MAX_BRIEF_TEXT = 12_000

#: The six options Iris scores (prompts/risk_classification.yaml).
IRIS_OPTIONS = (
    "prohibited",
    "high_risk_annex_i",
    "high_risk_annex_iii",
    "not_high_risk_6_3",
    "transparency_only",
    "minimal",
)


# ---- prompt and brief ---------------------------------------------------------------------


@cache
def _read(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


@cache
def iris_questions() -> dict[str, Any]:
    data = yaml.safe_load(_read("risk_classification.yaml"))
    if not isinstance(data, dict):
        raise ValueError("risk_classification.yaml holds no questions")
    return data


def compose_prompt(today: date) -> str:
    """Layered: rules -> agent instructions -> defaults -> date (precedence in the rules)."""
    return "\n\n".join(
        [
            f"<platform_rules>\n{_read('rules.md')}\n</platform_rules>",
            f"<agent_instructions>\n{_read('classify_risk.md')}\n</agent_instructions>",
            f"<defaults>\n{_read('method.md')}\n</defaults>",
            f"Today is {today:%A, %d %B %Y}.",
        ]
    )


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_BRIEF_TEXT:
        return value[:MAX_BRIEF_TEXT] + f"\n... [{len(value) - MAX_BRIEF_TEXT} more characters]"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


def render_brief(brief: dict[str, Any], feedback: dict[str, Any] | None) -> str:
    body = yaml.safe_dump(_clip(brief), sort_keys=False, allow_unicode=True, width=100)
    text = f"<brief>\n{body}</brief>"
    if feedback:
        lead = (
            "A human reviewer rejected the previous classification. Redo it taking the "
            "reason into account."
            if feedback.get("source") == "human"
            else "An automatic check failed on the previous attempt. Fix every problem listed."
        )
        fb = yaml.safe_dump(_clip(feedback), sort_keys=False, allow_unicode=True, width=100)
        text += f"\n\n<feedback>\n{lead}\n{fb}</feedback>"
    return text


# ---- the Gemini step ----------------------------------------------------------------------


class ClassifierStepFailed(RuntimeError):
    public_message = "The classifier did not return a result; it can be retried."


class ClassifierStep:
    """One deepagents run with the regulation tools and ``RiskProposal`` as its result tool."""

    def __init__(self, *, model_factory: Callable[[ModelRole], Any] | None = None) -> None:
        self.model_factory = model_factory or (lambda role: build_chat_model(role))

    def _model(self, fake: Callable[[], RiskProposal]) -> Any:
        if is_fake():
            script = [tool_call_message(RiskProposal.__name__, fake().model_dump(mode="json"))]
            return ScriptedChatModel(model=model_spec(ROLE), script=script)
        return self.model_factory(ROLE)

    async def run(
        self,
        brief: dict[str, Any],
        tools: list[Any],
        *,
        feedback: dict[str, Any] | None,
        fake: Callable[[], RiskProposal],
        config: Mapping[str, Any] | None = None,
    ) -> RiskProposal:
        agent = create_deep_agent(
            model=self._model(fake),
            tools=tools,
            system_prompt=compose_prompt(datetime.now(UTC).date()),
            response_format=ToolStrategy(RiskProposal),
            name="risk-classifier",
        )
        run_config: dict[str, Any] = {
            "recursion_limit": RECURSION_LIMIT,
            "run_name": f"step:{STEP}",
            "tags": ["classification", STEP],
            "metadata": {"step": STEP, "model": model_spec(ROLE)},
        }
        if config:
            for key in ("callbacks", "metadata"):
                if config.get(key) is not None:
                    run_config[key] = (
                        {**run_config["metadata"], **config[key]}
                        if key == "metadata"
                        else config[key]
                    )
        message = HumanMessage(content=render_brief(brief, feedback))
        last: Exception = ClassifierStepFailed("no result")
        for attempt in range(1, ATTEMPTS + 1):
            try:
                result = await agent.ainvoke({"messages": [message]}, config=run_config)
                structured = result.get("structured_response") if isinstance(result, dict) else None
                if structured is None:
                    raise ClassifierStepFailed("the agent ended without a result")
                return (
                    structured
                    if isinstance(structured, RiskProposal)
                    else RiskProposal.model_validate(structured)
                )
            except Exception as exc:
                last = exc
                logger.warning(
                    "classify_step_attempt_failed",
                    "Classifier attempt failed",
                    attempt=attempt,
                    failure_reason=type(exc).__name__,
                )
        raise last


# ---- Iris (independent check) -------------------------------------------------------------


def agent_option(result: RiskProposal) -> str:
    """The agent's (risk_class, route) as one of Iris's six options."""
    if result.risk_class == "prohibited":
        return "prohibited"
    if result.risk_class == "high_risk":
        return "high_risk_annex_i" if result.route == "art6_1_annex_i" else "high_risk_annex_iii"
    if result.route == "art6_3_exempt":
        return "not_high_risk_6_3"
    if result.route == "art50_only" or result.risk_class == "limited_risk":
        return "transparency_only"
    return "minimal"


def iris_state(
    card: Mapping[str, Any], pre: Mapping[str, Any], provisions: Mapping[str, Any]
) -> dict[str, Any]:
    keys = (
        "name",
        "description",
        "intended_purpose",
        "decision_informed",
        "affected_persons",
        "human_oversight",
        "deployment",
        "annex_i_product",
    )
    system = {k: card.get(k) for k in keys if card.get(k)}
    system["features"] = pre.get("features") or []
    system["profiling_declared"] = pre.get("profiling")
    texts = {pid: str(p.get("text") or "")[:600] for pid, p in provisions.items()}
    return {"system": system, "provisions": texts}


async def iris_check(
    iris: IrisClient | None,
    state: dict[str, Any],
    agent_choice: str,
    *,
    trace_id: str | None,
    parent_id: str | None,
) -> tuple[IrisCheck | None, str | None]:
    """Iris's answer, or ``(None, reason)`` when it is unavailable (never Gemini)."""
    if iris is None or not iris.configured:
        return None, "not_configured"
    span = start_span(
        "iris.decide",
        trace_id=trace_id,
        parent_id=parent_id,
        input={"task": "risk_classification", "state": state},
        metadata={"task": "risk_classification", "preferred": "iris"},
    )
    try:
        answers = await iris.ask(state, dict(iris_questions()))
        cls_answer = answers["risk_class"]
        probabilities = {
            str(k): float(v)
            for k, v in (cls_answer.get("probabilities") or {}).items()
            if isinstance(v, (int, float))
        }
        check = IrisCheck(
            choice=str(cls_answer["choice"]),
            probabilities=probabilities,
            confidence=choice_confidence(cls_answer),
            profiling=float(answers["profiling"]["noul"]),
            agent_choice=agent_choice,
        )
    except Exception as exc:
        failure = str(exc) if isinstance(exc, IrisError) else type(exc).__name__
        logger.warning("classify_iris_failed", "Iris could not check", failure_reason=failure)
        end_span(span, metadata={"failure": failure}, level="WARNING")
        return None, failure
    end_span(
        span,
        output=check.model_dump(mode="json"),
        metadata={"task": "risk_classification", "model": "iris", "verdict": check.choice},
    )
    return check, None


def compare(
    result: RiskProposal,
    check: IrisCheck | None,
    problems: list[str],
    iris_failure: str | None,
    min_confidence: float,
) -> tuple[bool | None, list[str]]:
    """Plan 02 §6.4: ``(agreement, needs_human reasons)``; any reason -> needs_human."""
    reasons: list[str] = []
    agreement: bool | None = None
    if check is None:
        reasons.append(f"independent check unavailable ({iris_failure or 'not_configured'})")
    else:
        agreement = check.choice == check.agent_choice
        if not agreement:
            reasons.append(f"Iris chose {check.choice}, the agent {check.agent_choice}")
        if check.confidence is not None and check.confidence < min_confidence:
            reasons.append(f"Iris confidence {check.confidence:.2f} < {min_confidence:.2f}")
        if check.profiling is not None and check.profiling > 0.5 and result.art6_3.holds:
            reasons.append(
                f"Iris thinks it profiles people (p={check.profiling:.2f}) but Art. 6(3) is claimed"
            )
    if result.confidence < min_confidence:
        reasons.append(f"agent confidence {result.confidence:.2f} < {min_confidence:.2f}")
    if problems:
        reasons.append(f"{len(problems)} verifier problem(s) left after the redo")
    return agreement, reasons


# ---- dates (code) -------------------------------------------------------------------------


def date_targets(result: RiskProposal) -> list[tuple[str, str, str | None]]:
    """``(what, provision id, valid_from_by_basis family)`` for the route's core provisions."""
    route = result.route
    out: list[tuple[str, str, str | None]] = []
    if route == "art5":
        out.append(("Prohibition applies (Art. 5)", "AIA.5", None))
    elif route == "art6_2_annex_iii":
        out.append(("High-risk obligations apply (Art. 6(2), Annex III)", "AIA.6.2", "annex_iii"))
        out.append(("Annex III point applies", result.annex_basis_id or "AIA.ANNEX_III", None))
    elif route == "art6_1_annex_i":
        out.append(("High-risk obligations apply (Art. 6(1), Annex I)", "AIA.6.1", "annex_i"))
    elif route == "art6_3_exempt":
        out.append(("Art. 6(4) assessment duty applies", "AIA.6.4", "annex_iii"))
        out.append(("Registration under Art. 49(2) applies", "AIA.49.2", None))
    if route == "art50_only" or result.transparency.features or result.transparency.provisions:
        out.append(("Transparency duties apply (Art. 50)", "AIA.50", None))
    return out


def key_dates(result: RiskProposal, kb: KbCache) -> list[KeyDate]:
    dates = []
    for what, pid, family in date_targets(result):
        node = kb.nodes.get(pid) or {}
        by_basis = node.get("valid_from_by_basis")
        when = (by_basis or {}).get(family) if family and isinstance(by_basis, dict) else None
        when = when or node.get("valid_from")
        amended = node.get("amended_by")
        dates.append(
            KeyDate(
                what=what,
                date=str(when) if when else None,
                provision_id=pid,
                amended_by=[str(a) for a in amended] if isinstance(amended, list) else [],
            )
        )
    return dates


# ---- the run ------------------------------------------------------------------------------


@dataclass
class ClassifyRequest:
    classification_id: str
    system_id: str
    card: dict[str, Any]
    documents: list[dict[str, Any]] = field(default_factory=list)
    kb_version: str | None = None
    feedback: dict[str, Any] | None = None


@dataclass
class Tracing:
    """The run's own Langfuse trace: its id, the root span, the step's callbacks."""

    trace_id: str | None = None
    root_id: str | None = None
    step_config: Mapping[str, Any] | None = None


class KbUnavailable(RuntimeError):
    """reg-memory could not pin a kb or serve the classification provisions."""

    public_message = "reg-memory is unavailable; the classification can be retried."


def _span(name: str, tracing: Tracing, payload: Any) -> Any:
    return start_span(name, trace_id=tracing.trace_id, parent_id=tracing.root_id, input=payload)


async def classify(
    req: ClassifyRequest,
    *,
    regmem: RegMemory,
    step: ClassifierStep | None = None,
    iris: IrisClient | None = None,
    tracing: Tracing | None = None,
) -> ClassificationResult:
    """One classification. Raises :class:`KbUnavailable` or the step's error."""
    tracing = tracing or Tracing()
    step = step or ClassifierStep()
    try:
        version = req.kb_version or await regmem.active_kb_version()
    except PipelineHTTPError as exc:
        raise KbUnavailable(exc.public) from exc
    kb = KbCache(kb_version=version)

    span = _span("classify.prechecks", tracing, {"card": req.card})
    pre = prechecks(req.card, req.documents)
    ids = provision_ids(pre)
    await resolve(regmem, kb, ids)
    if not any(kb.known(i) for i in ids):
        end_span(span, output={"prechecks": pre, "error": "no provisions"}, level="ERROR")
        raise KbUnavailable("no classification provision could be read")
    anchors = ["AIA.6.3", *[c["provision"] for c in pre["annex_iii_candidates"]]]
    guidance = await related_guidance(regmem, version, anchors)
    for g in guidance:  # listed guidance exists at the kb (its id came from it)
        kb.nodes.setdefault(g["id"], {**g, "kb_version": version})
    provisions = brief_provisions(kb, ids)
    end_span(span, output={"prechecks": pre, "provisions": list(provisions), "guidance": guidance})

    brief: dict[str, Any] = {
        "classification_id": req.classification_id,
        "kb_version": version,
        "system": req.card,
        "prechecks": pre,
        "provisions": provisions,
        "related_guidance": guidance,
        "documents": brief_documents(req.documents),
    }
    human = None
    if req.feedback and str(req.feedback.get("reason") or "").strip():
        if req.feedback.get("source", "human") == "human":
            human = {"source": "human", "reason": str(req.feedback["reason"])}
        else:  # e.g. a stale re-run: context, not a rejection
            brief["previous_run_note"] = str(req.feedback["reason"])
    tools = regulation_tools(regmem, kb)

    async def run_step(feedback: dict[str, Any] | None) -> RiskProposal:
        return await step.run(
            brief,
            tools,
            feedback=feedback,
            fake=lambda: fakes.classify_risk(brief),
            config=tracing.step_config,
        )

    async def verify(proposal: RiskProposal, attempt: int) -> list[str]:
        vspan = _span("classify.verify", tracing, {"attempt": attempt})
        await resolve(regmem, kb, [c.id for c in proposal.citations])
        found = classification_problems(proposal, kb.nodes, pre)
        end_span(vspan, output={"problems": found}, level="WARNING" if found else None)
        return found

    proposal = await run_step(human)
    problems = await verify(proposal, 1)
    if problems:
        redo: dict[str, Any] = {"source": "verifier", "problems": problems}
        if human:
            redo["human_reason"] = human["reason"]
        proposal = await run_step(redo)
        problems = await verify(proposal, 2)

    check, failure = await iris_check(
        iris,
        iris_state(req.card, pre, provisions),
        agent_option(proposal),
        trace_id=tracing.trace_id,
        parent_id=tracing.root_id,
    )
    min_conf = settings.pipeline.classify_iris_min_confidence
    agreement, reasons = compare(proposal, check, problems, failure, min_conf)

    await resolve(regmem, kb, [pid for _, pid, _ in date_targets(proposal)])
    data = proposal.model_dump()
    data["citations"] = [c.model_dump() for c in normalise_citations(proposal, kb)]
    result = ClassificationResult(
        **data,
        classification_id=req.classification_id,
        system_id=req.system_id,
        kb_version=version,
        prechecks=pre,
        key_dates=key_dates(proposal, kb),
        iris=check,
        agreement=agreement,
        needs_human=bool(reasons),
        needs_human_reasons=reasons,
        verifier_problems=problems,
        decided_by="gemini+iris" if check is not None else "gemini",
        trace_id=tracing.trace_id,
    )
    logger.info(
        "classification_proposed",
        "Risk classification proposed",
        classification_id=req.classification_id,
        system_id=req.system_id,
        risk_class=result.risk_class,
        route=result.route,
        needs_human=result.needs_human,
        agreement=agreement,
    )
    return result


__all__ = [
    "IRIS_OPTIONS",
    "ClassifierStep",
    "ClassifyRequest",
    "KbUnavailable",
    "Tracing",
    "agent_option",
    "classify",
    "compare",
    "compose_prompt",
    "date_targets",
    "iris_check",
    "key_dates",
]
