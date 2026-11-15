"""Deterministic provision parser (no LLM): extracted act text -> provision nodes.

Input is the markdown that the extract stage writes for a Cellar XHTML act
(``### Article N`` + title, ``1.`` paragraphs, ``(a)`` points, ``(i)`` sub-points,
``## ANNEX X``, ``▼B`` / ``▼M1`` amendment markers in consolidated texts,
``| (n) | text |`` rows for recitals and amending points).

Ids are stable and readable::

    AIA.10              Article 10 (its title + any unnumbered intro text)
    AIA.10.2            paragraph 2
    AIA.10.2.f          point (f) of paragraph 2
    AIA.113.c.i         sub-point (i)
    AIA.3.1             definition (1) (points directly under an article)
    AIA.ANNEX_III.4.a   Annex III, point 4(a)
    AIA.REC.27          recital 27
    OMNIBUS.1.12        Digital Omnibus, Article 1, amending point (12)

Each node carries its own verbatim text only (children are separate nodes),
``content_hash`` = sha256 of that text, ``path``, ``valid_from`` (from the
application dates of Art. 113, as amended) and ``amended_by``, plus the
``chapter_title`` / ``section_title`` headings it sits under.

Parser rules that keep the structure right (``PARSER_VERSION`` 2):

* An unnumbered subparagraph after the last point of a list ("Notwithstanding the
  first subparagraph, ...") belongs to the paragraph (or article) that holds the
  list, not to the last point. Text between two points stays with the point.
* ``(i)`` right after ``(h)`` is the letter (i), unless the next point is ``(ii)``:
  then it opens sub-points of (h) (Art. 5(1)(h)(i)-(iii)); same for ``(v)`` / ``(x)``.
* Annex points numbered ``3.1.`` are their own nodes (``AIA.ANNEX_VII.3.1``).
* Markdown heading marks are stripped from titles (``## Union legislative acts``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

#: Bumped whenever the parser's output changes for the same input text; a release
#: records it, so a re-parse is always a new kb release, never an edit of an old one.
PARSER_VERSION = 2

ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}
# A roman numeral that is also the next letter after the given one.
_AMBIGUOUS = {"i": "h", "v": "u", "x": "w"}

RE_CHAPTER = re.compile(r"^##\s+CHAPTER\s+([IVXL]+)\s*$")
RE_SECTION = re.compile(r"^##\s+SECTION\s+(\d+)\s*$")
RE_ARTICLE = re.compile(r"^###\s+Article\s+(\d+[a-z]?)\s*$")
RE_ANNEX = re.compile(r"^##\s+ANNEX\s+([IVXL]+)\s*$")
RE_PARA = re.compile(r"^(\d+[a-z]?)\.(?:\s+(\S.*))?\s*$")
RE_POINT = re.compile(r"^\((\d{1,3}[a-z]?|[a-z]{1,3})\)(?:\s+(\S.*))?\s*$")
RE_ROW = re.compile(r"^\|\s*\((\d{1,3}[a-z]?)\)\s*\|(.*)\|\s*$")
RE_ANNEX_SECTION = re.compile(r"^(?:Section|Part)\s+([A-Z]|\d+)(?:\s*[.—–-]\s*(.*))?$")
RE_SUBNUM = re.compile(r"^(\d+)\.(\d+)\.(?:\s+(\S.*))?\s*$")
RE_HEADING_MARK = re.compile(r"^#+\s*")
RE_MARKER = re.compile(r"^▼\s*([A-Z]\d*)(\s*[—–-]+)?\s*$")
RE_AMENDER = re.compile(r"►([A-Z]\d+)\s*\|\s*([A-Z ()]+?)\s*\(EU\)\s*(\d{4}/\d+)")
RE_TARGET = re.compile(
    r"\b(?:in\s+)?Article\s+(\d+[a-z]?)(?:\s*\((\d+[a-z]?)\))?|\bAnnex\s+([IVXL]+)\b"
)

# Application dates (Art. 113 as amended by Reg (EU) 2026/1744), used for valid_from.
GENERAL_DATE = "2026-08-02"
DATES_ANNEX_III = "2027-12-02"
DATES_ANNEX_I = "2028-08-02"


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class _Node:
    id: str
    kind: str  # article | paragraph | point | annex | annex_point | recital
    path: list[str]
    parent: str | None = None
    title: str | None = None
    chapter: str | None = None
    section: str | None = None
    lines: list[str] = field(default_factory=list)
    markers: set[str] = field(default_factory=set)
    token: str = ""  # its own number/letter
    rank: int = 1  # points: 0 = (1), 1 = (a), 2 = (i)
    chapter_title: str | None = None
    section_title: str | None = None

    def text(self) -> str:
        return "\n".join(self.lines).strip()


class _Parser:
    def __init__(self, instrument: str) -> None:
        self.instrument = instrument
        self.nodes: dict[str, _Node] = {}
        self.order: list[str] = []
        self.marker = "B"
        self.chapter: str | None = None
        self.section: str | None = None
        self.container: _Node | None = None  # article or annex
        self.block: _Node | None = None  # annex "Section A" sub-container
        self.para: _Node | None = None
        self.sub: _Node | None = None  # annex point "3.1" under point "3"
        self.points: list[_Node] = []  # nested (1) > (a) > (i)
        self.want_title: _Node | None = None
        self.want_heading: str | None = None  # "chapter" | "section": its title is next
        self.chapter_title: str | None = None
        self.section_title: str | None = None
        # Plain lines after a point that already has text: they stay with that point if
        # another point of the list follows, else they belong to the list's holder.
        self.tail: list[tuple[str, str]] = []
        self.roman_next = False  # set by parse_act's look-ahead for "(i)" after "(h)"
        self.amenders: dict[str, str] = {}

    # ---- helpers --------------------------------------------------------------------

    def _add(self, node: _Node) -> _Node:
        base, n = node.id, 2
        while node.id in self.nodes:  # never collide: AIA.3.1 vs a stray paragraph 1
            node.id = f"{base}_{n}"
            n += 1
        if self.marker != "B":
            node.markers.add(self.marker)
        self.nodes[node.id] = node
        self.order.append(node.id)
        return node

    def _holder(self) -> _Node | None:
        """What holds the current list of points (sub-point, paragraph, block, article)."""
        return self.sub or self.para or self.block or self.container

    def _deepest(self) -> _Node | None:
        if self.points:
            return self.points[-1]
        return self._holder()

    def _flush_tail(self, *, into_point: bool = False) -> None:
        if not self.tail:
            return
        target = self.points[-1] if into_point and self.points else self._holder()
        if target is not None:
            for line, marker in self.tail:
                target.lines.append(line)
                if marker != "B":
                    target.markers.add(marker)
        self.tail = []

    def _child(self, parent: _Node, token: str, kind: str, label: str) -> _Node:
        return self._add(
            _Node(
                id=f"{parent.id}.{token}",
                kind=kind,
                path=[*parent.path, f"{label} {token}"],
                parent=parent.id,
                chapter=self.chapter,
                section=self.section,
                token=token,
                chapter_title=self.chapter_title,
                section_title=self.section_title,
            )
        )

    def _append(self, line: str) -> None:
        node = self._deepest()
        if node is None:
            return
        # A point that ends a line in ":" introduces its own text ("the following paragraph
        # is added: '3. ...'"), so what follows stays with it.
        opens = any(x.rstrip().endswith(":") for x in node.lines)
        if node.kind == "point" and node.lines and not opens:
            self.tail.append((line, self.marker))
            return
        node.lines.append(line)
        if self.marker != "B":
            node.markers.add(self.marker)

    def finish(self) -> None:
        """End of the text: trailing lines go to the list's holder."""
        self._flush_tail()

    # ---- line handlers -----------------------------------------------------------------

    def feed(self, raw: str) -> None:
        line = raw.strip()
        if not line or line == "---" or re.fullmatch(r"\|(\s*-+\s*\|)+", line):
            return
        if m := RE_AMENDER.search(line):
            self.amenders[m.group(1)] = f"{m.group(2).strip().title()} (EU) {m.group(3)}"
        if m := RE_MARKER.match(line):
            self.marker = m.group(1)
            return
        if m := RE_CHAPTER.match(line):
            self._flush_tail()
            self.chapter, self.section = m.group(1), None
            self.chapter_title = self.section_title = None
            self.container = self.block = self.para = self.sub = None
            self.points = []
            self.want_heading = "chapter"
            return
        if m := RE_SECTION.match(line):
            self._flush_tail()
            self.section = m.group(1)
            self.section_title = None
            self.container = self.block = self.para = self.sub = None
            self.points = []
            self.want_heading = "section"
            return
        if self.want_heading is not None:
            kind, self.want_heading = self.want_heading, None
            if not line.startswith("#"):
                if kind == "chapter":
                    self.chapter_title = _clean_title(line)
                else:
                    self.section_title = _clean_title(line)
                return
        if m := RE_ARTICLE.match(line):
            self._flush_tail()
            art = m.group(1)
            self.container = self._add(
                _Node(
                    id=f"{self.instrument}.{art}",
                    kind="article",
                    path=[f"Art {art}"],
                    chapter=self.chapter,
                    section=self.section,
                    token=art,
                    chapter_title=self.chapter_title,
                    section_title=self.section_title,
                )
            )
            self.block = self.para = self.sub = None
            self.points = []
            self.want_title = self.container
            return
        if m := RE_ANNEX.match(line):
            self._flush_tail()
            annex = m.group(1)
            self.chapter = self.section = None
            self.chapter_title = self.section_title = None
            self.container = self._add(
                _Node(
                    id=f"{self.instrument}.ANNEX_{annex}",
                    kind="annex",
                    path=[f"Annex {annex}"],
                    token=annex,
                )
            )
            self.block = self.para = self.sub = None
            self.points = []
            self.want_title = self.container
            return
        if self.container is None:
            return  # preamble / headers before the first article
        if self.want_title is not None:
            self.want_title.title = _clean_title(line)
            self.want_title = None
            return
        if m := RE_ROW.match(line):
            self._point(m.group(1), _row_text(m.group(2)))
            return
        if self.container.kind == "annex" and (m := RE_ANNEX_SECTION.match(line)):
            self._flush_tail()
            self.block = self._child(self.container, m.group(1), "annex_section", "Section")
            self.block.lines.append(line)
            if m.group(2):
                self.block.title = _clean_title(m.group(2))
            self.para = self.sub = None
            self.points = []
            return
        if self.container.kind == "annex" and (m := RE_SUBNUM.match(line)):
            self._flush_tail()
            top = self.para if self.para is not None and self.para.token == m.group(1) else None
            parent = top or self.block or self.container
            self.sub = self._child(parent, m.group(2), "annex_point", "pt")
            self.points = []
            if m.group(3):
                self._append(m.group(3))
            return
        if m := RE_PARA.match(line):
            self._flush_tail()
            parent = self.block or self.container
            kind = "annex_point" if self.container.kind == "annex" else "paragraph"
            label = "pt" if self.container.kind == "annex" else "para"
            self.para = self._child(parent, m.group(1), kind, label)
            self.sub = None
            self.points = []
            if m.group(2):
                self._append(m.group(2))
            return
        if m := RE_POINT.match(line):
            self._point(m.group(1), m.group(2))
            return
        self._append(line)

    def _rank(self, token: str) -> int:
        """0 = (1), 1 = (a), 2 = (i); "(i)" right after "(h)" is a letter unless "(ii)" follows."""
        if token[0].isdigit():
            return 0
        if token in ROMAN:
            letters = [p for p in self.points if p.rank == 1]
            last = letters[-1].token if letters else None
            if last is not None and (_AMBIGUOUS.get(token) != last or self.roman_next):
                return 2
        return 1

    def _point(self, token: str, text: str | None) -> None:
        rank = self._rank(token)
        if self.tail:
            # A list that starts again ("(a)" after "(d)" and a lead-in) is a new list of
            # the same holder, so the lead-in is the holder's text. Otherwise the text sat
            # between two points of one list and stays with the point before.
            if token in {"a", "1"} and any(p.rank == rank for p in self.points):
                self.points = []
                self._flush_tail()
            else:
                self._flush_tail(into_point=True)
        while self.points and self.points[-1].rank >= rank:
            self.points.pop()
        parent = self.points[-1] if self.points else self._holder()
        assert parent is not None  # noqa: S101 - feed() checked the container
        node = self._child(parent, token, "point", "pt")
        node.rank = rank
        self.points.append(node)
        if text:
            self._append(text)


