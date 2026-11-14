# ruff: noqa: E501
"""Knowledge base: provision parser, releases, provision-level diff, change types,
requirements applicability. Gemini is mocked (no paid calls)."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from kb_fixtures import CONSOLIDATED, OMNIBUS

from core.settings import LlmSettings
from engine.catalog.loader import Catalog
from engine.kb import changes as kb_changes
from engine.kb.applicability import applicable
from engine.kb.changes import build_change, heuristic_change_type
from engine.kb.corpus import check_corpus, load_corpus
from engine.kb.interpretations import find_references
from engine.kb.parser import content_hash, link_amendments, parse_act, parse_recitals
from engine.kb.releases import KnowledgeBase
from engine.llm import gemini as gemini_mod
from engine.llm.gemini import Gemini

CATALOG = Catalog.model_validate(
    {
        "sources": [
            {
                "id": "ai-act-consolidated",
                "title": "AI Act consolidated",
                "kind": "consolidated",
                "binding": True,
                "fetcher": "cellar",
                "celex": "02024R1689-20260727",
            },
            {
                "id": "guide",
                "title": "Guide",
                "kind": "guideline",
                "binding": False,
                "status": "draft",
                "fetcher": "http",
                "url": "https://example.eu/guide",
            },
        ]
    }
)


def _by_id(nodes):
    return {n["id"]: n for n in nodes}


def _record_text(store, doc_id: str, source_id: str, text: str) -> None:
    store.record(
        doc_id=doc_id,
        source_id=source_id,
        url=f"https://example.eu/{doc_id}",
        content=text.encode(),
        ext="md",
        content_type="text/markdown",
    )
    from engine.extract.stage import extract_pending

    extract_pending(store, [source_id])


def _gemini(key: str = "") -> Gemini:
    return Gemini(LlmSettings(GOOGLE_API_KEY=key, GEMINI_MODEL="gemini-test"))


# ---- parser ----------------------------------------------------------------------------------


def test_parser_ids_paths_dates_and_amendments():
    nodes = _by_id(parse_act(CONSOLIDATED, "AIA", source_doc="ai-act-consolidated"))
    assert {
        "AIA.3",
        "AIA.3.1",
        "AIA.3.2",
        "AIA.6.2",
        "AIA.9.1",
        "AIA.9.2.a",
        "AIA.10.1",
        "AIA.10.2.f",
        "AIA.10.2.g",
        "AIA.50.1",
        "AIA.113.c.i",
        "AIA.113.c.ii",
        "AIA.ANNEX_III",
        "AIA.ANNEX_III.4.a",
    } <= set(nodes)
    f = nodes["AIA.10.2.f"]
    assert f["path"] == ["Art 10", "para 2", "pt f"]
    assert f["text"].startswith("examination in view of possible biases")
    assert f["content_hash"] == content_hash(f["text"])
    assert f["parent"] == "AIA.10.2"
    # ▼M1 marker -> amended_by resolves the header table to the amending act
    assert nodes["AIA.10.1"]["amended_by"] == ["Regulation (EU) 2026/1744"]
    assert nodes["AIA.10.2.f"]["amended_by"] == []
    # application dates from Art. 113 as amended
    assert nodes["AIA.3.1"]["valid_from"] == "2025-02-02"
    assert nodes["AIA.10.2.f"]["valid_from"] == "2027-12-02"
    assert nodes["AIA.10.2.f"]["valid_from_by_basis"]["annex_i"] == "2028-08-02"
    assert nodes["AIA.50.1"]["valid_from"] == "2026-08-02"
    assert nodes["AIA.ANNEX_III.4.a"]["valid_from"] == "2027-12-02"
    assert nodes["AIA.9"]["text"].startswith("Risk management system")


def test_parser_is_deterministic_and_links_omnibus_points():
    a = parse_act(CONSOLIDATED, "AIA")
    b = parse_act(CONSOLIDATED, "AIA")
    assert [(n["id"], n["content_hash"]) for n in a] == [(n["id"], n["content_hash"]) for n in b]
    omnibus = parse_act(OMNIBUS, "OMNIBUS")
    assert [n["id"] for n in omnibus] == ["OMNIBUS.1", "OMNIBUS.1.1", "OMNIBUS.1.2"]
    link_amendments(a, omnibus, "Regulation (EU) 2026/1744")
    nodes = _by_id(a)
    assert nodes["AIA.10.1"]["amended_by"] == ["OMNIBUS.1.1"]
    assert nodes["AIA.113.c"]["amended_by"] == ["OMNIBUS.1.2"]
    recitals = parse_recitals(OMNIBUS, "OMNIBUS")
    assert (
        recitals[0]["id"] == "OMNIBUS.REC.1" and recitals[0]["text"] == "Simplification is needed."
    )


def test_interpretation_references():
    known = {
        "AIA.6",
        "AIA.6.2",
        "AIA.10",
        "AIA.10.2",
        "AIA.10.2.f",
        "AIA.ANNEX_III",
        "AIA.ANNEX_III.4.a",
    }
    text = (
        "Under point 4(a) of Annex III and Article 6(2); see Art. 10(2), point (f), Article 99(1)."
    )
    refs = find_references(text, known)
    assert refs == ["AIA.6.2", "AIA.10.2.f", "AIA.ANNEX_III.4.a"]


# ---- change types ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "kind", "expected"),
    [
        ("Providers shall test.", "Providers  shall test", "provision", "editorial"),
        ("It applies from 2 August 2026.", "It applies from 2 December 2027.", "provision", "date"),
        ("Providers shall test.", "Providers may test if feasible.", "provision", "substantive"),
        (None, "New text.", "provision", "substantive"),
        (None, "New guidance.", "interpretation", "new_interpretation"),
        ("Old reading.", "A different reading.", "interpretation", "new_interpretation"),
        ("Old reading.", "old reading", "interpretation", "editorial"),
    ],
)
def test_heuristic_change_types(old, new, kind, expected):
    ctype, why = heuristic_change_type(old, new, kind)
    assert ctype == expected and why


# ---- releases + RegChange ----------------------------------------------------------------------


async def test_release_diff_regchange_and_activation(store):
    kb = KnowledgeBase(store)
    _record_text(store, "ai-act-consolidated", "ai-act-consolidated", CONSOLIDATED)
    first, created = kb.build_release(CATALOG, trigger="t1")
    assert created and first["parent"] is None and first["status"] == "candidate"
    assert first["counts"]["requirements"] > 20 and first["counts"]["test_templates"] == 8
    again, created_again = kb.build_release(CATALOG)
    assert not created_again and again["kb_version"] == first["kb_version"]
    kb.activate(first["kb_version"], by="test")
    assert kb.active_version() == first["kb_version"]

    changed = CONSOLIDATED.replace(
        "possible biases that are likely to affect the health and safety of persons;",
        "possible biases that are likely to affect the health, safety or rights of persons;",
    ).replace("It shall apply from 2 August 2026.", "It shall apply from 2 December 2026.")
    _record_text(store, "ai-act-consolidated", "ai-act-consolidated", changed)
    second, created = kb.build_release(CATALOG, trigger="t2")
    assert created and second["parent"] == first["kb_version"]
    assert second["kb_version"].endswith("-2")

    change = await build_change(kb, first["kb_version"], second["kb_version"], _gemini())
    by_id = {e["id"]: e for e in change["provisions"]}
    assert set(by_id) == {"AIA.10.2.f", "AIA.113"}
    assert by_id["AIA.10.2.f"]["change_type"] == "substantive"
    assert by_id["AIA.113"]["change_type"] == "date"
    assert by_id["AIA.10.2.f"]["classified_by"] == "heuristic"
    assert "health, safety or rights" in by_id["AIA.10.2.f"]["new_text"]
    assert by_id["AIA.10.2.f"]["old_hash"] != by_id["AIA.10.2.f"]["new_hash"]
    impacted = {i["requirement_id"] for i in change["impacted_requirements"]}
    assert "REQ.AIA.10.2.f.bias-examination" in impacted
    assert change["id"] == f"RC-{second['kb_version']}"
    assert kb_changes.load_change(kb, change["id"])["summary"] == change["summary"]

    # still a candidate until the explicit activation (HITL accept)
    assert kb.load_manifest(second["kb_version"])["status"] == "candidate"
    kb.activate(second["kb_version"], by="engineer")
    assert kb.load_manifest(second["kb_version"])["status"] == "active"
    assert kb.load_manifest(first["kb_version"])["status"] == "superseded"
    assert [m["kb_version"] for m in kb.list_releases()] == [
        second["kb_version"],
        first["kb_version"],
    ]
    old = kb.provision_map(first["kb_version"])["AIA.10.2.f"]
    assert "health and safety" in old["text"] and old["kb_version"] == first["kb_version"]


class _FakeModels:
    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(text=self.answer)


def _fake_client(monkeypatch, answer):
    models = _FakeModels(answer)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    monkeypatch.setattr(gemini_mod, "client_factory", lambda key: client)
    return models


def _entries():
    return [
        {
            "id": "AIA.10.2.f",
            "kind": "provision",
            "change": "changed",
            "binding": True,
            "old_text": "Providers shall test.",
            "new_text": "Deployers shall test.",
        }
    ]


async def test_gemini_classifies_with_structured_output(monkeypatch):
    answer = [{"id": "AIA.10.2.f", "change_type": "scope", "rationale": "Actor changed."}]
    models = _fake_client(monkeypatch, json.dumps(answer))
    entries = _entries()
    await kb_changes.classify(entries, _gemini("key"))
    assert entries[0]["change_type"] == "scope"
    assert entries[0]["classified_by"] == "gemini:gemini-test"
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"].response_mime_type == "application/json"


async def test_gemini_failure_falls_back_to_heuristic(monkeypatch):
    _fake_client(monkeypatch, RuntimeError("quota"))
    entries = _entries()
    await kb_changes.classify(entries, _gemini("key"))
    assert entries[0]["classified_by"] == "heuristic"
    assert entries[0]["change_type"] == "substantive"


async def test_no_key_never_calls_gemini(monkeypatch):
    models = _fake_client(monkeypatch, "[]")
    entries = _entries()
    await kb_changes.classify(entries, _gemini(""))
    assert models.calls == [] and entries[0]["classified_by"] == "heuristic"


# ---- corpus + applicability -------------------------------------------------------------------


def test_shipped_corpus_is_consistent():
    reqs, tts = load_corpus()
    assert len(reqs) >= 25 and len(tts) == 8
    ids = {r["id"] for r in reqs}
    assert "REQ.AIA.10.2.f.bias-examination" in ids
    assert all(r["provenance"] == "drafted_by_agent" and r["review"] == "pending" for r in reqs)
    provisions = {p for r in reqs for p in [r["source"], *r["related"]]}
    assert check_corpus(reqs, tts, provisions) == []  # templates <-> requirements consistent


def test_requirements_applicability():
    reqs, _ = load_corpus()
    for r in reqs:
        if r["applies_if"]["risk_class"] == ["high"]:
            r["valid_from"] = "2027-12-02"
            r["valid_from_by_basis"] = {"annex_iii": "2027-12-02", "annex_i": "2028-08-02"}
        else:
            r["valid_from"] = "2026-08-02"
    high = applicable(
        reqs, role="provider", risk_class="high", basis="AIA.ANNEX_III.4.a", on=date(2026, 11, 14)
    )
    ids = {r["id"] for r in high}
    assert "REQ.AIA.10.2.f.bias-examination" in ids
    assert "REQ.AIA.6.2.annex-iii-high-risk" in ids
    assert "REQ.AIA.50.1.ai-interaction-disclosure" not in ids  # needs the feature
    f = next(r for r in high if r["id"] == "REQ.AIA.10.2.f.bias-examination")
    assert f["in_force"] is False and f["effective_valid_from"] == "2027-12-02"
    later = applicable(
        reqs, role="provider", risk_class="high", basis="annex_i", on=date(2028, 1, 1)
    )
    f = next(r for r in later if r["id"] == "REQ.AIA.10.2.f.bias-examination")
    assert f["effective_valid_from"] == "2028-08-02" and f["in_force"] is False
    chatbot = applicable(
        reqs, role="provider", risk_class="limited", features=["chatbot"], on=date(2026, 11, 14)
    )
    ids = {r["id"] for r in chatbot}
    assert "REQ.AIA.50.1.ai-interaction-disclosure" in ids
    assert "REQ.AIA.10.2.f.bias-examination" not in ids
    assert all(r["in_force"] for r in chatbot)
    assert applicable(reqs, role="deployer", risk_class="high") == []
