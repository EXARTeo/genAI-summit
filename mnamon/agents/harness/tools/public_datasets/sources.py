"""Public dataset catalogues: search (metadata + schema) and row download.

All verified live on 2026-11-14 (keyless unless noted):

* **OpenML** REST (``/api/v1/json``): exact-name and tag listing, description
  (licence, citation, ARFF url, default target), features with types.
  Free-text search (``/es``) answers 403, so it is not used.
* **UCI ML Repository** (``/api/datasets/list?search=``, ``/api/dataset?id=``):
  search, variables with roles/types/demographics, CSV url. The API has no
  licence field; the repository licenses its datasets CC BY 4.0.
* **Hugging Face Hub** (``/api/datasets?search=&full=true``): card data
  (licence, features); ``datasets-server`` ``/info``, ``/splits``, ``/rows`` for
  schema and JSON rows (no parquet reader needed).
* **Firecrawl** ``/v2/search`` (``FIRECRAWL_API_KEY``, optional): Kaggle,
  data.europa.eu and other portals; web hits without a schema.

Pure Python + httpx; no pandas (the agents image has none). Every function
takes an ``httpx.Client`` so tests use ``httpx.MockTransport``.
"""

from __future__ import annotations

import csv
import io
import os
import re
from typing import Any

import httpx

from harness.tools.public_datasets.models import Candidate, Column

OPENML = "https://www.openml.org/api/v1/json"
UCI = "https://archive.ics.uci.edu/api"
HF = "https://huggingface.co/api"
HF_SERVER = "https://datasets-server.huggingface.co"
FIRECRAWL = "https://api.firecrawl.dev/v2"
UCI_LICENCE = "CC-BY-4.0"
HEADERS = {"User-Agent": "public-dataset-discovery/0.1", "Accept": "application/json"}
FIRECRAWL_DOMAINS = ["kaggle.com", "data.europa.eu", "zenodo.org", "data.gov"]


class SourceError(RuntimeError):
    """A catalogue answered with an error or an unreadable payload."""


def new_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)


def _get_json(client: httpx.Client, url: str, **params: Any) -> Any:
    response = client.get(url, params=params or None)
    if response.status_code >= 400:
        raise SourceError(f"GET {url} -> {response.status_code}")
    return response.json()


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# -- OpenML ------------------------------------------------------------------------

_OPENML_TYPES = {"numeric": "numeric", "nominal": "category", "string": "string", "date": "date"}


def _openml_list(client: httpx.Client, path: str) -> list[dict]:
    try:
        data = _get_json(client, f"{OPENML}/data/list/{path}")
    except SourceError:
        return []  # "No results" is a 412 on OpenML
    return list(((data or {}).get("data") or {}).get("dataset") or [])


def openml_candidate(client: httpx.Client, did: int, n_rows: int | None = None) -> Candidate:
    desc = _get_json(client, f"{OPENML}/data/{did}")["data_set_description"]
    feats = _get_json(client, f"{OPENML}/data/features/{did}")["data_features"]["feature"]
    target = desc.get("default_target_attribute") or None
    columns = [
        Column(
            name=f["name"],
            type=_OPENML_TYPES.get(f.get("data_type", ""), "unknown"),
            values=[str(v) for v in f.get("nominal_value") or []]
            if isinstance(f.get("nominal_value"), list)
            else ([str(f["nominal_value"])] if f.get("nominal_value") else []),
            is_target=f.get("is_target") == "true" or f["name"] == target,
        )
        for f in feats
        if f.get("is_ignore") != "true" and f.get("is_row_identifier") != "true"
    ]
    licence = str(desc.get("licence", ""))
    original = str(desc.get("original_data_url") or "")
    if licence.lower() in ("", "public") and "archive.ics.uci.edu" in original:
        licence = UCI_LICENCE  # a UCI dataset mirrored on OpenML keeps UCI's CC BY 4.0
    target_col = next((c for c in columns if c.is_target), None)
    task = "unknown"
    if target_col is not None:
        task = "classification" if target_col.type == "category" else "regression"
    return Candidate(
        source="openml",
        source_id=str(did),
        name=str(desc.get("name", did)),
        url=f"https://www.openml.org/d/{did}",
        description=str(desc.get("description", ""))[:2000],
        licence=licence,
        n_rows=n_rows,
        columns=columns,
        target=target,
        task=task,
        updated=str(desc.get("collection_date") or desc.get("upload_date") or ""),
        citation=str(desc.get("citation") or desc.get("original_data_url") or ""),
        download={"arff_url": desc.get("url"), "parquet_url": desc.get("parquet_url")},
    )