def _clean_title(line: str) -> str:
    return RE_HEADING_MARK.sub("", line).strip()


def _roman_lookahead(lines: list[str]) -> set[int]:
    """Indexes of "(i)" / "(v)" / "(x)" lines whose next point is "(ii)" / "(vi)" / "(xi)"."""
    points = [(n, m.group(1)) for n, raw in enumerate(lines) if (m := RE_POINT.match(raw.strip()))]
    return {
        n
        for (n, token), (_, after) in zip(points, points[1:], strict=False)
        if token in _AMBIGUOUS and after == token + "i"
    }


def _row_text(cells: str) -> str:
    parts = [c.strip() for c in cells.split("|")]
    return " ".join(p for p in parts if p and not re.fullmatch(r"-+", p))


# ---- application dates (Art. 113) ---------------------------------------------------------


def _valid_from(node: _Node, instrument: str) -> tuple[str | None, dict[str, str] | None]:
    if instrument != "AIA":
        return None, None
    nid = node.id
    if node.kind in {"annex", "annex_point"} or nid.startswith("AIA.ANNEX_"):
        if nid.startswith("AIA.ANNEX_III"):
            return DATES_ANNEX_III, None
        return GENERAL_DATE, None
    art = nid.split(".")[1]
    num = int(re.match(r"\d+", art).group())  # type: ignore[union-attr]
    if num == 5 and re.match(r"^AIA\.5\.(1\.b[ab]|1a|1b)(\.|$)", nid):
        return "2026-12-02", None
    if node.chapter in {"I", "II"}:
        return "2025-02-02", None
    if 102 <= num <= 110:
        return "2026-07-27", None
    if num == 101:
        return GENERAL_DATE, None
    if (node.chapter == "III" and node.section == "4") or node.chapter in {"V", "VII", "XII"}:
        return "2025-08-02", None
    if num == 78:
        return "2025-08-02", None
    if node.chapter == "III" and node.section in {"1", "2", "3"}:
        if nid == "AIA.6.5" or nid.startswith("AIA.6.5."):
            return GENERAL_DATE, None
        return DATES_ANNEX_III, {"annex_iii": DATES_ANNEX_III, "annex_i": DATES_ANNEX_I}
    return GENERAL_DATE, None


