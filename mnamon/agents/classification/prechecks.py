"""Deterministic pre-checks and the regulation the classifier reads (plan 02 §6.1, P2).

Pre-checks are **hints, never answers**: Annex III candidates, Art. 5 red flags,
Art. 50 features, profiling, the role hint, the Annex I flag and a doubt that
the system is an AI system at all. The keyword tables are data
(``hints.yaml``). The provision texts and related guidance are fetched
concurrently at the pinned ``kb_version`` into a :class:`KbCache`, which the
verifier and the dates reuse.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pipeline.clients import PipelineHTTPError, RegMemory

from core.logging import get_logger

logger = get_logger(__name__)

HINTS_PATH = Path(__file__).resolve().parent / "hints.yaml"

#: Provisions every run reads (their text goes into the brief).
CORE_PROVISIONS = (
    "AIA.3.1",
    "AIA.3.3",
    "AIA.3.4",
    "AIA.5.1",
    "AIA.6.1",
    "AIA.6.2",
    "AIA.6.3",
    "AIA.6.3.a",
    "AIA.6.3.b",
    "AIA.6.3.c",
    "AIA.6.3.d",
    "AIA.6.4",
    "AIA.25.1",
)
#: Longest provision text kept in the brief (the agent can look up the rest).
PROVISION_TEXT_CHARS = 1_500
#: Guidance listed in the brief (ids + titles; the agent reads them with read_guidance).
MAX_GUIDANCE = 12
#: Document text the step sees (the backend truncates too; this is the guard).
DOC_CHARS = 6_000
DOCS_TOTAL_CHARS = 30_000
#: How many Annex III points become candidates.
MAX_CANDIDATES = 3

#: Card fields whose words the pre-checks read.
TEXT_FIELDS = (
    "name",
    "description",
    "intended_purpose",
    "decision_informed",
    "decision",
    "affected_persons",
    "vulnerable_groups",
    "human_oversight",
    "deployment",
    "users",
    "outputs",
)


@cache
def load_hints() -> dict[str, Any]:
    data = yaml.safe_load(HINTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("classification/hints.yaml is empty")
    return data


@cache
def _word_re(keyword: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])")


def _matches(text: str, keywords: list[Any]) -> list[str]:
    return [str(k) for k in keywords if _word_re(str(k)).search(text)]


def _flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flatten(v)]
    return []


def card_features(card: Mapping[str, Any]) -> list[str]:
    raw = card.get("features") or []
    items = raw if isinstance(raw, list) else [raw]
    return sorted({str(f).strip() for f in items if str(f).strip()})


def dossier_text(card: Mapping[str, Any], documents: list[Mapping[str, Any]]) -> str:
    """The words the pre-checks read: the card's descriptive fields, features, doc titles."""
    parts = [s for key in TEXT_FIELDS for s in _flatten(card.get(key))]
    parts += [f.replace("_", " ") for f in card_features(card)]
    parts += [Path(str(d.get("path") or "")).stem.replace("-", " ") for d in documents]
    return " \n".join(parts).lower()


def annex_point_id(point: str) -> str:
    return f"AIA.ANNEX_III.{point}"


def annex_label(point: str) -> str:
    """``4.a`` -> ``Annex III 4(a)``; ``2`` -> ``Annex III 2``."""
    head, _, tail = point.partition(".")
    return f"Annex III {head}({tail})" if tail else f"Annex III {head}"


