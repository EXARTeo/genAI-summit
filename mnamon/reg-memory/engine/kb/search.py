"""Deterministic regulation search (no LLM): ranked, self-explaining provision hits.

Every hit is useful on its own: a readable ``label`` ("Art. 10(2)"), a ``title``
(the node's own, or the nearest article / annex / annex section title, flagged
``title_inherited``), a ``snippet`` of the matching text with the query term in
it, the chapter and section headings, ``source``, ``binding``, ``kind`` and a
``score``.

Ranking, highest first (ties: document order):

* **Heading matches** (the node's own or inherited title, then its section and
  chapter headings) weigh most: "governance" ranks Art. 10 "Data and data
  governance" and Chapter VII "Governance" above a passing mention.
* **Whole-word text matches** beat partial ones ("risk" does not match "brisk"
  as a word); the whole phrase beats scattered terms; repeats add a little.
* Every query term must match somewhere (title, headings or text); when no node
  matches all terms, nodes matching most of them are returned.
* Recitals and amending-act points weigh less than the consolidated articles
  (they explain or change the law, they are not the law in force).
* **One hit per article / annex / recital**: the best node stands for its
  article and the other matching nodes are listed in ``also``. A node with no
  matching text of its own (an article whose title matches) yields to its best
  matching child, which carries the title as inherited.

Derived at read time from a release's provisions; a release is never changed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

SNIPPET_CHARS = 260
MAX_ALSO = 6

_WORD = re.compile(r"[\w’'-]+", re.UNICODE)
STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it"}
    | {"of", "on", "or", "that", "the", "this", "to", "with", "which", "who", "what", "about"}
)
# Lower weight for nodes that explain or amend rather than state the law in force.
KIND_WEIGHT = {"recital": 0.55}
INSTRUMENT_WEIGHT = {"OMNIBUS": 0.7}
INSTRUMENT_NAME = {"AIA": "", "OMNIBUS": "Omnibus "}


@dataclass
class _Query:
    phrase: str
    terms: list[str]
    patterns: dict[str, re.Pattern[str]] = field(default_factory=dict)
    phrase_re: re.Pattern[str] | None = None


def parse_query(q: str) -> _Query:
    words = [w.lower().strip("’'-") for w in _WORD.findall(q)]
    terms = [w for w in words if w and w not in STOPWORDS] or [w for w in words if w]
    unique = list(dict.fromkeys(terms))
    query = _Query(phrase=" ".join(words), terms=unique)
    for t in unique:
        query.patterns[t] = re.compile(rf"(?<![\w-]){re.escape(t)}\w{{0,3}}(?![\w])", re.I)
    if len(words) > 1:
        gap = r"[\s\-–]+"
        query.phrase_re = re.compile(
            r"(?<![\w])" + gap.join(re.escape(w) for w in words) + r"\w{0,3}(?![\w])", re.I
        )
    return query


# ---- labels and inherited titles ---------------------------------------------------------


def label(node: dict[str, Any]) -> str:
    """Readable citation label from the node's path: Art. 10(2)(f), Annex III, point 4(a)."""
    path = list(node.get("path") or [])
    prefix = INSTRUMENT_NAME.get(node.get("instrument") or "", f"{node.get('instrument')} ")
    if not path:
        return node.get("id", "")
    head, rest = path[0], path[1:]
    if head.startswith("Recital"):
        return f"{prefix}{head}"
    if head.startswith("Art "):
        out = "Art. " + head[4:]
        for part in rest:
            out += f"({part.split(' ', 1)[-1]})"
        return prefix + out
    if head.startswith("Annex"):
        parts = [head]
        tokens: list[str] = []
        for part in rest:
            kind, _, tok = part.partition(" ")
            if kind == "Section":
                parts.append(f"Section {tok}")
            else:
                tokens.append(tok)
        if tokens:
            first, more = tokens[0], tokens[1:]
            # "3.1" sub-points read as decimals, letters / romans in brackets.
            while more and more[0].isdigit():
                first += "." + more.pop(0)
            parts.append("point " + first + "".join(f"({t})" for t in more))
        return prefix + ", ".join(parts)
    return prefix + " ".join(path)


