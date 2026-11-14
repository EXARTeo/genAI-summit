"""Proposed sources: documents discovery found that are not in the catalog yet.

    <data>/discovery/proposed.json          every proposal and its decision
    <data>/discovery/accepted_sources.yaml  accepted proposals: the catalog overlay

Each proposal is triaged (relevance 0-1, kind, binding, tags) by Gemini or, with
no key, by a keyword heuristic. Below ``IGNORE_BELOW`` it is stored as
``ignored`` (kept, hidden by default). Accepting one appends a catalog entry to
the overlay (the git ``sources.yaml`` is never edited at runtime).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from engine.catalog.loader import Catalog, Source
from engine.llm.gemini import Gemini
from engine.store import _atomic_write, now_iso

IGNORE_BELOW = 0.35
KINDS = ["regulation", "amendment", "guideline", "faq", "code_of_practice", "standard", "other"]

_AI = re.compile(r"\b(artificial intelligence|ai act|2024/1689|general-purpose ai|gpai)\b", re.I)
_AI_WORD = re.compile(r"\bAI\b")
_GUIDANCE = re.compile(
    r"\b(guideline|guidance|code of practice|q&a|faq|questions and answers)", re.I
)


def _paths(data_dir: Path) -> tuple[Path, Path]:
    root = Path(data_dir) / "discovery"
    return root / "proposed.json", root / "accepted_sources.yaml"


def overlay_path(data_dir: Path) -> Path:
    return _paths(data_dir)[1]


def load(data_dir: Path) -> list[dict[str, Any]]:
    path = _paths(data_dir)[0]
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def save(data_dir: Path, items: list[dict[str, Any]]) -> None:
    data = json.dumps({"items": items}, indent=2, ensure_ascii=False).encode("utf-8")
    _atomic_write(_paths(data_dir)[0], data)


def proposal_id(candidate: dict[str, Any]) -> str:
    key = candidate.get("celex") or candidate.get("url") or ""
    return "P-" + hashlib.sha256(key.encode()).hexdigest()[:10]


# ---- triage -------------------------------------------------------------------------------


def keyword_triage(c: dict[str, Any]) -> dict[str, Any]:
    """Deterministic triage: AI Act keywords, CELEX sector/type and URL shape."""
    title = c.get("title") or ""
    text = f"{title} {c.get('description') or ''} {c.get('url') or ''}"
    celex = c.get("celex") or ""
    score = 0.2
    if _AI.search(text):
        score = 0.75
    elif _AI_WORD.search(title):
        score = 0.5
    if _GUIDANCE.search(text):
        score += 0.15
    kind, binding = "other", False
    if celex.startswith("3"):
        binding = True
        kind = "regulation" if celex[5:6] in {"R", "L"} else "other"
        score += 0.1
    elif celex.startswith("5"):
        doc_type = celex[5:7]
        if doc_type in {"SC", "DC", "PC"}:  # staff working docs, communications, proposals
            score -= 0.25
        kind = "guideline" if _GUIDANCE.search(title) else "other"
    elif _GUIDANCE.search(text):
        kind = "faq" if re.search(r"faq|q&a|questions", text, re.I) else "guideline"
    if c.get("relation") == "amends":
        kind, score = "amendment", score + 0.2
    tags = ["ai-act"] if score >= 0.5 else []
    tags.append(f"discovered-{c.get('found_by', 'unknown').replace('_', '-')}")
    return {
        "relevance": round(max(0.0, min(1.0, score)), 2),
        "kind": kind,
        "binding": binding,
        "tags": tags,
        "reason": "keyword heuristic (no Gemini key or Gemini unavailable)",
        "by": "heuristic",
    }


_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "relevance": {"type": "number"},
            "kind": {"type": "string", "enum": KINDS},
            "binding": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["id", "relevance", "kind", "binding", "tags", "reason"],
    },
}

_PROMPT = """You triage newly found documents for an EU AI Act (Regulation (EU) 2024/1689)
compliance knowledge base used by AI providers of high-risk systems.
For each document return: relevance 0..1 (1 = directly changes or interprets AI Act
obligations; staff working documents and unrelated policy are low), kind, binding (true only
for legal acts: regulations, directives, decisions), up to 5 short lowercase tags, and a
one-line reason.
Documents (JSON):
"""


async def triage(candidates: list[dict[str, Any]], gemini: Gemini) -> None:
    """Set ``triage`` on each candidate (in place)."""
    llm: dict[str, dict[str, Any]] = {}
    batch = candidates[: gemini.max_items]
    if gemini.active and batch:
        payload = [
            {
                k: c.get(k)
                for k in ("id", "title", "url", "celex", "date", "relation", "description")
            }
            for c in batch
        ]
        answer = await gemini.json(
            _PROMPT + json.dumps(payload, ensure_ascii=False), _SCHEMA, purpose="source_triage"
        )
        if isinstance(answer, list):
            llm = {str(a.get("id")): a for a in answer if isinstance(a, dict)}
    for c in candidates:
        hit = llm.get(c["id"])
        if hit and hit.get("kind") in KINDS:
            c["triage"] = {
                "relevance": float(max(0.0, min(1.0, hit.get("relevance") or 0))),
                "kind": hit["kind"],
                "binding": bool(hit.get("binding")),
                "tags": [str(t) for t in (hit.get("tags") or [])][:5],
                "reason": str(hit.get("reason", ""))[:300],
                "by": f"gemini:{gemini.model}",
            }
        else:
            c["triage"] = keyword_triage(c)


# ---- recording and decisions ----------------------------------------------------------------


def known_keys(catalog: Catalog, items: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in catalog.sources:
        if s.url:
            keys.add(s.url.rstrip("/"))
        if s.celex:
            keys.add(s.celex)
    for p in items:
        if p.get("url"):
            keys.add(p["url"].rstrip("/"))
        if p.get("celex"):
            keys.add(p["celex"])
    return keys


async def add_candidates(
    data_dir: Path, catalog: Catalog, candidates: list[dict[str, Any]], gemini: Gemini
) -> list[dict[str, Any]]:
    """Record the new candidates (deduplicated against the catalog and earlier proposals)."""
    items = load(data_dir)
    known = known_keys(catalog, items)
    fresh: list[dict[str, Any]] = []
    for c in candidates:
        key = c.get("celex") or (c.get("url") or "").rstrip("/")
        if not key or key in known:
            continue
        known.add(key)
        fresh.append({**c, "id": proposal_id(c), "found_at": now_iso()})
    if not fresh:
        return []
    await triage(fresh, gemini)
    for c in fresh:
        c["status"] = "proposed" if c["triage"]["relevance"] >= IGNORE_BELOW else "ignored"
    save(data_dir, items + fresh)
    return fresh


def _source_id(p: dict[str, Any], taken: set[str]) -> str:
    base = p.get("celex") or p.get("title") or p.get("url") or p["id"]
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:50] or p["id"].lower()
    sid, n = f"disc-{slug}", 2
    while sid in taken:
        sid = f"disc-{slug}-{n}"
        n += 1
    return sid


def decide(
    data_dir: Path, catalog: Catalog, pid: str, accept: bool, *, by: str = "api"
) -> dict[str, Any]:
    items = load(data_dir)
    prop = next((p for p in items if p["id"] == pid), None)
    if prop is None:
        raise KeyError(pid)
    if prop["status"] in {"accepted", "rejected"}:
        raise ValueError(f"proposal already {prop['status']}")
    prop.update(status="accepted" if accept else "rejected", decided_at=now_iso(), decided_by=by)
    if accept:
        tri = prop.get("triage") or {}
        sid = _source_id(prop, {s.id for s in catalog.sources})
        entry: dict[str, Any] = {
            "id": sid,
            "title": (prop.get("title") or sid)[:200],
            "kind": tri.get("kind") if tri.get("kind") in KINDS else "other",
            "binding": bool(tri.get("binding")),
            "status": "final",
            "publisher": "discovered",
            "tags": list(tri.get("tags") or []),
            "notes": f"Accepted proposal {pid} ({prop.get('found_by')})",
        }
        if prop.get("celex"):
            entry.update(fetcher="cellar", celex=prop["celex"], formats=["xhtml"])
        else:
            url = prop["url"]
            entry.update(fetcher="http", url=url)
            if url.lower().endswith(".pdf"):
                entry["formats"] = ["pdf"]
        Source.model_validate(entry)  # fail before writing
        path = overlay_path(data_dir)
        overlay = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
        overlay.setdefault("sources", []).append(entry)
        _atomic_write(
            path, yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True).encode("utf-8")
        )
        prop["source_id"] = sid
    save(data_dir, items)
    return prop
