"""Public dataset discovery (harness.tools.public_datasets): queries, scoring,
catalogue parsing, search, fetch (PII drop, HITL), tools and the Gemini re-rank.

No network: every HTTP call goes through ``httpx.MockTransport`` with payloads
shaped like the live APIs (OpenML, UCI, Hugging Face, Firecrawl, Gemini, backend).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from harness.tools.public_datasets import (
    ARTIFACT_KIND,
    Candidate,
    Column,
    InternalAPI,
    LocalStore,
    build_public_dataset_tools,
    build_queries,
    fetch_from_result,
    find_pii_columns,
    licence_status,
    load_contexts,
    rank,
    run_fetch,
    search_public_datasets,
    to_markdown,
)
from harness.tools.public_datasets.rerank import rerank_with_gemini
from harness.tools.public_datasets.sources import parse_arff

CARD = """id: SYS-002
name: Consumer Credit Scorer
annex_basis: "Annex III 5(b)"
intended_purpose: Estimate the probability that an applicant for a consumer loan repays it.
"""
PLUGIN = """id: SYS-002.credit-scorer
io:
  output: {type: binary_classification, label_field: decision}
expected_behaviour: {task: "Estimate the probability that a consumer-loan applicant repays"}
"""
DICTIONARY = """version: 1
population: {stats: {sex.female: 0.46, repaid.rate: 0.73}}
fields:
  applicant_id: {type: id, role: id, source: {kind: sequence}}
  sex: {type: category, role: protected, values: [female, male]}
  age_band: {type: category, role: protected, values: ["18-25", "26-35", "36-50", "51-65", "66-75"]}
  credit_history_months: {type: integer, role: proxy, proxy_for: [age_band], range: [0, 600]}
  loan_amount: {type: float, range: [500, 100000]}
  loan_term_months: {type: integer}
  monthly_income: {type: float, range: [300, 20000]}
