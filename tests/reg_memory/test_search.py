# ruff: noqa: E501 - verbatim act text lines
"""Parser structure fixes (PARSER_VERSION 2) and the ranked regulation search."""

from __future__ import annotations

from kb_fixtures import CONSOLIDATED

from engine.kb.parser import PARSER_VERSION, parse_act
from engine.kb.search import label, parse_query, search, snippet

ACT = """## CHAPTER II

PROHIBITED AI PRACTICES

### Article 5

Prohibited AI practices

1.
The following AI practices shall be prohibited:

(g)

the use of biometric categorisation systems;

(h)

the use of ‘real-time’ remote biometric identification systems, unless strictly necessary for one of the following objectives:

(i)

the targeted search for specific victims;

(ii)

the prevention of a specific threat;

(iii)

the localisation of a suspect.

Point (h) of the first subparagraph is without prejudice to Article 9 of Regulation (EU) 2016/679.

## CHAPTER III

HIGH-RISK AI SYSTEMS

## SECTION 1

Classification of AI systems as high-risk

### Article 6

Classification rules for high-risk AI systems

3.
By derogation from paragraph 2, an AI system referred to in Annex III shall not be considered to be high-risk.

(a)

the AI system is intended to perform a narrow procedural task;

(d)

the AI system is intended to perform a preparatory task.

Notwithstanding the first subparagraph, an AI system referred to in Annex III shall always be considered to be high-risk where the AI system performs profiling of natural persons.

4.
A provider who considers that an AI system referred to in Annex III is not high-risk shall document its assessment.

### Article 16

Obligations of providers of high-risk AI systems

Providers of high-risk AI systems shall:

(h)

affix the CE marking;

(i)

comply with the registration obligations;

(j)

take the necessary corrective actions.

### Article 43

Conformity assessment

1.
The provider shall opt for one of the following procedures based on:

(a)

the internal control; or

(b)

the assessment of the quality management system.

In demonstrating the compliance, the provider shall follow the procedure set out in Annex VII where:

(a)

harmonised standards do not exist;

(b)

the provider has not applied the harmonised standard.

## CHAPTER VII

GOVERNANCE

## SECTION 1

Governance at Union level

### Article 64

AI Office

1.
The Commission shall develop Union expertise and capabilities in the field of AI through the AI Office.

## ANNEX III

High-risk AI systems referred to in Article 6(2)

1.
Biometrics:

(a)

remote biometric identification systems.

This shall not include AI systems intended to be used for biometric verification;

(b)

AI systems intended to be used for biometric categorisation.

## ANNEX VII

Conformity based on an assessment of the quality management system

3.
Quality management system

3.1. The application of the provider shall include:

(a)

the name and address of the provider;

(b)

the list of AI systems covered.

3.2. The quality management system shall be assessed by the notified body.

## ANNEX X

## Union legislative acts on large-scale IT systems in the area of Freedom, Security and Justice

1.
Schengen Information System
"""


def _nodes(text: str = ACT) -> dict[str, dict]:
    return {n["id"]: n for n in parse_act(text, "AIA", source_doc="ai-act-consolidated")}


# ---- parser ------------------------------------------------------------------------------


def test_parser_version_is_2():
    assert PARSER_VERSION == 2


def test_trailing_subparagraph_belongs_to_the_paragraph_not_the_last_point():
    nodes = _nodes()
    assert nodes["AIA.6.3.d"]["text"] == "the AI system is intended to perform a preparatory task."
    assert "Notwithstanding the first subparagraph" in nodes["AIA.6.3"]["text"]
    # ... and to the paragraph that holds a sub-point list
    assert "Point (h) of the first subparagraph" in nodes["AIA.5.1"]["text"]
    assert nodes["AIA.5.1.h.iii"]["text"] == "the localisation of a suspect."


def test_text_between_two_points_stays_with_the_point():
    nodes = _nodes()
    assert "biometric verification" in nodes["AIA.ANNEX_III.1.a"]["text"]
    assert "biometric verification" not in nodes["AIA.ANNEX_III.1"]["text"]


