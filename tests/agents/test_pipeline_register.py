"""Findings-register hydration: load_context reads it, seal stamps register_status (no LLM)."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pipeline.register import annotate, load_register, register_brief, register_status
from pipeline_fakes import AUDIT_ID, SYSTEM_ID, build_graph, make_harness

from core.settings import settings

CONFIG = {"configurable": {"thread_id": "audit-AUD-1"}}
BIAS = "OBL.AIA.10.2.f.bias-examination"


@pytest.fixture(autouse=True)
def _fake_llm():
    settings.gemini.fake_llm = True
    settings.pipeline.max_auto_redos = 1
    settings.pipeline.max_redos = 3


def _item(obligation: str, state: str, verdict: str, history=None, **extra) -> dict[str, Any]:
    return {
        "obligation_id": obligation,
        "state": state,
        "verdict": verdict,
        "first_seen_audit_id": "SYS-001-20261114-0900",
        "history": history or [],
        **extra,
    }


@pytest.mark.parametrize(
    ("item", "verdict", "gap_id", "expected"),
    [
        (None, "gap", "G-1", "new"),
        (_item("o", "open", "gap"), "gap", "G-1", "still_open"),
        (_item("o", "open", "gap"), "pass", None, "resolved"),
        (
            _item("o", "resolved", "pass", [{"to": "open"}, {"to": "resolved"}]),
            "gap",
            "G",
            "regressed",
        ),
        (_item("o", "monitoring", "pass"), "gap", "G-1", "new"),
        (_item("o", "monitoring", "pass"), "pass", None, "unchanged"),
        (
            _item("o", "closed", "partial", [{"kind": "closed", "verdict": "partial"}]),
            "partial",
            "G-1",
            "accepted_risk",
        ),
        (
            _item("o", "closed", "partial", [{"kind": "closed", "verdict": "partial"}]),
            "gap",
            "G-1",
            "regressed",
        ),
    ],
)
def test_register_status_mirrors_the_backend(item, verdict, gap_id, expected):
    assert register_status(item, verdict, gap_id) == expected


async def test_load_register_is_best_effort():
    class NoRegister:
        pass

    class Broken:
        async def register(self):
            raise RuntimeError("down")

    assert await load_register(NoRegister()) == []
    assert await load_register(Broken()) == []


def test_brief_splits_open_and_accepted():
    reg = [
        _item("a", "open", "gap", article="Art. 10"),
        _item("b", "closed", "partial", close_reason="DPO accepted"),
        _item("c", "resolved", "pass"),
    ]
    brief = register_brief(reg)
    assert [i["obligation_id"] for i in brief["open"]] == ["a"]
    assert brief["accepted_risks"][0]["close_reason"] == "DPO accepted"
    assert brief["resolved"] == ["c"]
    assert register_brief([]) is None
    proposed = [{"obligation_id": "a", "verdict": "pass"}, {"obligation_id": "z", "verdict": "gap"}]
    annotate(proposed, reg)
    assert proposed[0]["register_status"] == "resolved"
    assert proposed[0]["register_since"] == "SYS-001-20261114-0900"
    assert proposed[1]["register_status"] == "new"


async def test_pipeline_hydrates_and_stamps_sealed_findings():
    h = make_harness()
    register = [_item(BIAS, "open", "gap", article="Art. 10(2)(f)")]

    async def fetch_register() -> dict[str, Any]:
        return {"system_id": SYSTEM_ID, "items": register}

    h.backend.register = fetch_register  # type: ignore[attr-defined]
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke({"audit_id": AUDIT_ID, "system_id": SYSTEM_ID}, CONFIG)
    for _ in range(2):
        pending = (await graph.aget_state(CONFIG)).interrupts[0]
        await graph.ainvoke(Command(resume={pending.id: {"decision": "approved"}}), CONFIG)
    state = (await graph.aget_state(CONFIG)).values
    assert state["register"] == register
    by = {f["obligation_id"]: f for f in h.backend.sealed}
    assert by[BIAS]["register_status"] == "still_open"
    assert by[BIAS]["register_since"] == "SYS-001-20261114-0900"
    others = [f for o, f in by.items() if o != BIAS]
    assert others and all(f["register_status"] == "new" for f in others)