def heading(
    node: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> tuple[str | None, bool, str | None]:
    """``(title, inherited, from_id)``: the node's own title or its nearest titled ancestor's."""
    if node.get("title"):
        return node["title"], False, node["id"]
    parent = node.get("parent")
    seen = 0
    while parent and seen < 12:
        anc = by_id.get(parent)
        if anc is None:
            break
        if anc.get("title"):
            return anc["title"], True, anc["id"]
        parent, seen = anc.get("parent"), seen + 1
    return None, False, None


def _group_key(node: dict[str, Any], match: str = "text") -> str:
    if match == "heading":  # articles found by their chapter / section heading: one hit
        return f"{node.get('instrument')}.CH_{node.get('chapter')}.S_{node.get('section') or ''}"
    parts = node["id"].split(".")
    if len(parts) > 2 and parts[1] == "REC":
        return ".".join(parts[:3])
    return ".".join(parts[:2])


# ---- scoring -----------------------------------------------------------------------------


def _body(node: dict[str, Any]) -> str:
    """The node's own text without its title line (articles and annexes start with it)."""
    text = node.get("text") or ""
    title = node.get("title")
    if title and node.get("kind") in {"article", "annex"} and text.startswith(title):
        text = text[len(title) :]
    return text.strip()


def _heading_score(q: _Query, text: str | None, weight: float) -> tuple[float, set[str]]:
    if not text:
        return 0.0, set()
    hit = {t for t, p in q.patterns.items() if p.search(text)}
    if not hit:
        return 0.0, set()
    score = weight * len(hit) / len(q.terms)
    if q.phrase_re is not None and q.phrase_re.search(text):
        score += weight * 0.5
    return score, hit


def _text_score(q: _Query, text: str) -> tuple[float, set[str]]:
    if not text:
        return 0.0, set()
    lower = text.lower()
    hit: set[str] = set()
    score = 0.0
    for t, p in q.patterns.items():
        n = len(p.findall(text))
        if n:
            hit.add(t)
            score += 2.0 + min(1.5, 0.5 * math.log2(1 + n))
        elif t in lower:  # inside another word: weak evidence
            score += 0.3
    if q.phrase_re is not None and q.phrase_re.search(text):
        score += 5.0
    return score, hit


def snippet(text: str, q: _Query, width: int = SNIPPET_CHARS) -> str:
    """A ~``width``-char window around the phrase, else around the first term match whose
    window holds the most distinct query terms; cut on word bounds."""
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return ""
    m = q.phrase_re.search(flat) if q.phrase_re is not None else None
    if m is None:
        found = [(t, f) for t, p in q.patterns.items() for f in p.finditer(flat)]
        found.sort(key=lambda tf: tf[1].start())

        def spread(i: int) -> int:
            start = found[i][1].start()
            return len({t for t, f in found[i:] if f.start() - start < width * 2 // 3})

        m = found[max(range(len(found)), key=lambda i: (spread(i), -i))][1] if found else None
    if len(flat) <= width:
        return flat
    if m is None:
        cut = flat[:width].rsplit(" ", 1)[0]
        return cut + " …"
    start = max(0, m.start() - width // 3)
    end = min(len(flat), start + width)
    start = max(0, end - width)
    if start > 0:  # begin on a word
        space = flat.find(" ", start, m.start())
        start = space + 1 if space >= 0 else m.start()
    if end < len(flat):  # end on a word, after the match
        space = flat.rfind(" ", m.end(), end)
        end = space if space > 0 else end
    out = flat[start:end].strip()
    return ("… " if start > 0 else "") + out + (" …" if end < len(flat) else "")


def _score_node(
    node: dict[str, Any], q: _Query, by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    title, inherited, title_from = heading(node, by_id)
    body = _body(node)
    t_score, t_hit = _text_score(q, body)
    own_title_score, own_hit = _heading_score(q, node.get("title"), 8.0)
    inh_score, inh_hit = (0.0, set())
    if inherited:
        inh_score, inh_hit = _heading_score(q, title, 5.0)
    sec_score, sec_hit = _heading_score(q, node.get("section_title"), 3.0)
    ch_score, ch_hit = _heading_score(q, node.get("chapter_title"), 2.0)
    matched = t_hit | own_hit | inh_hit | sec_hit | ch_hit
    match = "text" if t_hit else "title" if own_hit else "heading"
    if match == "heading" and (node.get("kind") != "article" or not (sec_hit or ch_hit)):
        return None  # only an ancestor's title matches: the ancestor or a sibling is the hit
    score = t_score + own_title_score + inh_score + sec_score + ch_score
    score *= KIND_WEIGHT.get(node.get("kind", ""), 1.0)
    score *= INSTRUMENT_WEIGHT.get(node.get("instrument", ""), 1.0)
    return {
        "node": node,
        "score": score,
        "matched": matched,
        "has_text": bool(t_hit),
        "match": match,
        "title": title,
        "title_inherited": inherited,
        "title_from": title_from,
        "body": body,
    }


def _heading_line(node: dict[str, Any]) -> str:
    parts = []
    if node.get("chapter"):
        parts.append(f"Chapter {node['chapter']} {node.get('chapter_title') or ''}".strip())
    if node.get("section"):
        parts.append(f"Section {node['section']} {node.get('section_title') or ''}".strip())
    return " > ".join(parts)


# ---- public ------------------------------------------------------------------------------


def search(
    provisions: Iterable[dict[str, Any]],
    q: str,
    *,
    limit: int = 10,
    instrument: str | None = None,
    binding: dict[str, Any] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Rank ``provisions`` for ``q``; returns ``(total groups, hits[:limit])``.

    ``binding`` maps ``source_doc`` -> the catalog's ``binding`` (default ``True``:
    acts are law).
    """
    query = parse_query(q)
    if not query.terms:
        return 0, []
    items = list(provisions)
    by_id = {p["id"]: p for p in items}
    order = {p["id"]: n for n, p in enumerate(items)}
    scored = []
    for p in items:
        if instrument and p.get("instrument") != instrument:
            continue
        s = _score_node(p, query, by_id)
        if s is not None:
            scored.append(s)
    if not scored:
        return 0, []
    need = len(query.terms)
    best_cover = max(len(s["matched"]) for s in scored)
    cover = need if best_cover >= need else best_cover
    scored = [s for s in scored if len(s["matched"]) >= cover]

    groups: dict[str, list[dict[str, Any]]] = {}
    for s in scored:
        groups.setdefault(_group_key(s["node"], s["match"]), []).append(s)
    hits = []
    for members in groups.values():
        members.sort(key=lambda s: (-s["score"], order[s["node"]["id"]]))
        top = members[0]["score"]
        # The earliest node that scores close to the best stands for the article (its
        # main paragraph rather than a later one that repeats the words).
        with_text = [s for s in members if s["has_text"] and s["score"] >= 0.85 * top]
        pool = with_text or [s for s in members if s["has_text"]] or members
        lead = min(pool, key=lambda s: order[s["node"]["id"]])
        # A title-only lead (article heading) hands its weight to the best child with text.
        bonus = top - lead["score"]
        group_score = lead["score"] + bonus + 0.4 * min(len(members) - 1, 5)
        hits.append((group_score, order[lead["node"]["id"]], lead, members))
    hits.sort(key=lambda h: (-h[0], h[1]))

    out = []
    for group_score, _, lead, members in hits[:limit]:
        node = lead["node"]
        src = node.get("source_doc")
        item: dict[str, Any] = {
            "id": node["id"],
            "label": label(node),
            "title": lead["title"],
            "title_inherited": lead["title_inherited"],
            "snippet": _heading_line(node)
            if lead["match"] == "heading"
            else snippet(lead["body"] or node.get("text") or "", query),
            "match": lead["match"],
            "score": round(group_score, 2),
            "kind": node.get("kind"),
            "instrument": node.get("instrument"),
            "source": src,
            # Recitals explain the law; they are never binding themselves.
            "binding": False
            if node.get("kind") == "recital"
            else ((binding or {}).get(src, True) if src else True),
        }
        if lead["title_inherited"]:
            item["title_from"] = lead["title_from"]
        for key in ("chapter_title", "section_title", "valid_from"):
            if node.get(key):
                item[key] = node[key]
        also = [m["node"]["id"] for m in members if m is not lead]
        if also:
            item["also"] = sorted(also, key=order.__getitem__)[:MAX_ALSO]
        out.append(item)
    return len(hits), out
