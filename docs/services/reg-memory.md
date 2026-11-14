# reg-memory: the regulation store

`product/reg-memory/` is the Regulatory Knowledge Service of the AI Act Governance Copilot
([agent context §1](../architecture/agent-context.md#1-reg-memory-all-the-regulation-in-one-place)).
This first version **downloads** the EU AI Act and its supporting documents, keeps **every version** on
disk with its **extracted text** and **diffs**, and serves them over a small internal API.
Parsing into provisions, search and the database tables (backend Alembic migrations) come later.

## Layout

```text
product/reg-memory/
├── main.py                 FastAPI app + lifespan (optional bootstrap ingest when the store is empty)
├── Dockerfile, requirements.txt, .dockerignore
├── core/                   same layout and behaviour as product/backend/core/
│   ├── settings.py         grouped pydantic-settings (settings.app / store / fetch / security / rate_limit / logging)
│   ├── error_handling.py   ServiceExceptionHandler (safe JSON errors, logged once)
│   ├── logging/            backend's structured logging: request-id middleware, EventLogger, redaction, JSON/console
│   └── security/           client.py: X-Internal-Secret gate; rate_limit.py: per-IP budget + per-route limits (in memory)
├── schema/                 API models (sources.py, documents.py, ingest.py); __init__ stays empty
├── router/                 health, sources, ingest, documents (thin)
├── utils/                  glue between routers and the engine (background runs, store reads)
└── engine/
    ├── catalog/            sources.yaml + loader.py (validated with pydantic)
    ├── fetch/              cellar.py (EU law by CELEX), http.py (retries, throttle, follow_links), firecrawl.py
    ├── extract/            html.py (XHTML/HTML -> markdown), pdf.py (pypdf), docx.py (zip + XML), stage.py
    ├── store.py            the versioned file store
    ├── diff.py             diff stage (CLI)
    └── ingest.py           orchestrator (CLI)
```

## Fetching

- **EU law comes from the Cellar API**, never from eur-lex.europa.eu (it answers bots with an HTTP 202
  challenge): `GET https://publications.europa.eu/resource/celex/<CELEX>` with `Accept: application/xhtml+xml`
  (or a PDF type) and `Accept-Language: eng`. Recent OJ acts only have a PDF/A-2a manifestation, so `pdf`
  tries `application/pdf`, then `application/pdf;type=pdfa2a`, then `pdfa1a`.
- **Web pages** use plain HTTP with a generic User-Agent (`reg-memory/0.1`), timeouts, 3 retries with
  exponential backoff on 429/5xx/transport errors (a 429's `Retry-After` is respected), a size cap and
  **one request per 3 s per host** (`digital-strategy` and the AI Act Service Desk answer 429 otherwise).
- **Conditional requests:** the stored `ETag` / `Last-Modified` are sent; a 304 is recorded as `same`
  without downloading. `--force` / `force: true` skips them (unchanged bytes are still `same`).
- **Type detection by magic bytes** (`%PDF` → pdf, `PK` + `word/document.xml` → docx), then
  `Content-Type`, then the `Content-Disposition` file name: the Commission's newsroom downloads send
  `Content-Type: /`. A source (or `follow_links` child) that expects pdf/docx but gets HTML (a wrong
  newsroom id returns an HTML error page with HTTP 200) is recorded as **failed**, not as a new version.
- **Challenges** (HTTP 202 or an empty body) fall back to Firecrawl when `FIRECRAWL_API_KEY` is set;
  otherwise the fetch is recorded as failed and the run goes on.
- **`follow_links`** downloads the documents a landing page links to (as child documents of the page):
  a URL regex, a max count, a host allowlist, and label filters. The default `exclude_label` drops the
  Commission's per-language copies (`... (Greek)`, `... (French)`), keeping English.

## Catalog: `engine/catalog/sources.yaml`

One entry per source; append to add one (block or flow style).

| Field | Meaning |
| --- | --- |
| `id` | Unique, `[a-z0-9_-]`; also the main document's id |
| `title` | Human title |
| `kind` | `regulation`, `amendment`, `consolidated`, `guideline`, `faq`, `code_of_practice`, `standard`, `national_law`, `internal_policy`, `other` |
| `binding` | `true`, `false` or `internal` |
| `status` | `final` or `draft` |
| `publisher` | Free text |
| `fetcher` | `cellar` (needs `celex`), `http` or `firecrawl` (need `url`) |
| `celex` / `url` | Where it comes from |
| `formats` | Cellar: one document per format (`xhtml`, `html`, `pdf`); the first is the main one, others are `<id>.<fmt>`. HTTP: the expected type (`[pdf]`/`[docx]` → an HTML answer is a failure) |
| `follow_links` | `{pattern, max, hosts, include_label?, exclude_label?, binary?}` (`binary: true` = children must be pdf/docx) |
| `tags`, `notes` | Free text |
| `enabled` | `false` = skipped by full runs (still fetchable by id) |

```yaml
  - id: guidelines-prohibited-practices
    title: Commission Guidelines on prohibited AI practices
    kind: guideline
    binding: false
    status: final
    publisher: European Commission
    fetcher: http
    url: https://digital-strategy.ec.europa.eu/en/library/commission-publishes-guidelines-prohibited-artificial-intelligence-ai-practices-defined-ai-act
    follow_links:
      pattern: ^https://ec\.europa\.eu/newsroom/dae/redirection/document/\d+$
      max: 5
      hosts: [ec.europa.eu]
    tags: [ai-act, art-5]
```

## Store: one data volume

Everything lives under one directory: `./data` locally (git-ignored), `/data` in Docker (named volume
`reg-memory-data`). A **document** is one fetched artifact: a source's main text (`doc_id` = source id),
another format of it (`<source_id>.pdf`) or a linked child (`<source_id>.<slug>`, with `parent_id`).

```text
data/
├── catalog/<run_id>.yaml                      snapshot of sources.yaml used by that run
├── raw/<doc_id>/v0001__<sha256-12>.<ext>      original bytes, never overwritten
├── text/<doc_id>/v0001__<sha256-12>.md        extracted text, one per raw version
├── diffs/<doc_id>/v0001__v0002.diff           unified diff of the texts of consecutive versions
├── diffs/<doc_id>/v0001__v0002.json           summary: lines_added, lines_removed, changed_sections
├── manifests/<doc_id>.json                    append-only fetch log + per-stage flags
└── runs/<run_id>.json                         one ingest run: per-source results, stage counts
```

`manifests/<doc_id>.json` holds `doc_id, source_id, parent_id, url, label, etag, last_modified` and
`versions`: one entry **per fetch**, appended, never rewritten:

```json
{"version": 2, "fetched_at": "2026-11-14T16:00:00+00:00", "url": "...", "final_url": "...",
 "sha256": "...", "content_type": "application/xhtml+xml", "bytes": 851234, "status": "changed",
 "raw_path": "raw/ai-act/v0002__1a2b3c4d5e6f.xhtml", "ext": "xhtml", "filename": null,
 "text_path": "text/ai-act/v0002__1a2b3c4d5e6f.md", "diff_path": "diffs/ai-act/v0001__v0002.diff",
 "processed": {"extracted": true, "diffed": true}}
```

`status` is `new` (first content), `changed` (new bytes → new version + files), `same` (same hash or
HTTP 304: no new file, `version` = the current one) or `failed` (`error` set). This is the base for
later provision diffs and `kb_version`.

### Stages (each incremental, each runnable alone)

| Stage | Command | Skips when |
| --- | --- | --- |
| Download | `python -m engine.ingest [--source ID ...] [--force] [--no-extract] [--no-diff]` | Same sha256 (or 304) → `same`, nothing written |
| Extract | `python -m engine.extract.stage [--source ID ...] [--force]` | `processed.extracted` and the text file exists |
| Diff | `python -m engine.diff [--source ID ...] [--force]` | The `.diff` file for that version pair exists |

`engine.ingest` runs extract and diff after the download. Run the CLIs from `product/reg-memory/`
(`.venv\Scripts\python -m engine.ingest`) or inside the container
(`./scripts/stack.sh exec reg-memory python -m engine.ingest`).

## API

Port 8010, internal only (not published). Every `/v1` route needs `X-Internal-Secret`; every route is
rate-limited (global per-IP budget + per-route limits) and logged with a request id.

| Method | Path | What |
| --- | --- | --- |
| GET | `/health` | Liveness (no auth, not logged) |
| GET | `/v1/sources` | Catalog + the main document's latest fetch + number of documents |
| POST | `/v1/ingest` | `{source_ids?, force?}` → `202 {run_id}`; runs in the background, one at a time |
| GET | `/v1/ingest/{run_id}` | The run record (`queued`, `running`, `done`, `failed`) |
| GET | `/v1/documents` | Every document (optional `?source_id=`), latest version and text flag |
| GET | `/v1/documents/{doc_id}` | The full versions log |
| GET | `/v1/documents/{doc_id}/text?version=` | Extracted text (latest if no version) |

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_ENV` | `development` | Outside `development`/`test` an unset secret refuses every `/v1` call (503) |
| `REG_MEMORY_INTERNAL_SECRET` | empty (compose: dev value) | Expected `X-Internal-Secret` |
| `REG_MEMORY_DATA_DIR` | `./data` (image: `/data`) | The store |
| `REG_MEMORY_CATALOG` | `engine/catalog/sources.yaml` | Catalog path |
| `REG_MEMORY_BOOTSTRAP_ON_START` | `false` (compose: `true`) | Full ingest at start when the store is empty |
| `FIRECRAWL_API_KEY` | empty | Optional challenge fallback |
| `REG_MEMORY_HOST_INTERVAL_SECONDS` | `3` | Minimum gap between requests to one host |
| `REG_MEMORY_HTTP_RETRIES` / `REG_MEMORY_HTTP_TIMEOUT_SECONDS` | `3` / `60` | Retries and timeout |
| `REG_MEMORY_MAX_BYTES` | 50 MB | Size cap per download |
| `REG_MEMORY_CONCURRENCY` | `8` | Parallel downloads |
| `IP_RATE_LIMIT_MAX_CALLS`, `INGEST_RATE_LIMIT_MAX_ATTEMPTS`, `READ_RATE_LIMIT_MAX_ATTEMPTS` | 600 / 10 / 240 per minute | Rate limits |
| `LOG_FORMAT`, `LOG_LEVEL`, `LOG_REDACTION_SECRET` | `console`, `INFO`, random | Logging (as in the backend) |

## Add a source

1. Append an entry to `engine/catalog/sources.yaml` (check the URL with `curl -sIL` first; prefer Cellar
   for EU law, a direct document URL or a landing page + `follow_links` for the rest).
2. `python -m engine.ingest --source <id>` and check `data/manifests/<id>.json` and the text.
3. Tests: `product\reg-memory\.venv\Scripts\python -m pytest tests/reg_memory` (no network:
   `httpx.MockTransport`).