def test_roman_i_after_h_is_a_sub_point_when_ii_follows():
    nodes = _nodes()
    assert {"AIA.5.1.h.i", "AIA.5.1.h.ii", "AIA.5.1.h.iii"} <= set(nodes)
    assert "AIA.5.1.i" not in nodes
    assert nodes["AIA.5.1.h.i"]["path"] == ["Art 5", "para 1", "pt h", "pt i"]
    # (i) between (h) and (j) stays the letter
    assert nodes["AIA.16.i"]["parent"] == "AIA.16"
    assert nodes["AIA.16.j"]["parent"] == "AIA.16"


def test_a_restarted_list_keeps_its_lead_in_on_the_paragraph():
    nodes = _nodes()
    assert "In demonstrating the compliance" in nodes["AIA.43.1"]["text"]
    assert nodes["AIA.43.1.b"]["text"] == "the assessment of the quality management system."
    assert nodes["AIA.43.1.a_2"]["text"] == "harmonised standards do not exist;"


def test_annex_decimal_points_and_headings():
    nodes = _nodes()
    assert nodes["AIA.ANNEX_VII.3"]["text"] == "Quality management system"
    assert nodes["AIA.ANNEX_VII.3.1"]["text"] == "The application of the provider shall include:"
    assert nodes["AIA.ANNEX_VII.3.1.b"]["parent"] == "AIA.ANNEX_VII.3.1"
    assert nodes["AIA.ANNEX_VII.3.1.b"]["text"] == "the list of AI systems covered."
    assert nodes["AIA.ANNEX_VII.3.2"]["text"].startswith("The quality management system")
    assert nodes["AIA.ANNEX_X"]["title"].startswith("Union legislative acts")
    assert nodes["AIA.6.3"]["chapter_title"] == "HIGH-RISK AI SYSTEMS"
    assert nodes["AIA.6.3"]["section_title"] == "Classification of AI systems as high-risk"
    assert nodes["AIA.64"]["chapter_title"] == "GOVERNANCE"


def test_shared_fixture_still_parses_the_same_ids():
    ids = set(_nodes(CONSOLIDATED))
    assert {"AIA.10.2.f", "AIA.113.c.i", "AIA.113.c.ii", "AIA.ANNEX_III.4.a"} <= ids


# ---- search ------------------------------------------------------------------------------


def _governance_corpus() -> list[dict]:
    return list(_nodes(CONSOLIDATED).values()) + [
        {
            "id": "AIA.1.2.f",
            "instrument": "AIA",
            "kind": "point",
            "path": ["Art 1", "para 2", "pt f"],
            "parent": None,
            "title": None,
            "text": "rules on market monitoring, market surveillance, governance and enforcement;",
            "source_doc": "ai-act-consolidated",
        },
        {
            "id": "AIA.REC.67",
            "instrument": "AIA",
            "kind": "recital",
            "path": ["Recital 67"],
            "parent": None,
            "title": None,
            "text": "High-quality data and access to it play a vital role; appropriate data governance and management practices.",
            "source_doc": "ai-act",
        },
    ]


def test_labels_read_like_citations():
    assert label({"path": ["Art 10", "para 2", "pt f"], "instrument": "AIA"}) == "Art. 10(2)(f)"
    assert (
        label({"path": ["Annex III", "pt 4", "pt a"], "instrument": "AIA"})
        == "Annex III, point 4(a)"
    )
    assert (
        label({"path": ["Annex VIII", "Section A", "pt 1"], "instrument": "AIA"})
        == "Annex VIII, Section A, point 1"
    )
    assert label({"path": ["Annex VII", "pt 3", "pt 1"], "instrument": "AIA"}) == (
        "Annex VII, point 3.1"
    )
    assert label({"path": ["Recital 27"], "instrument": "AIA"}) == "Recital 27"
    assert label({"path": ["Art 1", "pt 12"], "instrument": "OMNIBUS"}) == "Omnibus Art. 1(12)"


