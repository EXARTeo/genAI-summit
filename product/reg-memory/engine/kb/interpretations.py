"""Guidelines, FAQs and codes of practice -> interpretation nodes (``binding: false``).

One node per markdown section (``#``/``##``/``###`` heading) of a document's
latest extracted text, or one node per document when it has no headings (most
PDFs). ``relates_to`` links each node to the AI Act provisions it mentions,
found by regex on article / annex references and kept only when the id exists.
"""

from __future__ import annotations

import re
from typing import Any

from engine.kb.parser import content_hash

#: Catalog kinds that become interpretations.
INTERPRETATION_KINDS = frozenset({"guideline", "faq", "code_of_practice", "internal_policy"})
MAX_SECTIONS = 250

RE_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
RE_ARTICLE_REF = re.compile(
    r"\bArt(?:icle|s?\.)\s*(\d{1,3}[a-z]?)"
    r"(?:\s*\((\d{1,2}[a-z]?)\))?"
    r"(?:\s*\(([a-z]{1,3})\)|,?\s*(?:first\s+subparagraph,\s*)?point\s*\(([a-z]{1,3})\))?",
    re.IGNORECASE,
)
RE_ANNEX_REF = re.compile(
    r"\bAnnex\s+([IVX]{1,5})\b(?:,?\s*(?:point|section|area)\s*(\d{1,2})(?:\s*\(([a-z])\))?)?"
)
RE_POINT_OF_ANNEX = re.compile(
    r"\bpoint\s+(\d{1,2})(?:\s*\(([a-z])\))?\s+of\s+Annex\s+([IVX]{1,5})\b", re.IGNORECASE
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "section"


def _resolve(candidate: str, known: set[str]) -> str | None:
    """The candidate id, or its longest existing prefix (AIA.10.2.z -> AIA.10.2)."""
    parts = candidate.split(".")
    for depth in range(len(parts), 1, -1):
        cid = ".".join(parts[:depth])
        if cid in known:
            return cid
    return None


def find_references(text: str, known: set[str], instrument: str = "AIA") -> list[str]:
    """AI Act provision ids mentioned in ``text`` (only ids present in ``known``)."""
    found: list[str] = []
    for m in RE_ARTICLE_REF.finditer(text):
        parts = [m.group(1), m.group(2), m.group(3) or m.group(4)]
        found.append(".".join([instrument, *[p for p in parts if p]]))
    for m in RE_POINT_OF_ANNEX.finditer(text):
        parts = [f"ANNEX_{m.group(3)}", m.group(1), m.group(2)]
        found.append(".".join([instrument, *[p for p in parts if p]]))
    for m in RE_ANNEX_REF.finditer(text):
        parts = [f"ANNEX_{m.group(1)}", m.group(2), m.group(3)]
        found.append(".".join([instrument, *[p for p in parts if p]]))
    out: list[str] = []
    for cand in found:
        rid = _resolve(cand, known)
        if rid and rid not in out:
            out.append(rid)
    # "point 4(a) of Annex III" also matches a bare "Annex III": keep the specific id only.
    return [r for r in out if not any(o.startswith(r + ".") for o in out)]


def split_sections(text: str) -> list[tuple[str | None, str]]:
    """``[(heading, body)]``; one ``(None, text)`` item when there are < 2 headings."""
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if RE_HEADING.match(ln)]
    if len(heads) < 2:
        return [(None, text.strip())]
    out: list[tuple[str | None, str]] = []
    if heads[0] > 0 and "\n".join(lines[: heads[0]]).strip():
        out.append(("Introduction", "\n".join(lines[: heads[0]]).strip()))
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        heading = RE_HEADING.match(lines[start]).group(2)  # type: ignore[union-attr]
        body = "\n".join(lines[start:end]).strip()
        if body:
            out.append((heading, body))
    if len(out) > MAX_SECTIONS:  # very long pages: merge the tail into the last node
        head, tail = out[: MAX_SECTIONS - 1], out[MAX_SECTIONS - 1 :]
        out = [*head, (tail[0][0], "\n\n".join(b for _, b in tail))]
    return out


def build_interpretations(
    doc: dict[str, Any], source: Any, text: str, known: set[str]
) -> list[dict[str, Any]]:
    """Interpretation nodes for one document (``doc`` = manifest + latest entry)."""
    base = f"INT.{doc['doc_id']}"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for heading, body in split_sections(text):
        nid = base if heading is None else f"{base}.{_slug(heading)}"
        n = 2
        while nid in seen:
            nid = f"{base}.{_slug(heading or '')}-{n}"
            n += 1
        seen.add(nid)
        summary = re.sub(r"\s+", " ", body)[:300]
        items.append(
            {
                "id": nid,
                "source_id": source.id,
                "doc_id": doc["doc_id"],
                "title": source.title if heading is None else f"{source.title}: {heading}",
                "kind": source.kind,
                "binding": source.binding if source.binding == "internal" else False,
                "status": source.status,
                "publisher": source.publisher,
                "url": doc.get("url"),
                "doc_version": doc.get("version"),
                "relates_to": find_references(body, known),
                "summary": summary,
                "text": body,
                "content_hash": content_hash(body),
            }
        )
    return items
