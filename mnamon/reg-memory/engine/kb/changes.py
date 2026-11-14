"""Provision-level diff between two kb releases -> RegChange.

Nodes (provisions + interpretations) are compared by ``content_hash``. Each
changed / added / removed node gets a ``change_type``:

    editorial | substantive | date | scope | new_interpretation

from Gemini (one batched structured call, with a one-line rationale) or, with no
key or on any failure, from a deterministic heuristic. The impact index (no LLM)
lists the requirements whose source / related provisions changed.

    <data>/kb/changes/RC-<to_kb_version>.json
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from typing import Any

from engine.kb.releases import KnowledgeBase
from engine.llm.gemini import Gemini
from engine.store import _atomic_write, now_iso

CHANGE_TYPES = ["editorial", "substantive", "date", "scope", "new_interpretation"]
MAX_TEXT = 6000  # chars of old/new text kept per node (interpretations can be whole PDFs)
MAX_DIFF_LINES = 120

RE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
RE_DATE = re.compile(
    r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b"
)


def _norm(text: str) -> str:
    """Lowercase, no whitespace, no punctuation: what an editorial change leaves equal."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in text if ch.isalnum())


def _norm_words(text: str) -> str:
    return re.sub(r"\s+", " ", RE_NUMBER.sub("#", RE_DATE.sub("@", text or ""))).strip().lower()


def heuristic_change_type(old: str | None, new: str | None, kind: str) -> tuple[str, str]:
    """Deterministic fallback classification with a one-line rationale."""
    if kind == "interpretation":
        if old is None:
            return "new_interpretation", "New guidance text appeared."
        if new is None:
            return "new_interpretation", "Guidance text was withdrawn."
        if _norm(old) == _norm(new):
            return "editorial", "Only whitespace, punctuation or case changed."
        return "new_interpretation", "The guidance text changed."
    if old is None:
        return "substantive", "A new provision was added."
    if new is None:
        return "substantive", "The provision was removed."
    if _norm(old) == _norm(new):
        return "editorial", "Only whitespace, punctuation or case changed."
    old_dates = set(RE_DATE.findall(old)) | set(RE_NUMBER.findall(old))
    new_dates = set(RE_DATE.findall(new)) | set(RE_NUMBER.findall(new))
    if old_dates != new_dates:
        ratio = difflib.SequenceMatcher(None, _norm_words(old), _norm_words(new)).ratio()
        if ratio >= 0.9:
            return "date", "Dates or numbers changed; the wording is otherwise the same."
    return "substantive", "The wording of the provision changed."


def _unified(old: str | None, new: str | None) -> str:
    lines = list(
        difflib.unified_diff(
            (old or "").splitlines(), (new or "").splitlines(), "old", "new", lineterm="", n=1
        )
    )
    if len(lines) > MAX_DIFF_LINES:
        lines = [*lines[:MAX_DIFF_LINES], f"... ({len(lines) - MAX_DIFF_LINES} more lines)"]
    return "\n".join(lines)


def _clip(text: str | None) -> str | None:
    if text is None or len(text) <= MAX_TEXT:
        return text
    return text[:MAX_TEXT] + f"\n... [{len(text) - MAX_TEXT} more characters]"


def diff_maps(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], kind: str
) -> list[dict[str, Any]]:
    """Changed / added / removed nodes between two ``id -> node`` maps."""
    out: list[dict[str, Any]] = []
    for nid in sorted(set(old) | set(new)):
        a, b = old.get(nid), new.get(nid)
        if a and b and a["content_hash"] == b["content_hash"]:
            continue
        change = "changed" if a and b else ("added" if b else "removed")
        node = b or a or {}
        out.append(
            {
                "id": nid,
                "kind": kind,
                "change": change,
                "title": node.get("title"),
                "path": node.get("path"),
                "source_id": node.get("source_id"),
                "binding": node.get("binding", kind == "provision"),
                "old_hash": a and a["content_hash"],
                "new_hash": b and b["content_hash"],
                "old_text": _clip(a and a["text"]),
                "new_text": _clip(b and b["text"]),
                "diff": _unified(a and a["text"], b and b["text"]),
                "relates_to": node.get("relates_to", []),
            }
        )
    return out


_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "change_type": {"type": "string", "enum": CHANGE_TYPES},
            "rationale": {"type": "string"},
        },
        "required": ["id", "change_type", "rationale"],
    },
}

_PROMPT = """You classify changes to EU AI Act regulatory texts for a compliance knowledge base.
For each item return its id, a change_type and a one-line rationale (max 25 words).
change_type:
- editorial: wording/punctuation/numbering with no change in meaning
- substantive: the obligation, its content or its conditions changed
- date: only an application date, deadline or number changed
- scope: who or what the provision applies to changed (actors, systems, exceptions)
- new_interpretation: non-binding guidance (guidelines, FAQ) appeared or changed its reading
Items (JSON):
"""