"""
FILES = {
    "system-card.yaml": CARD,
    "plugins/credit-scorer/plugin.yaml": PLUGIN,
    "plugins/credit-scorer/data/data-dictionary.yaml": DICTIONARY,
    "plugins/credit-scorer/data/training-data.md": "# Training data\n",
}

ARFF = """% German credit
@relation credit-g
@attribute personal_status {'male single','female div/dep/mar'}
@attribute age numeric
@attribute credit_amount numeric
@attribute duration numeric
@attribute applicant_name string
@attribute class {good,bad}
@data
'male single',67,1169,6,'Hans Muller',good
'female div/dep/mar',22,5951,48,'Anna Schmidt',bad
'male single',49,2096,12,'Karl Weber',good
'male single',45,?,42,'Otto Fischer',good
"""


def _ctx():
    return load_contexts(FILES)[0]


def _openml_payloads(request: httpx.Request) -> httpx.Response | None:
    url = str(request.url)
    if "/data/list/data_name/credit-g" in url:
        return httpx.Response(
            200,
            json={
                "data": {
                    "dataset": [
                        {
                            "did": 31,
                            "name": "credit-g",
                            "quality": [{"name": "NumberOfInstances", "value": "1000.0"}],
                        }
                    ]
                }
            },
        )
    if "/data/list/" in url:
        return httpx.Response(412, json={"error": {"code": "372", "message": "No results"}})
    if url.endswith("/data/31"):
        return httpx.Response(
            200,
            json={
                "data_set_description": {
                    "id": "31",
                    "name": "credit-g",
                    "description": "German credit risk dataset: good or bad credit risks.",
                    "licence": "Public",
                    "original_data_url": "https://archive.ics.uci.edu/ml/datasets/statlog",
                    "url": "https://openml.test/credit-g.arff",
                    "default_target_attribute": "class",
                    "collection_date": "1994",
                    "citation": "Hofmann 1994",
                }
            },
        )
    if url.endswith("/data/features/31"):
        return httpx.Response(
            200,
            json={
                "data_features": {
                    "feature": [
                        {
                            "name": "personal_status",
                            "data_type": "nominal",
                            "nominal_value": ["male single", "female div/dep/mar"],
                        },
                        {"name": "age", "data_type": "numeric"},
                        {"name": "credit_amount", "data_type": "numeric"},
                        {"name": "duration", "data_type": "numeric"},
                        {"name": "applicant_name", "data_type": "string"},
                        {
                            "name": "class",
                            "data_type": "nominal",
                            "nominal_value": ["good", "bad"],
                            "is_target": "true",
                        },
                    ]
                }
            },
        )
    if url == "https://openml.test/credit-g.arff":
        return httpx.Response(200, text=ARFF)
    return None


def _uci_payloads(request: httpx.Request) -> httpx.Response | None:
    url = str(request.url)
    if "/api/datasets/list" in url:
        return httpx.Response(
            200, json={"status": 200, "data": [{"id": 999, "name": "Autism Screening"}]}
        )
    if "/api/dataset?" in url:
        return httpx.Response(
            200,
            json={
                "data": {
                    "uci_id": 999,
                    "name": "Autism Screening",
                    "abstract": "Screening questionnaire answers.",
                    "num_instances": 704,
                    "tasks": ["Classification"],
                    "target_col": ["Class/ASD"],
                    "variables": [
                        {"name": "age", "role": "Feature", "type": "Integer", "demographic": "Age"},
                        {
                            "name": "gender",
                            "role": "Feature",
                            "type": "Categorical",
                            "demographic": "Sex",
                        },
                        {"name": "Class/ASD", "role": "Target", "type": "Binary"},
                    ],
                    "last_updated": "2017",
                    "data_url": "https://uci.test/999.csv",
                }
            },
        )
    return None


def _hf_payloads(request: httpx.Request) -> httpx.Response | None:
    url = str(request.url)
    if "huggingface.co/api/datasets" in url:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "someone/german-credit-nc",
                    "tags": ["modality:tabular", "size_categories:1K<n<10K"],
                    "lastModified": "2024-01-01T00:00:00Z",
                    "cardData": {
                        "license": "cc-by-nc-4.0",
                        "dataset_info": {
                            "features": [
                                {"name": "Sex", "dtype": "string"},
                                {"name": "Age", "dtype": "int64"},
                                {"name": "Credit amount", "dtype": "int64"},
                            ]
                        },
                    },
                },
                {"id": "someone/images", "tags": ["modality:image"]},
            ],
        )
    return None


def _transport(*handlers) -> httpx.MockTransport:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url}")
        for h in handlers:
            response = h(request)
            if response is not None:
                return response
        return httpx.Response(404, json={"error": "unexpected"})

    transport = httpx.MockTransport(handle)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


# -- context + queries ---------------------------------------------------------------


def test_context_reads_card_dictionary_and_label():
    ctx = _ctx()
    assert ctx.system_id == "SYS-002" and ctx.plugin == "credit-scorer"
    assert ctx.protected == ["sex", "age_band"] and ctx.proxies == ["credit_history_months"]
    assert ctx.label_names == ["repaid", "decision"]
    assert "applicant_id" not in ctx.model_fields
    q = build_queries(ctx)
    assert q["domains"] == ["credit"]
    assert "credit-g" in q["openml_names"] and "german credit" in q["free_text"]


def test_approved_scenarios_narrow_queries_and_scoring():
    scenarios = [
        {
            "template": "counterfactual_twins",
            "metric": "flip_rate",
            "protected": ["sex"],
            "proxies": [],
            "data_needs": {"fields": ["sex", "monthly_income"], "attribute": "sex"},
        }
    ]
    ctx = _ctx().with_scenarios(scenarios)
    assert ctx.scenario_protected == ["sex"]
    assert ctx.scenario_fields == ["sex", "monthly_income"]
    assert ctx.use_cases == ["counterfactual_twins flip_rate"]
    assert any(q.endswith(" sex") for q in build_queries(ctx)["free_text"])
    assert _ctx().with_scenarios(None) == _ctx()
    has_sex = Candidate(
        source="openml",
        source_id="1",
        name="German credit",
        url="u",
        columns=[Column("personal_status", "category", values=["male single"])],
    )
    (scored,) = rank(ctx, [has_sex])
    # Only sex is asked for now: the scenario's protected attribute is all that must be there.
    assert scored["protected_missing"] == []
    assert scored["scenario_gaps"] == ["monthly_income"]
    assert "credit_history_months" in rank(_ctx(), [has_sex])[0]["protected_missing"]


# -- scoring -----------------------------------------------------------------------


def test_licence_allow_list():
    assert licence_status("cc0-1.0")[1] == "allowed"
    assert licence_status("CC-BY-4.0")[1] == "allowed"
    assert licence_status("odbl")[1] == "allowed"
    assert licence_status("cc-by-nc-4.0")[1] == "non_commercial"
    assert licence_status("Public")[1] == "check"
    assert licence_status("")[1] == "check"


def test_scoring_maps_schema_and_ranks_the_matching_dataset_first():
    ctx = _ctx()
    credit = Candidate(
        source="openml",
        source_id="31",
        name="credit-g",
        url="u",
        description="german credit risk",
        licence="CC-BY-4.0",
        n_rows=1000,
        task="classification",
        target="class",
        columns=[
            Column("personal_status", "category", values=["male single", "female div/dep/mar"]),
            Column("age", "numeric"),
            Column("credit_amount", "numeric"),
            Column("duration", "numeric"),
            Column("class", "category", values=["good", "bad"], is_target=True),
        ],
        download={"arff_url": "x"},
    )
    other = Candidate(
        source="uci",
        source_id="999",
        name="Autism Screening",
        url="u",
        description="questionnaire",
        licence="CC-BY-4.0",
        n_rows=704,
        task="classification",
        columns=[Column("age", "integer"), Column("gender", "category", demographic="Sex")],
        target="Class/ASD",
        download={"csv_url": "x"},
    )
    ranked = rank(ctx, [other, credit])
    assert [c["id"] for c in ranked] == ["openml:31", "uci:999"]
    top = ranked[0]
    assert top["mapping"]["sex"]["values"] == {
        "male single": "male",
        "female div/dep/mar": "female",
    }
    assert top["mapping"]["age_band"]["transform"] == "bin"
    assert top["mapping"]["loan_amount"]["column"] == "credit_amount"
    assert top["mapping"]["loan_term_months"]["column"] == "duration"
    assert top["label"] == {"column": "class", "name": "repaid", "values": {"good": 1, "bad": 0}}
    assert "credit_history_months" in top["protected_missing"]
    assert set(top["breakdown"]) == {
        "schema",
        "scenario_fields",
        "protected",
        "label",
        "relevance",
        "task",
        "size",
        "licence",
        "recency",
    }
    # Coded values (no value map) count half.
    assert ranked[1]["mapping"]["sex"]["needs_value_map"] is True


# -- sources + search ------------------------------------------------------------------


def test_parse_arff_handles_quotes_and_missing():
    header, rows = parse_arff(ARFF, max_rows=10)
    assert header == [
        "personal_status",
        "age",
        "credit_amount",
        "duration",
        "applicant_name",
        "class",
    ]
    assert rows[1][0] == "female div/dep/mar"
    assert rows[3][2] == ""
    assert len(parse_arff(ARFF, max_rows=2)[1]) == 2


def test_search_end_to_end_with_mocked_catalogues(no_keys, tmp_path: Path):
    transport = _transport(_openml_payloads, _uci_payloads, _hf_payloads)
    with httpx.Client(transport=transport) as client:
        result = search_public_datasets(_ctx(), client=client)
    assert result["kind"] == ARTIFACT_KIND and result["status"] == "proposed"
    assert result["sources"]["openml"] == {"ok": True, "found": 1}
    assert result["sources"]["firecrawl"]["ok"] is False  # no key: skipped, said so
    ids = [c["id"] for c in result["candidates"]]
    assert ids[0] == "openml:31"
    assert "huggingface:someone/images" not in ids  # not tabular
    top = result["candidates"][0]
    assert top["licence"]["normalised"] == "CC-BY-4.0"  # UCI mirror on OpenML
    nc = next(c for c in result["candidates"] if c["source"] == "huggingface")
    assert "licence_non_commercial" in nc["flags"]
    assert result["recommendation"] == {
        "mode": "reference_sample",
        "candidate": "openml:31",
        "score": top["score"],
    }
    assert result["candidates_full"]["openml:31"]["download"]["arff_url"]
    md = to_markdown(result)
    assert "credit-g" in md and "Recommendation" in md
    assert not any("firecrawl" in c for c in transport.calls)


def test_firecrawl_hits_are_listed_without_schema(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def firecrawl(request: httpx.Request):
        if "firecrawl" in str(request.url):
            assert request.headers["Authorization"] == "Bearer fc-key"
            body = json.loads(request.content)
            assert "kaggle.com" in body["includeDomains"]
            return httpx.Response(
                200,
                json={
                    "data": {"web": [{"url": "https://www.kaggle.com/d/x", "title": "Credit X"}]}
                },
            )
        return None

    with httpx.Client(transport=_transport(firecrawl, _openml_payloads)) as client:
        result = search_public_datasets(
            _ctx(), client=client, firecrawl_key="fc-key", enabled=("firecrawl",)
        )
    web = result["candidates"][0]
    assert web["source"] == "firecrawl" and web["fetchable"] is False
    assert "schema_unknown" in web["flags"]
    assert result["recommendation"]["mode"] == "zero_shot"


def test_gemini_rerank_is_optional_and_mocked():
    ranked = [
        {
            "id": "a",
            "name": "A",
            "score": 0.7,
            "mapping": {},
            "gaps": [],
            "licence": {"normalised": "MIT"},
            "n_rows": 1,
            "description": "",
        },
        {
            "id": "b",
            "name": "B",
            "score": 0.6,
            "mapping": {},
            "gaps": [],
            "licence": {"normalised": "MIT"},
            "n_rows": 1,
            "description": "",
        },
    ]

    def gemini(request: httpx.Request):
        assert request.headers["x-goog-api-key"] == "g-key"
        text = json.dumps({"order": ["b", "a", "zzz"], "notes": {"b": "closer population"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    with httpx.Client(transport=_transport(gemini)) as client:
        assert rerank_with_gemini(_ctx(), ranked, client=client, api_key="")["used"] is False
        out = rerank_with_gemini(_ctx(), ranked, client=client, api_key="g-key")
    assert out["order"] == ["b", "a"]
    assert ranked[1]["llm_rank"] == 1 and ranked[1]["llm_note"] == "closer population"
    assert ranked[0]["score"] == 0.7  # the deterministic score is untouched


# -- fetch -----------------------------------------------------------------------------


def _result(no_keys_fixture=None):
    with httpx.Client(transport=_transport(_openml_payloads, _uci_payloads, _hf_payloads)) as c:
        return search_public_datasets(_ctx(), client=c, enabled=("openml", "huggingface"))


def test_pii_columns_are_found():
    header = ["applicant_name", "own_telephone", "email_addr", "age"]
    rows = [
        [f"Person {i}", "yes" if i % 2 else "none", f"p{i}@x.org", str(20 + i)] for i in range(20)
    ]
    dropped = {d["column"] for d in find_pii_columns(header, rows)}
    assert dropped == {"applicant_name", "email_addr"}


def test_fetch_stores_capped_rows_mapping_and_datasheet(no_keys, tmp_path: Path):
    result = _result()
    with httpx.Client(transport=_transport(_openml_payloads)) as client:
        out = fetch_from_result(
            result,
            "openml:31",
            store=LocalStore(tmp_path, "openml-31-credit-g"),
            approved_by="engineer:alice",
            client=client,
            max_rows=3,
        )
    folder = tmp_path / "datasets" / "public" / "openml-31-credit-g"
    assert sorted(p.name for p in folder.iterdir()) == [
        "data.csv",
        "datasheet.md",
        "mapping.yaml",
        "source.json",
    ]
    data = (folder / "data.csv").read_text(encoding="utf-8").splitlines()
    assert len(data) == 4 and "applicant_name" not in data[0]  # 3 rows, PII dropped
    assert out["dropped_columns"][0]["column"] == "applicant_name"
    mapping = yaml.safe_load((folder / "mapping.yaml").read_text(encoding="utf-8"))
    assert mapping["fields"]["sex"]["column"] == "personal_status"
    assert mapping["source"]["licence"] == "CC-BY-4.0"
    assert mapping["label"]["values"] == {"good": 1, "bad": 0}
    assert mapping["rows"] == 3 and mapping["sha256"] == out["sha256"]
    sheet = (folder / "datasheet.md").read_text(encoding="utf-8")
    assert "engineer:alice" in sheet and "Hofmann 1994" in sheet and "applicant_name" in sheet
    assert "Representation of `sex`" in sheet


def test_fetch_refuses_without_approval_or_with_nc_licence(no_keys, tmp_path: Path):
    result = _result()
    with pytest.raises(ValueError, match="approving human"):
        fetch_from_result(result, "openml:31", store=LocalStore(tmp_path, "x"), approved_by="")
    nc = next(c["id"] for c in result["candidates"] if c["source"] == "huggingface")
    with pytest.raises(ValueError, match="non-commercial"):
        fetch_from_result(result, nc, store=LocalStore(tmp_path, "y"), approved_by="bob")
    with pytest.raises(ValueError, match="not in the candidates"):
        fetch_from_result(result, "openml:1", store=LocalStore(tmp_path, "z"), approved_by="bob")


# -- tools over the backend's internal API ---------------------------------------------


def _backend(result: dict, status: str, puts: list):
    def handle(request: httpx.Request):
        url = str(request.url)
        if not url.startswith("http://backend.test/internal/"):
            return None
        assert request.headers["X-Internal-Secret"] == "s3cret"
        if request.method == "GET" and url.endswith("/internal/audits/A1"):
            artifact = {
                "id": "art1",
                "kind": ARTIFACT_KIND,
                "name": "credit-scorer",
                "version": 1,
                "status": status,
                "data": result,
            }
            approval = {"artifactId": "art1", "decision": "approved", "decidedBy": "client:alice"}
            return httpx.Response(
                200,
                json={
                    "audit": {"artifacts": [artifact], "approvals": [approval]},
                    "system": {"id": "SYS-002"},
                },
            )
        if request.method == "PUT":
            body = json.loads(request.content)
            puts.append((url.rsplit("/", 1)[-1], body["contentType"]))
            path = url.split("/datasets/public/")[1]
            return httpx.Response(
                200,
                json={"file": {"path": f"datasets/public/{path}", "version": 1}, "changed": True},
            )
        return None

    return handle


def test_run_fetch_needs_an_approved_artifact_and_writes_through_the_backend(no_keys):
    result = _result()
    puts: list = []
    for status, expect_error in (("proposed", True), ("approved", False)):
        transport = _transport(_backend(result, status, puts), _openml_payloads)
        api = InternalAPI("http://backend.test", "s3cret", httpx.Client(transport=transport))
        out = run_fetch("A1", "openml:31", api=api, client=httpx.Client(transport=transport))
        assert ("error" in out) is expect_error
    assert [p[0] for p in puts] == ["data.csv", "mapping.yaml", "datasheet.md", "source.json"]
    assert out["files"]["data.csv"]["path"] == "datasets/public/openml-31-credit-g/data.csv"


def test_tools_are_langchain_tools():
    tools = {t.name: t for t in build_public_dataset_tools()}
    assert set(tools) == {"search_public_datasets", "fetch_public_dataset"}
    assert "audit_id" in tools["fetch_public_dataset"].args
