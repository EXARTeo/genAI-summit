"""The system's findings register in the pipeline (hydration).

The backend keeps one register row per (system, obligation) across audits
(``GET /internal/audits/{id}/register``). ``load_context`` reads it into the
run state (``register``); the assess, critic and report briefs carry a compact
view (:func:`register_brief`): open gaps must be re-tested and reported as
still open or fixed, human-closed items are accepted risks (not new findings,
but a worse verdict is reported). The ``seal`` step stamps each finding with
its ``register_status`` (:func:`annotate`), mirroring the backend's rules
(``utils/register.py``): ``new | still_open | resolved | regressed |
accepted_risk | unchanged``.
"""

from __future__ import annotations

from typing import Any

from core.logging import get_logger

logger = get_logger(__name__)

GAP_VERDICTS = {"gap", "partial"}
BADNESS = {
    "pass": 0,
    "not_applicable": 0,
    "not_assessable_by_testing": 0,
    "inconclusive": 1,
    "partial": 2,
    "gap": 3,
}
#: Most items of each kind a brief carries.
MAX_BRIEF_ITEMS = 40


async def load_register(backend: Any) -> list[dict[str, Any]]:
    """The register's items (best effort: an older backend or an error gives ``[]``)."""
    fetch = getattr(backend, "register", None)
    if fetch is None:
        return []
    try:
        body = await fetch()
    except Exception as exc:
        logger.warning(
            "pipeline_register_unavailable",
            "Findings register unavailable",
            failure_reason=type(exc).__name__,
        )
        return []
    items = (body or {}).get("items") if isinstance(body, dict) else None
    return [i for i in items or [] if isinstance(i, dict) and i.get("obligation_id")]


def _badness(verdict: str | None, gap_id: str | None = None) -> int:
    base = BADNESS.get(str(verdict), 1)
    return max(base, 2) if gap_id and verdict not in GAP_VERDICTS else base


def _ever_open(item: dict[str, Any]) -> bool:
    return any(e.get("to") == "open" for e in item.get("history") or [])


def _closed_verdict(item: dict[str, Any]) -> str | None:
    for event in reversed(item.get("history") or []):
        if event.get("kind") == "closed":
            return event.get("verdict")
    return item.get("verdict")


def register_status(item: dict[str, Any] | None, verdict: str, gap_id: str | None = None) -> str:
    """What this audit's verdict means for the register item before it."""
    gap = verdict in GAP_VERDICTS or bool(gap_id)
    if item is None:
        return "new"
    state = item.get("state")
    if state == "open":
        return "resolved" if verdict == "pass" else "still_open"
    if state == "closed":
        if verdict == "pass":
            return "resolved"
        if _badness(verdict, gap_id) > _badness(_closed_verdict(item), item.get("gap_id")):
            return "regressed"
        return "accepted_risk"
    if gap or verdict == "inconclusive":
        return "regressed" if _ever_open(item) else "new"
    return "unchanged"


def annotate(proposed: list[dict[str, Any]], register: list[dict[str, Any]] | None) -> None:
    """Stamp each proposed finding with ``register_status`` (+ since when it is tracked)."""
    by_id = {i["obligation_id"]: i for i in register or []}
    for finding in proposed:
        item = by_id.get(finding.get("obligation_id"))
        finding["register_status"] = register_status(
            item, str(finding.get("verdict")), finding.get("gap_id")
        )
        if item is not None:
            finding["register_since"] = item.get("first_seen_audit_id")
            finding["register_state_before"] = item.get("state")


def _brief_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        k: item.get(k)
        for k in (
            "obligation_id",
            "article",
            "verdict",
            "severity",
            "first_seen_audit_id",
            "opened_at",
            "last_seen_audit_id",
            "last_reasoning",
        )
        if item.get(k) is not None
    }


def register_brief(register: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The compact register view a step brief carries (``None`` when it is empty)."""
    items = register or []
    if not items:
        return None
    open_items = [i for i in items if i.get("state") == "open"]
    closed = [i for i in items if i.get("state") == "closed"]
    return {
        "note": (
            "State of this system from earlier audits. Re-test every open item and say "
            "whether it is still open or fixed. Accepted risks were closed by a human with "
            "the reason given: do not raise them as new; report only a worse verdict."
        ),
        "open": [_brief_item(i) for i in open_items[:MAX_BRIEF_ITEMS]],
        "accepted_risks": [
            {
                **_brief_item(i),
                "closed_by": i.get("closed_by"),
                "close_reason": i.get("close_reason"),
                "closed_at": i.get("closed_at"),
            }
            for i in closed[:MAX_BRIEF_ITEMS]
        ],
        "resolved": [i["obligation_id"] for i in items if i.get("state") == "resolved"][
            :MAX_BRIEF_ITEMS
        ],
    }


def for_obligations(
    register: list[dict[str, Any]] | None, obligation_ids: set[str]
) -> list[dict[str, Any]]:
    """The register items of the given obligations (a step's slice)."""
    return [i for i in register or [] if i.get("obligation_id") in obligation_ids]


__all__ = [
    "annotate",
    "for_obligations",
    "load_register",
    "register_brief",
    "register_status",
]