async def classify(entries: list[dict[str, Any]], gemini: Gemini) -> None:
    """Set ``change_type``, ``rationale`` and ``classified_by`` on every entry (in place)."""
    llm: dict[str, dict[str, Any]] = {}
    batch = entries[: gemini.max_items]
    if gemini.active and batch:
        payload = [
            {
                "id": e["id"],
                "kind": e["kind"],
                "change": e["change"],
                "binding": e["binding"],
                "old": (e["old_text"] or "")[:1500],
                "new": (e["new_text"] or "")[:1500],
            }
            for e in batch
        ]
        answer = await gemini.json(
            _PROMPT + json.dumps(payload, ensure_ascii=False), _SCHEMA, purpose="change_type"
        )
        if isinstance(answer, list):
            for item in answer:
                if isinstance(item, dict) and item.get("change_type") in CHANGE_TYPES:
                    llm[str(item.get("id"))] = item
    for e in entries:
        hit = llm.get(e["id"])
        if hit:
            e.update(
                change_type=hit["change_type"],
                rationale=str(hit.get("rationale", ""))[:300],
                classified_by=f"gemini:{gemini.model}",
            )
        else:
            ctype, why = heuristic_change_type(e["old_text"], e["new_text"], e["kind"])
            e.update(change_type=ctype, rationale=why, classified_by="heuristic")


def impact(entries: list[dict[str, Any]], requirements: list[dict[str, Any]]) -> list[dict]:
    """Requirements touched by the change (no LLM): source/related provision or an
    interpretation that relates to them changed."""
    touched: set[str] = set()
    for e in entries:
        touched.add(e["id"])
        touched.update(e.get("relates_to") or [])

    def hit(pid: str) -> bool:
        return any(pid == t or pid.startswith(t + ".") or t.startswith(pid + ".") for t in touched)

    out = []
    for r in requirements:
        via = [p for p in [r["source"], *r.get("related", [])] if hit(p)]
        if via:
            out.append(
                {"requirement_id": r["id"], "via": via, "test_templates": r["test_templates"]}
            )
    return out


def change_path(kb: KnowledgeBase, change_id: str) -> Any:
    if not re.fullmatch(r"RC-\d{4}\.\d{2}\.\d{2}-\d+", change_id):
        raise ValueError(f"invalid change id: {change_id!r}")
    return kb.root / "changes" / f"{change_id}.json"


async def build_change(
    kb: KnowledgeBase,
    from_version: str | None,
    to_version: str,
    gemini: Gemini,
    *,
    trigger: str | None = None,
) -> dict[str, Any] | None:
    """Diff ``from_version`` -> ``to_version``; save and return the RegChange (None = no diff)."""
    old_p = kb.provision_map(from_version) if from_version else {}
    old_i = kb.interpretation_map(from_version) if from_version else {}
    entries = diff_maps(old_p, kb.provision_map(to_version), "provision")
    entries += diff_maps(old_i, kb.interpretation_map(to_version), "interpretation")
    if not entries:
        return None
    await classify(entries, gemini)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["change"]] = counts.get(e["change"], 0) + 1
    types: dict[str, int] = {}
    for e in entries:
        types[e["change_type"]] = types.get(e["change_type"], 0) + 1
    change = {
        "id": f"RC-{to_version}",
        "from_kb_version": from_version,
        "to_kb_version": to_version,
        "created_at": now_iso(),
        "trigger": trigger,
        "status": "open",
        "counts": counts,
        "change_types": types,
        "summary": _summary(entries),
        "impacted_requirements": impact(entries, kb.requirements(to_version)),
        "provisions": [e for e in entries if e["kind"] == "provision"],
        "interpretations": [e for e in entries if e["kind"] == "interpretation"],
    }
    path = change_path(kb, change["id"])
    _atomic_write(path, json.dumps(change, indent=2, ensure_ascii=False).encode("utf-8"))
    return change


def _summary(entries: list[dict[str, Any]]) -> str:
    prov = [e for e in entries if e["kind"] == "provision"]
    interp = [e for e in entries if e["kind"] == "interpretation"]
    parts = []
    if prov:
        parts.append(f"{len(prov)} provision(s) changed")
    if interp:
        parts.append(f"{len(interp)} interpretation(s) changed")
    ids = ", ".join(e["id"] for e in entries[:5])
    more = f" (+{len(entries) - 5} more)" if len(entries) > 5 else ""
    return f"{'; '.join(parts)}: {ids}{more}"


def list_changes(kb: KnowledgeBase) -> list[dict[str, Any]]:
    folder = kb.root / "changes"
    if not folder.exists():
        return []
    items = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("RC-*.json")]
    return sorted(items, key=lambda c: c["created_at"], reverse=True)


def load_change(kb: KnowledgeBase, change_id: str) -> dict[str, Any] | None:
    try:
        path = change_path(kb, change_id)
    except ValueError:
        return None
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