# ---- public API -------------------------------------------------------------------------


def parse_act(text: str, instrument: str, *, source_doc: str | None = None) -> list[dict[str, Any]]:
    """Parse one act's extracted markdown into provision dicts, in document order."""
    parser = _Parser(instrument)
    lines = text.splitlines()
    roman = _roman_lookahead(lines)
    for n, line in enumerate(lines):
        parser.roman_next = n in roman
        parser.feed(line)
    parser.finish()
    out = []
    for nid in parser.order:
        node = parser.nodes[nid]
        body = node.text()
        if node.kind in {"article", "annex"} and node.title:
            body = f"{node.title}\n{body}".strip()
        vf, by_basis = _valid_from(node, instrument)
        item: dict[str, Any] = {
            "id": node.id,
            "instrument": instrument,
            "kind": node.kind,
            "path": node.path,
            "parent": node.parent,
            "title": node.title,
            "text": body,
            "content_hash": content_hash(body),
            "valid_from": vf,
            "amended_by": sorted(parser.amenders.get(m, m) for m in node.markers),
        }
        if by_basis:
            item["valid_from_by_basis"] = by_basis
        if vf:
            item["valid_from_basis"] = "AIA.113"
        if node.chapter:
            item["chapter"] = node.chapter
        if node.section:
            item["section"] = node.section
        if node.chapter_title:
            item["chapter_title"] = node.chapter_title
        if node.section_title:
            item["section_title"] = node.section_title
        if source_doc:
            item["source_doc"] = source_doc
        out.append(item)
    return out


