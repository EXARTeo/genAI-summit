"""The independent per-obligation verdict: Oumi *Iris* first, Gemini only when Iris is down.

Runs in ``assess_obligations`` for every tested obligation. Iris sees the
obligation (id, article, summary) and its test rows (metric, value, CI, the
organisation's threshold, synthkit's status) and picks ``pass | partial | gap |
inconclusive`` (``prompts/decisions/obligation_verdict.yaml``). It never sees
the rule verdict or Gemini's proposal: the code compares the three
(``pipeline/verdicts.combine``). A Gemini fallback is recorded on the finding
(``judges.iris.model = gemini``, ``fallback: true``).
"""

from __future__ import annotations

from typing import Any

from pipeline.decision import DecisionTask, choice_confidence, load_questions
from pipeline.schemas import VerdictJudgement
from pipeline.verdicts import rule_verdict

#: Most test rows sent per obligation.
MAX_ROWS = 16


def judge_brief(entry: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the independent judge sees: the obligation and its rows (no proposal)."""
    return {
        "obligation": {
            k: entry.get(k) for k in ("obligation_id", "article", "summary", "verification_mode")
        },
        "tests": [
            {
                "id": r.get("id"),
                "metric": r.get("metric"),
                "value": r.get("value"),
                "ci95": r.get("ci95"),
                "n": r.get("n"),
                "threshold": {k: (r.get("threshold") or {}).get(k) for k in ("op", "value", "text")}
                if r.get("threshold")
                else None,
                "status": r.get("status"),
            }
            for r in rows[:MAX_ROWS]
        ],
        "thresholds": "organisational (system card org_thresholds / declared_metrics); "
        "the AI Act sets no numbers",
    }


def _iris_request(brief: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    return brief, {"verdict": load_questions("obligation_verdict")["verdict"]}


def _from_iris(answers: dict[str, Any], brief: dict[str, Any]) -> VerdictJudgement:
    answer = answers["verdict"]
    verdict = answer["choice"]
    p = float((answer.get("probabilities") or {}).get(verdict, 0) or 0)
    return VerdictJudgement(
        verdict=verdict,
        rationale=f"Iris: {verdict} (p={p:.2f}) over {len(brief.get('tests') or [])} test rows.",
        confidence=choice_confidence(answer),
    )


def fake_judgement(brief: dict[str, Any]) -> VerdictJudgement:
    """Deterministic judge under ``AGENTS_FAKE_LLM``: the rule over the rows it was given."""
    rows = [{**t, "threshold": t.get("threshold") or None} for t in brief.get("tests") or []]
    verdict, why = rule_verdict(rows)
    return VerdictJudgement(verdict=verdict, rationale=why[:300], confidence=0.7)


VERDICT_JUDGE: DecisionTask[VerdictJudgement] = DecisionTask(
    name="obligation_verdict",
    step="verdict_judge",
    iris_request=_iris_request,
    from_iris=_from_iris,
    fake=fake_judgement,
    verdict=lambda r: r.verdict,
)

__all__ = ["VERDICT_JUDGE", "fake_judgement", "judge_brief"]