def test_governance_ranks_the_titled_article_first_with_an_inherited_title():
    corpus = _governance_corpus()
    corpus.append(
        {
            "id": "AIA.10.3",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 10", "para 3"],
            "parent": "AIA.10",
            "title": None,
            "text": "Training data sets shall be subject to data governance and management practices.",
            "source_doc": "ai-act-consolidated",
        }
    )
    total, hits = search(corpus, "governance", binding={"ai-act": False})
    assert total == 3
    ids = [h["id"] for h in hits]
    assert ids[0] == "AIA.10.3"  # Art. 10 "Data and data governance": title + text
    assert ids.index("AIA.1.2.f") > 0
    assert hits[-1]["id"] == "AIA.REC.67"  # a recital explains, the articles state the law
    top = hits[0]
    assert top["label"] == "Art. 10(3)"
    assert top["title"] == "Data and data governance" and top["title_inherited"] is True
    assert "governance" in top["snippet"] and top["match"] == "text"
    assert top["also"] == ["AIA.10"]  # the article itself is folded into the hit
    assert hits[-1]["binding"] is False and top["binding"] is True
    assert top["source"] == "ai-act-consolidated"


def test_a_heading_match_alone_returns_the_article_not_its_paragraphs():
    corpus = list(_nodes().values())
    total, hits = search(corpus, "governance")
    by_id = {h["id"]: h for h in hits}
    assert "AIA.64" in by_id and by_id["AIA.64"]["match"] == "heading"
    assert "GOVERNANCE" in by_id["AIA.64"]["snippet"]
    assert "AIA.64.1" not in by_id


def test_whole_words_beat_partial_matches_and_all_terms_are_required():
    corpus = [
        {
            "id": "X.1",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 1", "para 1"],
            "parent": None,
            "title": None,
            "text": "The human operator keeps oversight of the system.",
        },
        {
            "id": "X.2",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 2", "para 1"],
            "parent": None,
            "title": None,
            "text": "Human oversight measures shall be built in.",
        },
        {
            "id": "X.3",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 3", "para 1"],
            "parent": None,
            "title": None,
            "text": "Oversight bodies exist.",
        },
        {
            "id": "X.4",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 4", "para 1"],
            "parent": None,
            "title": None,
            "text": "The humanitarian oversight function.",
        },
    ]
    _, hits = search(corpus, "human oversight")
    assert [h["id"] for h in hits] == ["X.2", "X.1"]


def test_snippet_holds_the_query_term_and_stays_short():
    text = (
        ("Lorem ipsum dolor sit amet. " * 20)
        + "The data governance practices apply. "
        + ("Consectetur adipiscing elit. " * 20)
    )
    out = snippet(text, parse_query("governance"))
    assert "governance" in out and len(out) <= 270
    assert out.startswith("… ") and out.endswith(" …")


def test_search_is_deterministic():
    corpus = _governance_corpus()
    assert search(corpus, "data governance") == search(list(corpus), "data governance")


def test_hyphenated_compounds_and_recitals():
    corpus = [
        {
            "id": "X.1",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 1", "para 1"],
            "parent": None,
            "title": None,
            "text": "A high-risk AI system shall be registered.",
        },
        {
            "id": "X.2",
            "instrument": "AIA",
            "kind": "paragraph",
            "path": ["Art 2", "para 1"],
            "parent": None,
            "title": None,
            "text": "The risk shall be assessed.",
        },
        {
            "id": "AIA.REC.9",
            "instrument": "AIA",
            "kind": "recital",
            "path": ["Recital 9"],
            "parent": None,
            "title": None,
            "text": "The risk is explained here.",
            "source_doc": "ai-act",
        },
    ]
    _, hits = search(corpus, "risk")
    assert [h["id"] for h in hits] == ["X.2", "AIA.REC.9"]  # "high-risk" is not "risk"
    assert hits[1]["binding"] is False and hits[1]["label"] == "Recital 9"