def parse_recitals(text: str, instrument: str, *, source_doc: str | None = None) -> list[dict]:
    """Recitals of an OJ act: ``| (n) | text |`` rows between "Whereas:" and "HAVE ADOPTED"."""
    start = text.find("Whereas:")
    end = text.find("HAVE ADOPTED", start + 1)
    if start < 0 or end < 0:
        return []
    out = []
    for line in text[start:end].splitlines():
        m = RE_ROW.match(line.strip())
        if not m:
            continue
        n = m.group(1)
        body = _row_text(m.group(2))
        out.append(
            {
                "id": f"{instrument}.REC.{n}",
                "instrument": instrument,
                "kind": "recital",
                "path": [f"Recital {n}"],
                "parent": None,
                "title": None,
                "text": body,
                "content_hash": content_hash(body),
                "valid_from": None,
                "amended_by": [],
                **({"source_doc": source_doc} if source_doc else {}),
            }
        )
    return out


def amendment_targets(text: str, target_instrument: str = "AIA") -> list[str]:
    """Provision ids an amending point talks about ("in Article 10(5)..." -> AIA.10.5)."""
    head = text[:300]
    out: list[str] = []
    for m in RE_TARGET.finditer(head):
        if m.group(3):
            out.append(f"{target_instrument}.ANNEX_{m.group(3)}")
        elif m.group(2):
            out.append(f"{target_instrument}.{m.group(1)}.{m.group(2)}")
        else:
            out.append(f"{target_instrument}.{m.group(1)}")
        break  # the first reference is the amended one
    return out


def link_amendments(provisions: list[dict], amending: list[dict], label: str) -> None:
    """Refine ``amended_by`` of consolidated nodes to the amending points (OMNIBUS.1.n).

    ``label`` is the amender name the consolidated markers resolved to (e.g.
    "Regulation (EU) 2026/1744"). A node keeps the label when no point targets it.
    """
    by_target: dict[str, list[str]] = {}
    for item in amending:
        if item["kind"] != "point":
            continue
        targets = amendment_targets(item["text"])
        item["amends"] = targets
        for t in targets:
            by_target.setdefault(t, []).append(item["id"])
    for prov in provisions:
        if label not in prov["amended_by"]:
            continue
        parts = prov["id"].split(".")
        hits: list[str] = []
        for depth in range(len(parts), 1, -1):  # most specific target first
            hits = by_target.get(".".join(parts[:depth]), [])
            if hits:
                break
        if hits:
            prov["amended_by"] = sorted({*(a for a in prov["amended_by"] if a != label), *hits})
