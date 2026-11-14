# reg-memory: the regulation store

`product/reg-memory/` is the Regulatory Knowledge Service of the AI Act Governance Copilot
([agent context §1](../architecture/agent-context.md#1-reg-memory-all-the-regulation-in-one-place)).
It **downloads** the EU AI Act and its supporting documents, keeps **every version** on disk with its
**extracted text** and **diffs**, **parses** the acts into stable provision nodes (`AIA.10.2.f`) and the
guidelines/FAQs into interpretations, snapshots them with the **requirements + test-template corpus**
into immutable **kb releases** (`kb_version` = `YYYY.MM.DD-N`), **watches** the sources (scheduler,
`check-now`, Firecrawl webhook) and turns every provision-level change into a **RegChange** with a
change type per provision (Gemini, or a deterministic heuristic without a key), a candidate release
that a human activates, and optional notifications (backend, Telegram). **Everything works without
any API key** (`GET /v1/integrations` shows what is active).

## Layout

```text
product/reg-memory/
├── main.py                 FastAPI app + lifespan (bootstrap: first download + baseline release; scheduler)
├── corpus/                 requirements.yaml + test_templates.yaml (in git, loaded into every release)
├── Dockerfile, requirements.txt, .dockerignore
├── core/                   same layout and behaviour as product/backend/core/
│   ├── settings.py         grouped pydantic-settings (settings.app / store / fetch / security / rate_limit / logging)
│   ├── error_handling.py   ServiceExceptionHandler (safe JSON errors, logged once)
│   ├── logging/            backend's structured logging: request-id middleware, EventLogger, redaction, JSON/console
│   └── security/           client.py: X-Internal-Secret gate; rate_limit.py: per-IP budget + per-route limits (in memory)
├── schema/                 API models (sources.py, documents.py, ingest.py); __init__ stays empty
├── router/                 health, sources (+ proposed), ingest, documents, provisions, releases, changes,
│                           requirements, integrations, watch, webhooks, demo (thin)
├── utils/                  glue between routers and the engine (background runs/checks, scheduler, reads)
└── engine/
    ├── catalog/            sources.yaml + loader.py (validated; + data overlay of accepted proposals)
    ├── fetch/              cellar.py (EU law by CELEX), http.py (retries, throttle, follow_links)
    ├── extract/            html.py (XHTML/HTML -> markdown), pdf.py (pypdf), docx.py (zip + XML), stage.py
    ├── kb/                 parser.py (provisions), interpretations.py, corpus.py, releases.py,
    │                       changes.py (diff + change types + impact), applicability.py
    ├── firecrawl/          client.py (REST v2: scrape + changeTracking, search, map), webhook.py (signature)
    ├── llm/gemini.py       google-genai wrapper: structured JSON or None (= use the fallback)
    ├── watch/              check.py (one check), discovery.py (links, Cellar SPARQL, search), proposals.py
    ├── notify.py           backend POST + Telegram message on a new RegChange
    ├── demo.py             the editable demo mirror page
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
- **Challenges** (HTTP 202 or an empty body) fall back to Firecrawl (`/v2/scrape`, markdown) when
  `FIRECRAWL_API_KEY` is set; otherwise the fetch is recorded as failed and the run goes on. A source
  with `fetcher: firecrawl` uses plain HTTP when there is no key.
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
| `monitor` | `true` = Firecrawl change tracking on every scheduled check (when keyed) |
| `discover` | `{pattern, hosts?, max?}`: an index page; new matching links become proposed sources |

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
├── runs/<run_id>.json                         one ingest run: per-source results, stage counts
├── kb/releases/<kb_version>/                  one immutable release (below)
├── kb/active.json                             the active kb_version (+ who activated it, previous)
├── kb/changes/RC-<kb_version>.json            one RegChange per candidate release that differs
├── watch/checks/<check_id>.json               one watch check (steps, release, change, notifications)
├── discovery/proposed.json                    proposed sources + triage + decisions
├── discovery/accepted_sources.yaml            catalog overlay (accepted proposals)
├── discovery/links/<source_id>.json           last seen links of each `discover` index page
├── discovery/state.json                       Cellar SPARQL `sparql_since`, last run
└── demo/art6-guidelines.html                  the editable demo mirror
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

## Knowledge base (PDF §12.3)

### Provisions: `engine/kb/parser.py` (deterministic, no LLM)

The extracted markdown of a Cellar act is regular enough to parse line by line: `### Article N` + title,
`1.` paragraphs, `(a)` points, `(i)` sub-points (`(i)` right after `(h)` is a letter), `(1)` numbered
points, `## ANNEX X` with `Section A` blocks, `| (n) | text |` rows (recitals, amending points) and the
consolidated text's `▼B` / `▼M1` markers. Ids are stable and readable:

| Id | What |
| --- | --- |
| `AIA.10` | Article 10: title + unnumbered intro text |
| `AIA.10.2.f` | Art. 10(2), point (f) |
| `AIA.113.c.i` | Art. 113, point (c)(i) |
| `AIA.3.1` | Art. 3, definition (1) |
| `AIA.ANNEX_III.4.a` | Annex III, point 4(a); `AIA.ANNEX_VIII.A.1` = Annex VIII, Section A, point 1 |
| `AIA.REC.27` | Recital 27 (from the OJ text `ai-act`; the consolidated text has none) |
| `OMNIBUS.1.12` | Reg. (EU) 2026/1744, Article 1, amending point (12) (+ `OMNIBUS.REC.n`) |

Each node: `id, instrument, kind, path ([Art 10, para 2, pt f]), parent, title, text` (its **own**
verbatim text; children are separate nodes), `content_hash` (`sha256:` of that text), `valid_from`
(Art. 113 as amended: Chapters I-II 2025-02-02; Ch. III Sec. 4, V, VII, XII, Art. 78 2025-08-02;
Art. 102-110 2026-07-27; Ch. III Sec. 1-3 2027-12-02 with `valid_from_by_basis`
`{annex_iii: 2027-12-02, annex_i: 2028-08-02}`; Art. 5(1)(ba)/(bb), 5(1a)/(1b) 2026-12-02; Annex III
2027-12-02; otherwise 2026-08-02), `amended_by` (a `▼M1` node lists the Omnibus points that target it,
e.g. `[OMNIBUS.1.9]`, or `Regulation (EU) 2026/1744`), `chapter`, `section`, `source_doc`, `kb_version`.
The real consolidated text gives ~1,400 AI Act nodes (+180 recitals, ~120 Omnibus nodes).

### Interpretations: `engine/kb/interpretations.py`

Catalog sources of kind `guideline`, `faq`, `code_of_practice`, `internal_policy` (not `binding: true`)
become interpretation nodes: one per markdown section (`#`-`###` heading) or one per document (most
PDFs). `id = INT.<doc_id>[.<heading-slug>]`, `binding: false` (or `internal`), `status` draft/final
from the catalog, `relates_to` = the AI Act provisions the text mentions ("Article 6(3)", "Art. 10(2),
point (f)", "point 4(a) of Annex III") kept only when the id exists, `summary`, `text`, `content_hash`.

### Corpus: `corpus/requirements.yaml`, `corpus/test_templates.yaml` (in git)

Requirements `REQ.AIA.<art>.<para>.<point>.<slug>` with `source` (provision id), `related`, `actor`,
`applies_if` (`risk_class`, `basis` families `annex_iii`/`annex_i`, `features_any`), `modality`,
`obligation`, `testability` (`model_and_data_test | documentation | process`), `test_templates`,
`provenance: drafted_by_agent`, `review: pending`. MVP scope, drafted from the downloaded consolidated
text: provider obligations for high-risk systems Art. 6(2)/(4), 9, 10 (+ Art. 4a special-category
data), 11, 12, 13, 14, 15, 17 and Art. 50 (SYS-004), 32 requirements. Eight test templates
(`TT.fairness.group_metrics`, `TT.fairness.counterfactual`, `TT.data.representation`,
`TT.robustness.perturbation`, `TT.robustness.edge_cases`, `TT.accuracy.subgroup`,
`TT.transparency.ai_disclosure`, `TT.security.prompt_injection`) with `supports`, `needs`,
`data_strategy`, `metric`, `pass_criterion` (from the system card: the Act sets no numbers) and
`limitations`. Both are validated (pydantic) and cross-checked on every release (`warnings` in the
manifest). In a release each requirement also carries `valid_from` (+ `valid_from_by_basis`) and
`source_hash` from its source provision.

### Releases (`kb_version`)

```text
kb/releases/<kb_version>/
  manifest.json                       status, created_at, trigger, parent, content_hash, hashes, inputs
                                      (doc id -> version + sha256), counts, warnings, activated_*
  index.json                          id -> {file, content_hash} for provisions and interpretations
  provisions/AIA/art_10.yaml          one YAML per article / annex (+ recitals.yaml), OMNIBUS/ too
  interpretations/<source_id>.yaml
  requirements.yaml, test_templates.yaml
```

A build snapshots the latest texts; if its content hash equals the latest release, nothing is
written. A new release is a **candidate**; it becomes **active** only through
`POST /v1/releases/{v}/activate` (the HITL accept, G6). The very first release is activated
automatically as the baseline (`REG_MEMORY_AUTO_ACTIVATE_FIRST`). Old releases are kept
(`superseded`); every read can pin `?kb_version=`.

### RegChange (PDF §12.6)

When a candidate differs from the active release, provisions and interpretations are compared by
`content_hash`: each changed / added / removed node gets `old_text`, `new_text` (clipped at 6,000
chars), a unified `diff`, a `change_type` (`editorial | substantive | date | scope |
new_interpretation`) and a one-line `rationale`, `classified_by` = `gemini:<model>` (one batched call
with a JSON schema) or `heuristic` (no key, an error, or beyond `GEMINI_MAX_ITEMS` nodes):
whitespace/punctuation only → editorial; dates/numbers changed with the wording otherwise ≥90 % equal →
date; interpretation changes → new_interpretation; otherwise substantive. The impact index (no LLM)
lists `impacted_requirements` whose source/related provision changed or is cited by a changed
interpretation. Saved as `kb/changes/RC-<to_kb_version>.json`, then notified.

## Watcher, discovery, notifications

### Checks

A check (`engine/watch/check.py`) = ingest (our fetch + sha256 diff: the change signal that works with
no key) → Firecrawl change tracking (keyed: `formats: [markdown, {type: changeTracking, modes:
[git-diff], tag: <source id>}]` for the checked sources, or the `monitor: true` ones on full checks) →
discovery (full checks) → if a document is new/changed: candidate release + RegChange + notify. It runs
under the same lock as ingests and is recorded in `watch/checks/<id>.json`.

- **Scheduler**: every `REG_MEMORY_WATCH_INTERVAL_MINUTES` (default 60, `0` = off), a full check.
- **`POST /v1/watch/check-now`** `{source_ids?, wait?, discovery?}`: all sources or a few; `wait: true`
  returns the finished record (demo), otherwise `202 {check_id}` and `GET /v1/watch/checks/{id}`.
- **Firecrawl monitor webhook** `POST /v1/webhooks/firecrawl`: verified with `X-Firecrawl-Signature:
  sha256=HMAC-SHA256(FIRECRAWL_WEBHOOK_SECRET, raw body)` **or** a valid `X-Internal-Secret` (add it to
  the monitor's `webhook.headers`). `monitor.page` items with status new/changed/removed are mapped to
  catalog sources by URL and a check of those sources starts. reg-memory is not published: a real
  Firecrawl monitor needs a tunnel or a proxy route to it.

### Discovery → proposed sources

1. **Index-page link diff** for sources with `discover` (`ai-regulatory-framework`,
   `service-desk-resources`): links (Firecrawl `map` when keyed, else the page we fetched) that were
   not there at the previous check; the first look is a baseline.
2. **Cellar SPARQL** (`https://publications.europa.eu/webapi/rdf/sparql`): acts that
   `resource_legal_amends_resource_legal`, `resource_legal_based_on_resource_legal` or `work_cites_work`
   32024R1689 with `work_date_document` since the last check (first run: 30 days back), English titles.
3. **Firecrawl search** (keyed only, otherwise reported as disabled): `categories: [gov, pdf]`,
   `includeDomains: [europa.eu]`, `tbs: qdr:m`.

New hits (not in the catalog or earlier proposals) are triaged (relevance 0-1, kind, binding, tags) by
Gemini or a keyword heuristic (AI Act terms, CELEX sector/type: staff working documents score low);
below 0.35 they are stored as `ignored`. `GET /v1/sources/proposed[?status=]`,
`POST /v1/sources/proposed/{id}/accept|reject`. Accepting appends a catalog entry (`disc-<slug>`,
Cellar for a CELEX, HTTP otherwise) to `discovery/accepted_sources.yaml`, merged into the catalog at
runtime (the git `sources.yaml` is never edited); the next check downloads it.

### Notifications (both optional, best effort)

On a new RegChange: `POST {BACKEND_INTERNAL_URL}/internal/regulation/changes` (summary, change types,
items with diffs, impacted requirements; `X-Internal-Secret` = `BACKEND_INTERNAL_SECRET`) and a
Telegram `sendMessage` to `TELEGRAM_CHAT_ID` (summary + affected provisions + requirements; inline
buttons come later). The result (`sent`, `skipped`, `failed`, `http_<code>`) is stored in the change
and the check. In compose `BACKEND_INTERNAL_URL` is `http://backend:8000` and reg-memory's own Telegram is off:
the backend stores the change and sends it to Telegram with Accept / Reject / Open buttons
([backend § Telegram approvals](backend-systems.md#telegram-approvals)); the UI reads it through `/v1/regulation`.

## Demo: live regulation change in seconds

The EU will not change the law during the demo, so the catalog has `demo-art6-guideline-mirror`, an
Art. 6 guideline page **served by reg-memory itself** at `GET /demo/mirror/art6-guidelines.html`
(public, no secret; the file lives in the data volume). Inside the stack:

```bash
./scripts/stack.sh exec -T reg-memory python - <<'PY'
import json, os, urllib.request as u
H = {"X-Internal-Secret": os.environ["REG_MEMORY_INTERNAL_SECRET"], "Content-Type": "application/json"}
def call(m, p, body=None):
    data = json.dumps(body).encode() if body is not None else None
    return json.load(u.urlopen(u.Request("http://localhost:8010" + p, data, H, method=m), timeout=300))
# 0) the mirror is in the baseline after the first full check; this makes sure
call("POST", "/v1/watch/check-now", {"source_ids": ["demo-art6-guideline-mirror"], "wait": True})
# 1) edit the guideline live
call("PUT", "/v1/demo/mirror", {"find": "high-risk under Article 6(2).",
     "replace": "high-risk under Article 6(2), even when a human reviews the shortlist."})
# 2) check now -> candidate release + RegChange (+ Telegram if configured)
chk = call("POST", "/v1/watch/check-now", {"source_ids": ["demo-art6-guideline-mirror"], "wait": True})
print(chk["release"])
print(call("GET", "/v1/changes/" + chk["release"]["change_id"])["interpretations"][0]["diff"])
# 3) the human accepts the new kb_version
print(call("POST", "/v1/releases/" + chk["release"]["kb_version"] + "/activate", {"by": "engineer"})["status"])
PY
```

`PUT /v1/demo/mirror` takes `{html}` (replace all), `{find, replace}`, `{append_html}` or `{reset: true}`.

**With Firecrawl monitoring**: publish the same HTML where Firecrawl can reach it, e.g. GitHub Pages
(a repo whose `index.html` is the `html` of `GET /v1/demo/mirror`; Settings → Pages → deploy from a
branch), set `REG_MEMORY_DEMO_MIRROR_URL=https://<user>.github.io/<repo>/` so the demo source fetches
it, create a Firecrawl monitor on that URL with a webhook to `/v1/webhooks/firecrawl`, and in the demo
commit an edit and press "check now" (the monitor's own schedule is slow; `check-now` scrapes with
change tracking on demand).

## API

Port 8010, internal only (not published). Every `/v1` route needs `X-Internal-Secret` (the webhook:
its signature or the secret); every route is rate-limited (global per-IP budget + per-route read /
ingest / write limits) and logged with a request id.

| Method | Path | What |
| --- | --- | --- |
| GET | `/health` | Liveness (no auth, not logged) |
| GET | `/v1/sources` | Catalog + the main document's latest fetch + number of documents |
| POST | `/v1/ingest` | `{source_ids?, force?}` → `202 {run_id}`; runs in the background, one at a time |
| GET | `/v1/ingest/{run_id}` | The run record (`queued`, `running`, `done`, `failed`) |
| GET | `/v1/documents` | Every document (optional `?source_id=`), latest version and text flag |
| GET | `/v1/documents/{doc_id}` | The full versions log |
| GET | `/v1/documents/{doc_id}/text?version=` | Extracted text (latest if no version) |
| GET | `/v1/provisions?kb_version=&prefix=&q=&instrument=&limit=&offset=&with_text=` | Provisions by id prefix (`AIA.10`) or text |
| GET | `/v1/provisions/{id}?kb_version=` | One provision + its children + interpretations relating to it |
| GET | `/v1/interpretations?relates_to=&source_id=` / `/v1/interpretations/{id}` | Guidance nodes (without / with text) |
| GET | `/v1/releases` / `/v1/releases/{kb_version}` | Releases (newest first, `active`) / one manifest |
| POST | `/v1/releases` `{force?}` | Build a candidate now (+ RegChange if it differs) |
| POST | `/v1/releases/{kb_version}/activate` `{by}` | The HITL accept: make it the active kb_version |
| GET | `/v1/changes` / `/v1/changes/{id}` | RegChanges (summaries) / one with old/new text, diff, types, impact |
| GET | `/v1/requirements?role=&risk_class=&basis=&date=&feature=&testability=&kb_version=` | Applicable requirements, each with `effective_valid_from` and `in_force` on `date` (default today) |
| GET | `/v1/test-templates` | Test templates of a release |
| GET | `/v1/integrations` | Which integrations are active and what falls back |
| GET | `/v1/watch` | Scheduler, discovery state, recent checks |
| POST | `/v1/watch/check-now` `{source_ids?, wait?, discovery?}` | Run a check (202 + id, or the record with `wait`) |
| GET | `/v1/watch/checks/{check_id}` | One check record |
| GET | `/v1/sources/proposed?status=` | Proposed sources (`proposed`, `accepted`, `rejected`, `ignored`, `all`) |
| POST | `/v1/sources/proposed/{id}/accept` / `reject` | Decide a proposal (accept → catalog overlay) |
| GET / PUT | `/v1/demo/mirror` | Read / edit the demo mirror |
| POST | `/v1/webhooks/firecrawl` | Firecrawl webhook (signature or `X-Internal-Secret`) |
| GET | `/demo/mirror/art6-guidelines.html` | The public demo page (no secret) |

Example for an Annex III 4(a) provider (the agents' `load_context`):
`GET /v1/requirements?role=provider&risk_class=high&basis=AIA.ANNEX_III.4.a&date=2026-11-14`; a chatbot:
`?role=provider&risk_class=limited&feature=interacts_with_persons`.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_ENV` | `development` | Outside `development`/`test` an unset secret refuses every `/v1` call (503) |
| `REG_MEMORY_INTERNAL_SECRET` | empty (compose: dev value) | Expected `X-Internal-Secret` |
| `REG_MEMORY_DATA_DIR` | `./data` (image: `/data`) | The store |
| `REG_MEMORY_CATALOG` | `engine/catalog/sources.yaml` | Catalog path |
| `REG_MEMORY_BOOTSTRAP_ON_START` | `false` (compose: `true`) | No release and no AI Act text yet: a first full check at start (download, extract, baseline release, discovery baseline). With the text on disk the baseline release is always built |
| `REG_MEMORY_WATCH_INTERVAL_MINUTES` | `60` | Scheduled full check; `0` = off |
| `REG_MEMORY_DISCOVERY_ENABLED` | `true` | Discovery on full checks (index links, Cellar SPARQL, Firecrawl search) |
| `REG_MEMORY_SPARQL_URL` | `https://publications.europa.eu/webapi/rdf/sparql` | Cellar SPARQL endpoint |
| `REG_MEMORY_AUTO_ACTIVATE_FIRST` | `true` | The first release becomes active without the HITL call |
| `REG_MEMORY_DEMO_MIRROR_URL` | `http://localhost:8010/demo/mirror/art6-guidelines.html` | Where `demo-art6-guideline-mirror` is fetched |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | empty / `gemini-3.5-flash-lite` | Gemini (`google-genai`) for change types and triage; empty = heuristics. `gemini-2.5-flash` is deprecated (routed to 3.5-flash-lite from 1 Dec 2026) |
| `GEMINI_MAX_ITEMS` | `40` | Nodes per Gemini call (the rest use the heuristic) |
| `FIRECRAWL_API_KEY` / `FIRECRAWL_API_URL` | empty / `https://api.firecrawl.dev` | Change tracking, search, map, challenge fallback |
| `FIRECRAWL_WEBHOOK_SECRET` | empty | Verifies `X-Firecrawl-Signature` |
| `BACKEND_INTERNAL_URL` / `BACKEND_INTERNAL_SECRET` | empty / compose: `AGENTS_INTERNAL_SECRET` | RegChange POST to the backend |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Telegram alert |
| `WRITE_RATE_LIMIT_MAX_ATTEMPTS` | 30 per minute | check-now, releases, proposals, demo edits, webhook |
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