def search_openml(
    client: httpx.Client, names: list[str], tags: list[str], limit: int = 5
) -> list[Candidate]:
    found: dict[int, tuple[int | None, str]] = {}
    for name in names:
        for d in _openml_list(client, f"data_name/{name}/limit/3/status/active")[:1]:
            found.setdefault(int(d["did"]), (_openml_rows(d), f"openml name {name}"))
    for tag in tags:
        for d in _openml_list(client, f"tag/{tag}/limit/{limit}/status/active"):
            found.setdefault(int(d["did"]), (_openml_rows(d), f"openml tag {tag}"))
    out = []
    for did, (n_rows, query) in list(found.items())[: limit * 2]:
        try:
            cand = openml_candidate(client, did, n_rows)
        except (SourceError, KeyError, ValueError):
            continue
        cand.query = query
        out.append(cand)
    return out


def _openml_rows(entry: dict) -> int | None:
    for q in entry.get("quality") or []:
        if q.get("name") == "NumberOfInstances":
            return _int(q.get("value"))
    return None


def parse_arff(text: str, max_rows: int) -> tuple[list[str], list[list[str]]]:
    """Dense ARFF -> header + rows (strings; ``?`` -> empty)."""
    header: list[str] = []
    rows: list[list[str]] = []
    in_data = False
    attr = re.compile(r"^@attribute\s+('(?:[^']|\\')*'|\"[^\"]*\"|\S+)", re.IGNORECASE)
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("%"):
            continue
        if not in_data:
            m = attr.match(s)
            if m:
                header.append(m.group(1).strip("'\""))
            elif s.lower().startswith("@data"):
                in_data = True
            continue
        if s.startswith("{"):
            raise SourceError("sparse ARFF is not supported")
        row = next(csv.reader([s], quotechar="'", skipinitialspace=True))
        rows.append(["" if v == "?" else v for v in row])
        if len(rows) >= max_rows:
            break
    return header, rows


# -- UCI -----------------------------------------------------------------------------

_UCI_TYPES = {
    "Integer": "integer",
    "Continuous": "numeric",
    "Real": "numeric",
    "Categorical": "category",
    "Binary": "boolean",
    "Date": "date",
}


def uci_candidate(client: httpx.Client, uci_id: int) -> Candidate:
    data = _get_json(client, f"{UCI}/dataset", id=uci_id).get("data") or {}
    targets = list(data.get("target_col") or [])
    columns = [
        Column(
            name=v["name"],
            type=_UCI_TYPES.get(v.get("type") or "", "unknown"),
            description=str(v.get("description") or ""),
            demographic=str(v.get("demographic") or ""),
            is_target=v.get("role") == "Target" or v["name"] in targets,
        )
        for v in data.get("variables") or []
        if v.get("role") != "ID"
    ]
    tasks = [t.lower() for t in data.get("tasks") or []]
    info = data.get("additional_info") or {}
    return Candidate(
        source="uci",
        source_id=str(uci_id),
        name=str(data.get("name", uci_id)),
        url=str(data.get("repository_url") or f"https://archive.ics.uci.edu/dataset/{uci_id}"),
        description=str(data.get("abstract") or "") + "\n" + str(info.get("summary") or ""),
        licence=UCI_LICENCE,
        n_rows=_int(data.get("num_instances")),
        columns=columns,
        target=targets[0] if targets else None,
        task="classification" if "classification" in tasks else (tasks[0] if tasks else ""),
        updated=str(data.get("last_updated") or data.get("year_of_dataset_creation") or ""),
        citation=f"doi:{data['dataset_doi']}" if data.get("dataset_doi") else "",
        download={"csv_url": data.get("data_url")} if data.get("data_url") else {},
    )