def _profiling(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    text = str(value or "").strip().lower()
    if text in {"yes", "true", "y"}:
        return "yes"
    if text in {"no", "false", "n"}:
        return "no"
    return "unknown"


def role_hint(card: Mapping[str, Any]) -> str:
    """How the system was obtained -> ``provider`` / ``deployer`` / ``provider_by_art25``."""
    acquisition = str(card.get("acquisition") or "").lower().replace("-", "_")
    if not acquisition:
        role = str(card.get("role") or "").lower()
        return role if role in {"provider", "deployer"} else "provider"
    for group in load_hints()["acquisition_roles"]:
        words = [str(w).lower().replace("-", "_") for w in group["words"]]
        if any(w in acquisition for w in words):
            return str(group["role"])
    return "provider"


def prechecks(card: Mapping[str, Any], documents: list[Mapping[str, Any]]) -> dict[str, Any]:
    """The deterministic hints (plan 02 §6.1). The agent confirms or rejects each one."""
    hints = load_hints()
    text = dossier_text(card, documents)
    candidates = []
    for point, entry in (hints.get("annex_iii") or {}).items():
        matched = _matches(text, list(entry.get("keywords") or []))
        if matched:
            candidates.append(
                {
                    "point": str(point),
                    "provision": annex_point_id(str(point)),
                    "title": entry.get("title"),
                    "matched": matched,
                }
            )
    candidates.sort(key=lambda c: -len(c["matched"]))
    flags = []
    for provision, entry in (hints.get("art5") or {}).items():
        groups = [_matches(text, list(g)) for g in entry.get("all") or []]
        if groups and all(groups):
            flags.append(
                {
                    "provision": provision,
                    "title": entry.get("title"),
                    "matched": [w for g in groups for w in g],
                }
            )
    product = str(card.get("annex_i_product") or "").strip()
    return {
        "annex_iii_candidates": candidates[:MAX_CANDIDATES],
        "art5_flags": flags,
        "features": card_features(card),
        "profiling": _profiling(card.get("profiling")),
        "role_hint": role_hint(card),
        "annex_i": {"flag": bool(product), "product_law": product or None},
        "ai_system_doubt": not _matches(text, list(hints.get("ai_system_words") or [])),
    }


def provision_ids(pre: Mapping[str, Any]) -> list[str]:
    """The provisions whose text goes into the brief."""
    ids = list(CORE_PROVISIONS)
    ids += [f["provision"] for f in pre.get("art5_flags") or []]
    ids += [c["provision"] for c in pre.get("annex_iii_candidates") or []]
    if pre.get("features"):
        ids += ["AIA.50.1", "AIA.50.2", "AIA.50.3"]
    return list(dict.fromkeys(ids))


# ---- reading the kb -----------------------------------------------------------------------


@dataclass
class KbCache:
    """What the run read from reg-memory at its kb (``None`` = does not exist there)."""

    kb_version: str | None
    nodes: dict[str, dict[str, Any] | None] = field(default_factory=dict)

    def known(self, node_id: str) -> bool:
        return self.nodes.get(node_id) is not None


async def _node(regmem: RegMemory, kb: KbCache, node_id: str) -> dict[str, Any] | None:
    try:
        if node_id.startswith("INT."):
            body = await regmem.interpretation(node_id, kb.kb_version)
        else:
            body = await regmem.provision(node_id, kb.kb_version)
    except PipelineHTTPError as exc:
        if exc.status == 404:
            kb.nodes[node_id] = None
            return None
        raise
    kb.nodes[node_id] = body if isinstance(body, dict) and body.get("id") else None
    return kb.nodes[node_id]


async def resolve(regmem: RegMemory, kb: KbCache, ids: list[str]) -> None:
    """Fetch every id not yet in the cache, concurrently (a 404 is cached as missing)."""
    todo = [i for i in dict.fromkeys(ids) if i and i not in kb.nodes]
    results = await asyncio.gather(*(_node(regmem, kb, i) for i in todo), return_exceptions=True)
    for node_id, result in zip(todo, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "classify_node_unavailable",
                "Could not read a regulation node",
                node_id=node_id,
                failure_reason=type(result).__name__,
            )


def brief_provisions(kb: KbCache, ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node_id in ids:
        node = kb.nodes.get(node_id)
        if not node:
            continue
        text = str(node.get("text") or "")
        clipped = text[:PROVISION_TEXT_CHARS] + (" ..." if len(text) > PROVISION_TEXT_CHARS else "")
        children = [c if isinstance(c, str) else c.get("id") for c in node.get("children") or []]
        out[node_id] = {"title": node.get("title"), "text": clipped, "children": children[:12]}
    return out


async def related_guidance(
    regmem: RegMemory, kb_version: str | None, anchors: list[str]
) -> list[dict[str, Any]]:
    """Guidance (INT.*) relating to the anchors: id, title, binding, status (no text)."""
    results = await asyncio.gather(
        *(regmem.interpretations(a, kb_version) for a in anchors), return_exceptions=True
    )
    seen: dict[str, dict[str, Any]] = {}
    for anchor, items in zip(anchors, results, strict=True):
        if isinstance(items, BaseException):
            continue
        for item in items:
            gid = str(item.get("id") or "")
            if gid and gid not in seen:
                relates = [str(r) for r in item.get("relates_to") or []]
                seen[gid] = {
                    "id": gid,
                    "title": item.get("title"),
                    "binding": item.get("binding") is True,
                    "status": item.get("status") or "final",
                    "relates_to": relates[:8],
                    "specific": len(relates) <= 8,
                    "found_via": anchor,
                }
    # Narrow guidance (few relates_to, e.g. a worked example) before whole documents.
    ranked = sorted(seen.values(), key=lambda g: (not g.pop("specific"), g["id"]))
    return ranked[:MAX_GUIDANCE]


def brief_documents(documents: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    budget = DOCS_TOTAL_CHARS
    for doc in documents:
        text = str(doc.get("text") or "")[: min(DOC_CHARS, max(budget, 0))]
        budget -= len(text)
        out.append({"path": doc.get("path"), "version": doc.get("version"), "text": text})
    return out


__all__ = [
    "CORE_PROVISIONS",
    "KbCache",
    "annex_label",
    "annex_point_id",
    "brief_documents",
    "brief_provisions",
    "load_hints",
    "prechecks",
    "provision_ids",
    "related_guidance",
    "resolve",
]
