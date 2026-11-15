"""The obligation catalogue: schema + cross-checks against a real release's provision ids,
deterministic activation, the release snapshot, ``GET /v1/obligations``,
``GET /v1/releases/{a}/diff/{b}`` and ``impacted_obligations`` on a RegChange."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from kb_fixtures import CONSOLIDATED
from test_kb import CATALOG, _record_text
from test_watch import stack  # noqa: F401 - the fake web + mirror fixture

from engine.kb.corpus import load_corpus
from engine.kb.obligations import (
    Obligation,
    activate,
    basis_parts,
    check_obligations,
    load_obligations,
)
from engine.kb.releases import KnowledgeBase
from utils import kb as kb_utils

#: Every provision id of the active release 2026.11.15-1 (AIA, consolidated, post-Omnibus).
IDS_FILE = Path(__file__).parent / "fixtures" / "aia_provision_ids_2026.11.15-1.txt"
TODAY = date(2026, 11, 15)


def _ids() -> set[str]:
    return set(IDS_FILE.read_text(encoding="utf-8").split())


def test_catalogue_is_valid_and_matches_the_kb():
    obls = load_obligations()
    reqs, tts = load_corpus()
    assert len(obls) >= 30
    ids = {o["id"] for o in obls}
    for must in (
        "OBL.AIA.4.ai-literacy",
        "OBL.AIA.5.prohibited-practices-screening",
        "OBL.AIA.4a.special-category-data",
        "OBL.AIA.9.6.testing",
        "OBL.AIA.10.2.f.bias-examination",
        "OBL.AIA.13.3.b.ii.declared-accuracy",
        "OBL.AIA.14.4.human-oversight",
        "OBL.AIA.15.5.cybersecurity",
        "OBL.AIA.49.1.registration",
        "OBL.AIA.50.1.ai-interaction-disclosure",
        "OBL.AIA.73.serious-incident-reporting",
    ):
        assert must in ids
    # every article / related id exists in the release, every template and requirement too,
    # and every requirement is covered by an obligation
    warnings = check_obligations(obls, _ids(), {t["id"] for t in tts}, {r["id"] for r in reqs})
    assert warnings == []
    modes = {o["verification_mode"] for o in obls}
    assert modes == {"model_test", "system_test", "hybrid", "documentary"}
    for o in obls:
        if o["verification_mode"] == "model_test":
            assert o["checks"], o["id"]


def test_schema_rejects_bad_rows():
    base = {
        "id": "OBL.AIA.15.1.accuracy",
        "article": "AIA.15.1",
        "addressee": ["provider"],
        "in_force": {"annex_iii": "2027-12-02"},
        "verification_mode": "model_test",
        "summary": "x",
    }
    assert Obligation.model_validate(base).in_force == {"annex_iii": "2027-12-02"}
    with pytest.raises(ValueError):
        Obligation.model_validate({**base, "in_force": {"annex_ii": "2027-12-02"}})
    with pytest.raises(ValueError):
        Obligation.model_validate({**base, "verification_mode": "vibes"})
    with pytest.raises(ValueError):
        Obligation.model_validate({**base, "id": "REQ.AIA.15.1.accuracy"})


@pytest.mark.parametrize(
    ("basis", "expected"),
    [
        ("Annex III 4(a)", ("annex_iii", "4.a")),
        ("AIA.ANNEX_III.5.b", ("annex_iii", "5.b")),
        ("annex_iii", ("annex_iii", None)),
        ("Annex I", ("annex_i", None)),
        (None, (None, None)),
    ],
)
def test_basis_parts(basis, expected):
    assert basis_parts(basis) == expected


def _by_id(**query):
    return {
        o["id"]: activate(o, **{"features": None, "exempt_6_3": None, "on": TODAY, **query})
        for o in load_obligations()
    }


def test_activation_provider_high_risk_annex_iii():
    rows = _by_id(role="provider", risk_class="high", basis="Annex III 4(a)", features=[])
    f = rows["OBL.AIA.10.2.f.bias-examination"]
    assert f["applicable"] and f["in_force_date"] == "2027-12-02" and not f["in_force_now"]
    assert rows["OBL.AIA.4.ai-literacy"]["in_force_now"] is True
    assert not rows["OBL.AIA.50.1.ai-interaction-disclosure"]["applicable"]
    # no 6(3) claim given -> exemption rows are not filtered (None = not checked) ...
    assert rows["OBL.AIA.6.4.non-high-risk-assessment"]["applicable"]
    # ... a declared "no claim" drops them
    rows = _by_id(
        role="provider", risk_class="high", basis="Annex III 4(a)", features=[], exempt_6_3=False
    )
    assert not rows["OBL.AIA.6.4.non-high-risk-assessment"]["applicable"]
    assert "6(3)" in rows["OBL.AIA.6.4.non-high-risk-assessment"]["reason"]
    annex_i = _by_id(role="provider", risk_class="high", basis="annex_i", exempt_6_3=False)
    assert annex_i["OBL.AIA.15.1.accuracy"]["in_force_date"] == "2028-08-02"
    assert not annex_i["OBL.AIA.49.1.registration"]["applicable"]  # Annex III only


def test_activation_deployer_keeps_only_operator_duties():
    rows = _by_id(role="deployer", risk_class="high", basis="Annex III 5(a)", features=[])
    applicable = {k for k, v in rows.items() if v["applicable"]}
    assert applicable == {"OBL.AIA.4.ai-literacy", "OBL.AIA.5.prohibited-practices-screening"}
    assert "system role is deployer" in rows["OBL.AIA.15.1.accuracy"]["reason"]


async def test_release_snapshot_api_and_diff(api, stack, data_dir):  # noqa: F811
    first = (await api.post("/v1/watch/check-now", json={"wait": True})).json()
    baseline = first["release"]["kb_version"]
    manifest = (await api.get(f"/v1/releases/{baseline}")).json()
    assert manifest["counts"]["obligations"] == len(load_obligations())
    assert "obligations" in manifest["hashes"]
    assert (data_dir / "kb" / "releases" / baseline / "obligations.yaml").exists()

    body = (
        await api.get(
            "/v1/obligations",
            params={
                "role": "provider",
                "risk_class": "high",
                "basis": "annex_iii",
                "annex_point": "4.a",
                "features": ["none"],
                "exempt_6_3": "false",
                "date": "2026-11-15",
            },
        )
    ).json()
    assert body["kb_version"] == baseline and body["catalogue_source"] == "release"
    ids = {o["id"] for o in body["items"]}
    assert "OBL.AIA.10.2.f.bias-examination" in ids
    assert "OBL.AIA.50.1.ai-interaction-disclosure" not in ids
    assert body["query"]["basis"] == "AIA.ANNEX_III.4.a"
    row = next(o for o in body["items"] if o["id"] == "OBL.AIA.10.2.f.bias-examination")
    assert row["in_force_now"] is False and row["article_hash"].startswith("sha256:")
    every = (
        await api.get("/v1/obligations", params={"role": "deployer", "include_not_applicable": 1})
    ).json()
    assert every["total"] == len(load_obligations())
    assert (
        await api.get("/v1/obligations", params={"kb_version": "2020.01.01-1"})
    ).status_code == 404

    # a change to the bias-examination guidance -> RegChange with impacted obligations
    await api.put(
        "/v1/demo/mirror",
        json={
            "find": "postcode or career gaps.",
            "replace": "postcode, career gaps or nationality.",
        },
    )
    check = (
        await api.post(
            "/v1/watch/check-now",
            json={"source_ids": ["demo-art6-guideline-mirror"], "wait": True},
        )
    ).json()
    rel = check["release"]
    change = (await api.get(f"/v1/changes/{rel['change_id']}")).json()
    hit = {i["obligation_id"]: i for i in change["impacted_obligations"]}
    assert "OBL.AIA.10.2.f.bias-examination" in hit
    assert "AIA.10.2.f" in hit["OBL.AIA.10.2.f.bias-examination"]["via"]

    # provisions did not change (only guidance): an empty provision diff
    diff = (await api.get(f"/v1/releases/{baseline}/diff/{rel['kb_version']}")).json()
    assert diff["provisions"] == [] and diff["counts"]["obligations"] == 0
    narrowed = (
        await api.get(
            f"/v1/releases/{baseline}/diff/{rel['kb_version']}",
            params={"provisions": "AIA.10,AIA.15"},
        )
    ).json()
    assert narrowed["provisions_filter"] == ["AIA.10", "AIA.15"]
    missing = await api.get(f"/v1/releases/{baseline}/diff/2020.01.01-1")
    assert missing.status_code == 404


def test_release_diff_reports_changed_provisions(store, monkeypatch):
    kb = KnowledgeBase(store)
    _record_text(store, "ai-act-consolidated", "ai-act-consolidated", CONSOLIDATED)
    first, _ = kb.build_release(CATALOG)
    changed = CONSOLIDATED.replace(
        "possible biases that are likely to affect the health and safety of persons;",
        "possible biases that are likely to affect the health, safety or rights of persons;",
    )
    _record_text(store, "ai-act-consolidated", "ai-act-consolidated", changed)
    second, _ = kb.build_release(CATALOG)
    monkeypatch.setattr(kb_utils, "get_kb", lambda: kb)
    out = kb_utils.release_diff(first["kb_version"], second["kb_version"], ["AIA.10"])
    assert [p["id"] for p in out.provisions] == ["AIA.10.2.f"]
    assert out.provisions[0]["change"] == "changed" and "+" in out.provisions[0]["diff"]
    none = kb_utils.release_diff(first["kb_version"], second["kb_version"], ["AIA.15"])
    assert none.provisions == []