def search_uci(client: httpx.Client, terms: list[str], limit: int = 5) -> list[Candidate]:
    ids: dict[int, str] = {}
    for term in terms:
        try:
            hits = _get_json(client, f"{UCI}/datasets/list", search=term).get("data") or []
        except SourceError:
            continue
        for h in hits[:limit]:
            ids.setdefault(int(h["id"]), term)
    out = []
    for uci_id, term in list(ids.items())[: limit * 2]:
        try:
            cand = uci_candidate(client, uci_id)
        except (SourceError, KeyError, ValueError):
            continue
        cand.query = f"uci {term}"
        out.append(cand)
    return out


# -- Hugging Face ----------------------------------------------------------------

_HF_NUMERIC = re.compile(r"^(u?int\d*|float\d*|double|decimal.*)$")


def _hf_type(dtype: str) -> str:
    if _HF_NUMERIC.match(dtype or ""):
        return "integer" if "int" in dtype else "numeric"
    if dtype == "bool":
        return "boolean"
    if dtype in ("string", "large_string"):
        return "string"
    return "unknown"


def _hf_columns(features: Any) -> list[Column]:
    cols: list[Column] = []
    if isinstance(features, list):
        for f in features:
            if isinstance(f, dict) and f.get("name"):
                if "class_label" in f:
                    names = (f["class_label"] or {}).get("names") or {}
                    values = list(names.values()) if isinstance(names, dict) else list(names)
                    cols.append(Column(f["name"], "category", values=[str(v) for v in values]))
                else:
                    cols.append(Column(f["name"], _hf_type(str(f.get("dtype", "")))))
    elif isinstance(features, dict):
        for name, f in features.items():
            f = f or {}
            if f.get("_type") == "ClassLabel":
                cols.append(Column(name, "category", values=[str(v) for v in f.get("names") or []]))
            else:
                cols.append(Column(name, _hf_type(str(f.get("dtype", "")))))
    return cols


def _hf_rows_from_tags(tags: list[str]) -> int | None:
    """Lower bound of ``size_categories:1K<n<10K`` (``n<1K`` -> None: unknown, small)."""
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for t in tags:
        m = re.match(r"size_categories:(\d+)([KMB]?)<n", t)
        if m:
            return int(m.group(1)) * scale[m.group(2)]
    return None


def hf_candidate(client: httpx.Client, entry: dict) -> Candidate:
    card = entry.get("cardData") or {}
    info = card.get("dataset_info") or {}
    if isinstance(info, list):
        info = info[0] if info else {}
    columns = _hf_columns(info.get("features"))
    config = info.get("config_name") or "default"
    if not columns:
        try:
            server = _get_json(client, f"{HF_SERVER}/info", dataset=entry["id"])
            first = next(iter((server.get("dataset_info") or {}).items()), (None, {}))
            config = first[0] or config
            columns = _hf_columns((first[1] or {}).get("features"))
        except SourceError:
            columns = []
    splits = info.get("splits") or []
    n_rows = sum(_int(s.get("num_examples")) or 0 for s in splits) or _hf_rows_from_tags(
        entry.get("tags") or []
    )
    licence = card.get("license") or next(
        (t.split(":", 1)[1] for t in entry.get("tags") or [] if t.startswith("license:")), ""
    )
    if isinstance(licence, list):
        licence = licence[0] if licence else ""
    return Candidate(
        source="huggingface",
        source_id=str(entry["id"]),
        name=str(entry["id"]).split("/")[-1],
        url=f"https://huggingface.co/datasets/{entry['id']}",
        description=str(entry.get("description") or "")[:2000],
        licence=str(licence),
        n_rows=n_rows,
        columns=columns,
        task="unknown",
        updated=str(entry.get("lastModified") or ""),
        citation=str(entry.get("citation") or ""),
        download={"dataset": entry["id"], "config": config},
    )


def search_huggingface(client: httpx.Client, queries: list[str], limit: int = 5) -> list[Candidate]:
    seen: dict[str, tuple[dict, str]] = {}
    for q in queries:
        try:
            hits = _get_json(client, f"{HF}/datasets", search=q, limit=limit, full="true")
        except SourceError:
            continue
        for h in hits or []:
            if h.get("gated") or h.get("private") or h.get("disabled"):
                continue
            tags = h.get("tags") or []
            if tags and not any(t in tags for t in ("modality:tabular", "format:csv")):
                continue
            seen.setdefault(h["id"], (h, q))
    out = []
    for entry, q in list(seen.values())[: limit * 2]:
        try:
            cand = hf_candidate(client, entry)
        except (SourceError, KeyError, ValueError):
            continue
        cand.query = f"hf {q}"
        out.append(cand)
    return out


# -- Firecrawl -------------------------------------------------------------------


def search_firecrawl(
    client: httpx.Client, queries: list[str], api_key: str | None = None, limit: int = 5
) -> list[Candidate]:
    """Web search over data portals; returns schema-less candidates (listed, not fetched)."""
    key = api_key if api_key is not None else os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        return []
    out: list[Candidate] = []
    for q in queries[:3]:
        body = {
            "query": f"{q} dataset csv",
            "limit": limit,
            "sources": ["web"],
            "includeDomains": FIRECRAWL_DOMAINS,
        }
        response = client.post(
            f"{FIRECRAWL}/search", json=body, headers={"Authorization": f"Bearer {key}"}
        )
        if response.status_code >= 400:
            continue
        data = response.json().get("data") or {}
        hits = data if isinstance(data, list) else data.get("web") or []
        for h in hits:
            url = str(h.get("url") or "")
            if not url:
                continue
            out.append(
                Candidate(
                    source="firecrawl",
                    source_id=re.sub(r"^https?://", "", url).rstrip("/")[:120],
                    name=str(h.get("title") or url)[:120],
                    url=url,
                    description=str(h.get("description") or ""),
                    query=f"web {q}",
                )
            )
    return out


# -- rows --------------------------------------------------------------------------


def _download_text(client: httpx.Client, url: str, max_bytes: int) -> str:
    """GET up to ``max_bytes``; a longer file is cut at the last full line (a row cap)."""
    chunks: list[bytes] = []
    size = 0
    truncated = False
    with client.stream("GET", url) as response:
        if response.status_code >= 400:
            raise SourceError(f"GET {url} -> {response.status_code}")
        for chunk in response.iter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                truncated = True
                break
    data = b"".join(chunks)[:max_bytes]
    if truncated and b"\n" in data:
        data = data[: data.rindex(b"\n") + 1]
    return data.decode("utf-8", errors="replace")


def load_rows(
    client: httpx.Client, cand: dict[str, Any], max_rows: int, max_bytes: int = 20_000_000
) -> tuple[list[str], list[list[str]]]:
    """Header + up to ``max_rows`` rows of a candidate (``Candidate.to_dict()`` shape)."""
    source = cand["source"]
    download = cand.get("download") or {}
    if source == "openml" and download.get("arff_url"):
        return parse_arff(_download_text(client, download["arff_url"], max_bytes), max_rows)
    if source == "uci" and download.get("csv_url"):
        reader = csv.reader(io.StringIO(_download_text(client, download["csv_url"], max_bytes)))
        header = next(reader)
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) >= max_rows:
                break
        return header, rows
    if source == "huggingface" and download.get("dataset"):
        return _hf_rows(client, download["dataset"], download.get("config"), max_rows)
    raise SourceError(f"{cand.get('id')}: not downloadable (no schema or file url)")


def _hf_rows(
    client: httpx.Client, dataset: str, config: str | None, max_rows: int
) -> tuple[list[str], list[list[str]]]:
    splits = _get_json(client, f"{HF_SERVER}/splits", dataset=dataset).get("splits") or []
    pick = next((s for s in splits if s.get("config") == config), splits[0] if splits else None)
    if pick is None:
        raise SourceError(f"{dataset}: no splits")
    header: list[str] = []
    rows: list[list[str]] = []
    offset = 0
    while len(rows) < max_rows:
        page = _get_json(
            client,
            f"{HF_SERVER}/rows",
            dataset=dataset,
            config=pick["config"],
            split=pick["split"],
            offset=offset,
            length=min(100, max_rows - len(rows)),
        )
        if not header:
            header = [f["name"] for f in page.get("features") or []]
        batch = page.get("rows") or []
        if not batch:
            break
        for r in batch:
            row = r.get("row") or {}
            rows.append(["" if row.get(h) is None else str(row.get(h)) for h in header])
        offset += len(batch)
        if len(batch) < 100:
            break
    return header, rows
