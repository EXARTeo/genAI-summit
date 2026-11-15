# Plan 02: System registration and the risk-classification agent

Status: proposed (2026-11-15). Owner: Mnamon team. Budget: **3-4 hours, 3 agents in parallel**, before the 18:00 code freeze.
Scope: the PM registers a new AI system in the UI; a small, fast agent proposes its AI Act risk class from the description and documents, grounded in reg-memory at a pinned `kb_version`; a human approves or rejects; an approved class updates the system card, and the obligations follow. Plugins, the pipeline graph and audits are already built (Plugins tab, plan 01) and only consumed here.

---

## 0. In one paragraph

A PM opens **Register a system**, fills five short steps (identity, purpose, deployment and people, documents, review) and creates a `draft` system with no models. On the new system's Overview, **Classify risk** runs the classifier: code first (Annex III / Art. 5 / Art. 50 / profiling / role pre-checks from the structured fields, provision texts fetched at the active `kb_version`), then **one Gemini step** that reads the dossier and the regulation and guidance through tools and returns a structured proposal (class, route, Annex basis, Art. 6(3) assessment, role, citations, counter-arguments, uncertainties), then a **code verifier** (citations exist at the kb, the answer is internally consistent), then **Oumi Iris** as an independent multiple-choice check on the final class. Disagreement or low confidence sets `needs_human`. The proposal is `proposed`; the AI Officer or PM **approves** (card updated: `risk_class`, `annex_basis`, `role`, `art_6_3_claim`, `features`; obligations preview refreshes) or **rejects with a reason** (the reason rides into the next run as feedback). History is append-only. When an accepted regulation change touches a provision the classification relied on, it becomes `stale` and the UI asks for a re-run.

---

## 1. Principles (inherited from plan 01, applied here)

| # | Principle | Here |
|---|---|---|
| P1 | Deterministic skeleton, LLM for judgement | Pre-checks, dates, citation checks, consistency rules and the Iris comparison are code. Gemini only judges the open questions (which area, does 6(3) hold, which role). |
| P2 | Every claim cites a source | Each conclusion carries `citations[]` of provision or interpretation ids **at the pinned `kb_version`**; the verifier rejects unknown ids. Guidance is marked non-binding (and `draft` for the Art. 6 guidelines). |
| P3 | Pin, then read | A run pins `kb_version` (active release) and `dossier_version` (file versions read). Both are stored on the classification. |
| P4 | Humans approve | Agents write `proposed`; only a human makes `approved`. One approve/reject, no multi-step approval workflow. |
| P5 | Append-only history | Proposals are never edited. Decisions and `stale` are new event rows. A re-run is a new classification. |
| P6 | Two judges | Gemini proposes, Iris decides independently on the class, code compares. Disagreement → `needs_human`, never silently resolved. |
| P7 | Fast | 1 Gemini step (+ at most 1 automatic redo) + 1 Iris call. Target under 60 s. Not a graph. |

---

## 2. Roles and user stories

| Role | Story | Built? |
|---|---|---|
| **PM** | "I register a new AI system with its name, description, intended purpose, deployment, affected people and documents. I do not configure models." Then "I press Classify risk and get a proposal I can read, with the law it rests on." | **This plan** |
| **AI Officer** | "I review the proposed class, its basis, the 6(3) reasoning and the counter-arguments, and approve it or reject it with a reason. I am told when a regulation change makes an approved class stale." | **This plan** (no login: whoever clicks is the actor, `client:<X-Client-Id>`) |
| **AI Engineer** | "After the class is approved I build the pipeline graph and plugins (Plugins tab) and run audits against the obligations that now apply." | Built (Plugins tab, audits) |

---

## 3. Scope and non-goals

**In:** register wizard (UI) on the existing `POST /v1/systems` + `PUT /v1/systems/{id}/files/{path}`; classifier endpoint in the agents service; `system_classifications` + `classification_events` tables; approve/reject; card update; obligations preview for an unaudited system; stale on regulation change; Langfuse trace per run; mock mode; tests.

**Out (non-goals):** login or permissions; a multi-step PM approval workflow; editing a proposal (reject and re-run instead); the chat copilot calling the classifier (a `classify_system` chat tool is a later slice; AG-UI stays the chat protocol, this run is a backend-driven job like the change judge); PDF/DOCX text extraction for uploaded documents (only `.md`, `.txt`, `.yaml`, `.json` are read in this slice; other files are stored and listed as "not read"); GPAI model provider obligations beyond a flag; national law; Telegram buttons for this gate (stretch S-T only).

---

## 4. What exists today (verified, file paths)

| Area | Fact | Where |
|---|---|---|
| Systems API | `POST /v1/systems {id, name, status, data}`, `PATCH` merges `data`, versioned folder files `PUT /v1/systems/{id}/files/{path}`, events; systems not scoped by client id | `mnamon/backend/router/systems.py`, `schema/systems.py` (`SYSTEM_ID_PATTERN`), `router/workspace_files.py` |
| Card location | The audit pipeline reads `system-card.yaml` from the dossier (`pipeline/graph.py` ~l.451); the UI reads `system.data.card` (seed import sets it, `utils/seed_import.py` l.90) | both must be updated on approve |
| Card fields | `id, name, organisation, role, risk_class (high_risk), annex_basis ("Annex III 4(a)"), intended_purpose, deployment {status, countries, users, since}, affected_persons, human_oversight, protected_attributes, known_proxies, components, declared_metrics, org_thresholds, provenance` | `mnamon/mlflow-seed/cases/SYS-00X/system-card.yaml` |
| Card → obligations | `card_profile()` reads `role`, `risk_class` (`high*` → `high`), `annex_basis` (regex), `features`, `exempt_6_3 / art_6_3_claim / derogation_6_3 / art_6_3` (dict with `claimed` ok) | `mnamon/agents/pipeline/obligations.py` l.72 |
| Obligations API | `GET /v1/obligations?role&risk_class&basis&annex_point&features&exempt_6_3&date&kb_version&include_not_applicable` (rows `OBL.AIA.6.4.non-high-risk-assessment`, `OBL.AIA.49.2.registration-non-high-risk` apply when `exempt_6_3: true`) | `mnamon/reg-memory/router/obligations.py`, `corpus/obligations.yaml` |
| Obligations tab | Reads the **latest audit's** `obligation_map` artifact only: an unaudited system shows "No obligation map yet" | `frontend/src/features/systems/components/detail_parts/ObligationsTab.tsx` |
| Risk badge | `RISK_META` keys `prohibited, high_risk, limited_risk, minimal_risk`; anything else renders "Unclassified" | `frontend/src/features/systems/lib/styles.ts` |
| Small-pipeline shape to copy | Change judge: route → `utils/change_judge.py` → `DecisionModel.decide(task)` (Iris first, Gemini step fallback, fake under `AGENTS_FAKE_LLM`); questions as YAML | `agents/router/audits.py`, `pipeline/impact.py`, `pipeline/decision.py`, `prompts/decisions/change_judge.yaml` |
| Deep-agent step | `StepRunner.run(step, brief, scope, feedback=, fake=)`: layered prompt (`rules.md` → step file → `method.md` → `MEMORY.md` → date), tools by `STEP_TOOLS`, result via `ToolStrategy(STEP_RESULTS[step])`, 2 attempts | `agents/pipeline/steps.py`, `pipeline/prompting.py`, `pipeline/schemas.py`, `pipeline/fakes.py` |
| Regulation tools | `lookup_provision(id)` (text + children + **interpretation ids only**), `search_regulation(q)` (calls `/v1/provisions?q=`, ids + titles) | `agents/pipeline/steps.py` `_regulation_tools` |
| Backend → agents | Change judge runs in a backend background task after accept (`utils/regulation.py` `decide_change`, `_judge_tasks`); audits via `utils/audit_pipeline.py` `_post` with `internal_headers()` | `mnamon/backend/utils/` |
| Append-only trigger | `reject_append_only_change()` + `trg_<table>_no_<verb>` | `backend/core/database/migrations/versions/0006_sealed_findings.py`; latest migration is `0007_finding_register.py` |
| Langfuse | `trace_run_config(config, kind=, name=, tags=)`; Iris calls are `iris.decide` spans | `agents/harness/observability/langfuse.py`, `pipeline/decision.py` |

### 4.1 reg-memory corpus check (catalogue `mnamon/reg-memory/engine/catalog/sources.yaml`)

| Needed for classification | In the catalogue? | Notes |
|---|---|---|
| AI Act text (Art. 3, 5, 6, 25, 50, Annex I, Annex III) | yes: `ai-act-consolidated` (Cellar), `ai-act` (OJ, recitals) | Parser ids `AIA.5.1.f`, `AIA.6.3`, `AIA.ANNEX_III.4.a`, `AIA.50.1`, `AIA.3.3`, `AIA.25.1`; Annex I lists the Union harmonisation acts |
| Digital Omnibus (dates, Art. 5(1)(ba)/(bb)) | yes: `digital-omnibus-ai` + `faq-digital-package-omnibus` | Dates come from each node's `valid_from` / `valid_from_by_basis` (parser applies Art. 113 as amended): code reads them, the LLM never computes dates |
| Guidelines on prohibited practices (Art. 5) | yes: `guidelines-prohibited-practices` (+ `-pdf`, `-communication`), final | |
| Guidelines on Art. 6 classification | **draft only**: `guidelines-high-risk-draft` (19 May 2026, `monitor: true`), `draft-guidelines-high-risk-general`, `-annex-i`, `-annex-iii`, Service Desk explorer + summaries/examples | Must be cited as *non-binding draft*. Final version is watched |
| AI system definition (out of scope test) | yes: `guidelines-ai-system-definition` (+ `-pdf`) | |
| Art. 50 transparency | yes: `guidelines-art50-transparency`, `faq-art50-transparency`, `cop-transparency-ai-generated-content` | |
| GPAI | yes: `guidelines-gpai-scope`, GPAI code of practice chapters, FAQs | Flag only in this slice |
| Role (provider / deployer, Art. 25) | Art. 3, 25 in the act; FAQs (`ai-act-service-desk-faq`, `faq-navigating-ai-act`) | No dedicated guideline exists; say so in `uncertainties` when role is borderline |
| Demo source | `demo-art6-guideline-mirror` (served by reg-memory, editable via `PUT /v1/demo/mirror`) | Its Example 12 says a CV **parser** that only structures CVs is a 6(3)(a) narrow procedural task: the demo hook (§11) |

**Gaps found (fixed in this plan, agents side only, no reg-memory change):**

1. **Guidance text is not reachable by agents.** `lookup_provision` returns interpretation *ids* only; there is no tool that reads `GET /v1/interpretations/{id}`. Most PDFs are one interpretation node per document (100+ pages). → New tool `read_guidance(interpretation_id, query)`: fetches the node, returns the `query`-matching paragraphs (deterministic keyword windows, max ~4,000 chars) + `binding`, `status`, `source_id`, `kb_version`.
2. **Guidance is not searchable.** `search_regulation` only covers provisions (and uses the unranked `/v1/provisions?q=`). → `search_regulation` switches to the ranked `GET /v1/provisions/search` and `read_guidance` is found through `GET /v1/interpretations?relates_to=<provision>` (listed by `lookup_provision`).
3. **Runtime presence not verified here** (stack not running during planning). Pre-flight for slice A (5 min): `.\scripts\stack.ps1 exec reg-memory python -c "..."` or the backend proxy `GET /api/v1/regulation/provisions/AIA.6.3`, `.../AIA.ANNEX_III.4.a`, `.../AIA.5.1.f`, and `GET /v1/interpretations?relates_to=AIA.6.3` must return the draft Art. 6 guideline and the demo mirror. If the draft PDFs failed to download, run `POST /v1/ingest {source_ids: [draft-guidelines-high-risk-general, draft-guidelines-high-risk-annex-iii]}` then `POST /v1/releases` + activate.

---

## 5. UX flow

```mermaid
flowchart LR
  G[Systems gallery\n+ Register a system] --> W1[1 Identity\nid, name, organisation,\nhow you got it]
  W1 --> W2[2 Purpose\ndescription, intended purpose,\ndecision it informs,\nhuman oversight, profiling?]
  W2 --> W3[3 Deployment and people\ncountries, users, status,\naffected persons, vulnerable groups,\ninteracts with people?, generates content?,\nsafety component of a product?]
  W3 --> W4[4 Documents\nupload md/txt/yaml\n(+ others stored, not read)]
  W4 --> W5[5 Review and create]
  W5 --> S[System page, Overview\nstatus draft, Unclassified\nCTA: Classify risk]
  S --> RUN[Classifying...\npre-checks → classifier →\nverify → Iris]
  RUN --> CARD[Result card\nclass + route + basis,\n6(3) assessment, role,\ncitations, counter-arguments,\nconfidence, uncertainties,\nIris agrees / needs_human]
  CARD -->|Approve| OK[card updated,\nstatus active,\nobligations preview refreshes,\nPlugins tab hint for the engineer]
  CARD -->|Reject + reason| RJ[history row rejected;\nRe-run uses the reason]
  OK -. regulation change accepted .-> ST[Stale badge\n+ Re-classify]
```

- **Register a system** button in `SystemsGallery` header → route `/systems/new` (full page with the shared `Stepper`, not a modal: five steps on mobile need room).
- Step 1 proposes the next free id (`SYS-004`), editable, validated against `SYSTEM_ID_PATTERN`. "How did you get this system?" = *built in-house* / *bought or licensed and used as is* / *bought and changed or rebranded* (feeds the role pre-check; Art. 25).
- Step 2 "Does it evaluate or predict personal aspects of people (performance, reliability, behaviour, location, health, preferences)?" = *yes / no / not sure* (profiling: 6(3) never applies if yes).
- Step 3 yes/no switches map to `features` (`interacts_with_persons`, `generates_synthetic_content`, `emotion_recognition`, `biometric`) and `annex_i_product` (free text: which product law, e.g. machinery, medical devices).
- **Fill example** button (demo speed): pre-fills "CV Parser" (structures CVs into fields, no ranking).
- **Create** = `POST /v1/systems {id, name, status: "draft", data: {card}}` + `PUT .../files/system-card.yaml` (card with `risk_class: unclassified`, `provenance: declared_by_pm`) + one `PUT .../files/docs/<name>` per document. Then navigate to the system's Overview.
- Overview gets a **Classification** card at the top: empty → *Classify risk*; running → three-step progress with elapsed time (polls every 2 s); proposed → result card + *Approve* / *Reject*; approved → compact summary + *Re-classify* + *History* (list of past runs, status chips); stale → warning badge + reason ("RC-2026.11.15-1 changed AIA.6.3") + *Re-classify*.
- Header badge: `riskMeta(card.risk_class)` already shows "Unclassified"; add a small `proposed` / `stale` dot next to it.
- Obligations tab: when no audit exists, shows the **preview** from the approved class (§7.3), titled "Obligations that follow from the approved classification (preview, no audit yet)".

---

## 6. Architecture

```mermaid
flowchart TB
  UI[Frontend\nClassify risk] -->|POST /v1/systems/{id}/classifications| BE[backend\nrow status running\nbackground task]
  BE -->|POST /systems/{id}/classify\nrequest: card, docs text, pins, feedback| AG
  subgraph AG["agents: pipeline/classify.py (not a graph)"]
    P0[pin kb_version\nactive release] --> P1[pre-checks (code)\nAnnex III candidates, Art. 5 flags,\nArt. 50 features, profiling, role,\nAnnex I flag]
    P1 --> P2[fetch provision texts (code)\nAIA.5.1.*, AIA.6.1-4,\ncandidate Annex III points,\nAIA.50.*, AIA.3.3/3.4, AIA.25.1\n+ related interpretation ids]
    P2 --> P3[classify_risk step\nGemini reasoning, StepRunner\ntools: lookup_provision,\nsearch_regulation, read_guidance]
    P3 --> P4[verify (code)\ncitations exist at kb,\nconsistency rules]
    P4 -- problems, 1 redo --> P3
    P4 --> P5[Iris check\nmultiple choice on the class\n+ profiling yes/no]
    P5 --> P6[compare (code)\nagree? confidence?\n→ needs_human]
    P6 --> P7[dates (code)\nvalid_from of the route's\nprovisions at kb]
  end
  AG -->|ClassificationResult| BE
  BE -->|status proposed / failed\n+ event row| DB[(system_classifications\nclassification_events)]
  UI -->|approve / reject| BE
  BE -->|approve: new versions of\nsystem-card.yaml + classification.yaml,\ndata.card merge, status active| FS[(workspace_files)]
  RM[(reg-memory\nkb_version)] --- AG
  LF[(Langfuse trace\nclassify:CLS-...)] --- AG
```

### 6.1 Deterministic pre-checks (`agents/pipeline/classify.py`, data in `agents/pipeline/classification/hints.yaml`)

| Check | Input | Output | Rule |
|---|---|---|---|
| Annex III candidates | `description`, `intended_purpose`, `affected_persons`, `deployment.users`, doc titles | `annex_iii_candidates: [{point: "4.a", provision: AIA.ANNEX_III.4.a, matched: [recruit, CV, shortlist]}]` | keyword table per point (1 biometrics … 8 justice/democracy), whole words, case-insensitive; top 3 by matches |
| Art. 5 red flags | same text + `features` | `art5_flags: [{provision: AIA.5.1.f, matched: [emotion, workplace]}]` | keyword pairs per practice (social scoring, emotion at work/school, untargeted face scraping, biometric categorisation of sensitive traits, crime prediction from profiling, real-time RBI, subliminal/manipulative, exploiting vulnerabilities) |
| Art. 50 features | wizard switches | `features[]` | direct |
| Profiling | wizard answer | `profiling: yes / no / unknown` | direct; `yes` blocks 6(3) in the verifier |
| Role hint | "how did you get it" | `role_hint: provider / deployer / provider_by_art25` | in-house → provider; as-is → deployer; changed or rebranded → provider (Art. 25(1)) |
| Annex I flag | `annex_i_product` | `annex_i: {flag, product_law}` | non-empty → route 6(1) must be addressed |
| Out-of-scope hint | description | `ai_system_doubt: bool` | rule-based only (no learning/inference words) → the agent must address Art. 3(1) |

Pre-checks are **hints, never answers**: the agent must confirm or reject each candidate and flag (the verifier checks every flag is addressed).

### 6.2 The classifier step (`classify_risk`)

- Runs through the existing `StepRunner` (add `classify_risk` to `STEP_ROLES` = `reasoning`, `STEP_TOOLS` = `("regulation",)`, `STEP_PROMPTS`, `STEP_RESULTS`, a fake in `fakes.py`). `StepScope(audit_id=<classification id>, system_id, kb_version, step="classify_risk", regmem=RegMemory())`. Recursion limit for this step: 24 (constant next to `STEP_RECURSION_LIMIT`).
- **The dossier comes in the brief, not through file tools** (file tools are audit-scoped, `BackendInternal` → `/internal/audits/{id}`): the backend sends the card and the readable documents (path, version, text truncated to 6,000 chars each, 30,000 total). Documents are framed as untrusted data.
- The brief also carries the pre-check output and the fetched provision texts, so most runs need 0-4 tool calls.
- A rejection's reason (from the previous run) is passed as `feedback={source: "human", reason}`.

### 6.3 Verifier (code, `classify.py: classification_problems(result, kb_ids, prechecks)`)

1. Every `citations[].provision_id` exists at `kb_version` (lookup cache from the run; interpretation ids `INT.*` checked against `GET /v1/interpretations/{id}`).
2. `risk_class == high_risk` ⇒ `route in {art6_1_annex_i, art6_2_annex_iii}` and `annex_basis` set; Annex III basis ⇒ it cites the `AIA.ANNEX_III.<point>` node.
3. `art6_3.holds == true` ⇒ `profiling` is not `yes`, a `condition` in `a|b|c|d` is named, `AIA.6.3` is cited, `risk_class != high_risk`, and the result lists the Art. 6(4) documentation duty in `next_steps`.
4. `risk_class == prohibited` ⇒ cites an `AIA.5.1.*` node. Every pre-check `art5_flag` and `annex_iii_candidate` appears in `art5_screening` / `annex_iii_considered` with a reason.
5. Guidance citations carry `binding: false`; an Art. 6 guideline citation carries `status: draft`.
6. At least one `counter_arguments` entry and one `would_change_if` entry.

Problems → one automatic redo with the problem list as `feedback={source: "verifier"}`; still failing → result kept, `verifier_problems` listed, `needs_human: true`.

### 6.4 Iris check (`prompts/decisions/risk_classification.yaml`, task via `DecisionTask`)

```yaml
risk_class:
  type: choice
  instructions: >-
    Given the system's intended purpose, deployment, affected persons and features (`system`)
    and the provisions in `provisions`, which AI Act category does this system fall into?
  criteria:
    prohibited: An Art. 5 practice.
    high_risk_annex_i: Safety component of (or itself) a product under Annex I law needing third-party conformity assessment (Art. 6(1)).
    high_risk_annex_iii: In an Annex III area and the Art. 6(3) derogation does not hold (Art. 6(2)).
    not_high_risk_6_3: In an Annex III area, but only a narrow procedural, improving, pattern-detecting or preparatory task and no profiling (Art. 6(3)).
    transparency_only: Not high-risk; interacts with people or generates content (Art. 50).
    minimal: None of the above.
profiling:
  type: noul
  instructions: Does the system evaluate or predict personal aspects of natural persons (profiling, GDPR Art. 4(4))?
```

Code maps the agent's `(risk_class, route)` to the same six options and compares. `needs_human = disagree or iris_confidence < 0.6 or agent.confidence < 0.6 or verifier_problems or (iris.profiling > 0.5 and art6_3.holds)`. Iris not configured → Gemini fallback is **not** used here (it would grade itself): `iris: null`, `needs_human: true`, reason "independent check unavailable". `AGENTS_FAKE_LLM` fakes Gemini only, as everywhere.

### 6.5 Dates (code)

`key_dates` = for the route's core provisions (`AIA.5`, `AIA.6.1`/`AIA.6.2`, `AIA.ANNEX_III`, `AIA.50`, `AIA.6.4`, `AIA.49.2`), each node's `valid_from` (or `valid_from_by_basis[family]`) at the pinned kb, with `amended_by` (e.g. `OMNIBUS.1.12`) so the card can say "high-risk duties apply from 2027-12-02 (Annex III, as amended by the Digital Omnibus)".

### 6.6 Speed and cost

Pre-checks + provision fetch: ~1 s (≤ 15 reg-memory calls, run concurrently). Gemini: 1 call + 0-4 tool turns (+ 1 redo at most). Iris: 1 call. One Langfuse trace `classify:<CLS id>` (tags `classification`, `system:<id>`), the Iris span nested.

---

## 7. Data model and API

### 7.1 Ids and statuses

- Id: `CLS-<SYSTEM_ID>-<YYYYMMDD>-<HHMM>` (UTC), `-2`, `-3` on collision (same helper style as audit ids in `backend/utils/audits.py`).
- `status`: `running → proposed | failed`; `proposed → approved | rejected`; `approved → stale | superseded`. Only one `running` per system (409 otherwise). Only `proposed` can be decided (409 otherwise). A newer approval moves the previous approved one to `superseded`.

### 7.2 Tables (backend, migration `0008_system_classifications.py`; renumber if another 0008 lands first, `alembic check` must pass)

```text
system_classifications
  id               PK  CLS-...
  system_id        FK systems.id, index
  status           running|proposed|failed|approved|rejected|stale|superseded
  kb_version       pinned at run start
  dossier_version  {path: version} of the files sent
  input            JSON  card snapshot + doc list sent (no doc text)
  result           JSON  ClassificationResult (null while running) — written ONCE
  error            text  (failed only)
  trace_id         Langfuse trace id
  previous_id      the run this one re-does (after a reject or stale)
  created_by       client:<id>
  created_at, updated_at

classification_events          (append-only: reject_append_only_change() trigger, as in 0006)
  id, classification_id FK, system_id, action  created|proposed|failed|approved|rejected|stale|superseded
  actor, reason, data JSON (e.g. {change_id, provisions}), at
```

Why a table and not only `system.data.classification` + a file: the HITL needs a queryable status and an append-only decision log (same principle as findings); the dossier file gives the human-readable, versioned copy. Both are written on approve. `result` is written once by `store_result()` (code guard: refuses if not null); `status` only moves along §7.1 through one function, and every move adds an event.

### 7.3 Backend routes (`router/classifications.py`, mounted under `/v1/systems`; thin → `utils/classifications.py` → `schema/classifications.py`; rate-limited + logged like `router/systems.py`)

| Method | Path | Body / query | Does |
|---|---|---|---|
| POST | `/v1/systems/{id}/classifications` | `{previousId?}` | Create row `running` + event; spawn background task: build request (card from `system-card.yaml` current version, readable docs under `docs/` + root `.md`, last rejection reason of `previousId`), call agents, `store_result` → `proposed` or `failed`. 202 + row |
| GET | `/v1/systems/{id}/classifications` | | Newest first, with events |
| GET | `/v1/systems/{id}/classifications/{cid}` | | One, with events |
| POST | `/v1/systems/{id}/classifications/{cid}/decision` | `{decision: approve\|reject, reason?}` (reason required for reject, ≤ 2,000 chars) | Approve: status + events, previous approved → `superseded`, write `classification.yaml` and a new `system-card.yaml` version (actor = client), merge `data.card`, system `status: active`. Reject: status + event. 409 if not `proposed` |
| GET | `/v1/systems/{id}/obligations` | `?date=` | Preview: card → reg-memory `GET /v1/obligations` (role, `risk_class` `high_risk`→`high`, `basis`, `annex_point`, `features`, `exempt_6_3`, `kb_version` of the approved classification, `include_not_applicable=true`). Prohibited → `{prohibited: true, items: [OBL.AIA.5...]}` |

Card fields written on approve (keys `card_profile()` already reads):

```yaml
risk_class: high_risk | limited_risk | minimal_risk | prohibited | out_of_scope
annex_basis: "Annex III 4(a)" | "Annex I: Regulation (EU) 2023/1230" | null
role: provider | deployer
features: [interacts_with_persons, ...]
art_6_3_claim: {claimed: true, condition: a, assessed_in: CLS-SYS-004-20261115-1405}
classification: {id: CLS-..., kb_version: 2026.11.15-1, approved_by: client:..., approved_at: ...}
provenance: classified_by_agent_approved_by_human
```

### 7.4 Agents route (`router/classifications.py`, internal secret; `schema/classifications.py`; logic `utils/classify_runs.py`)

`POST /systems/{system_id}/classify` (synchronous, ≤ 120 s; the backend awaits it inside its background task, exactly like the change judge):

```json
{
  "classification_id": "CLS-SYS-004-20261115-1405",
  "kb_version": null,
  "card": {"id": "SYS-004", "name": "CV Parser", "intended_purpose": "...", "deployment": {}, "affected_persons": "...",
           "human_oversight": "...", "profiling": "no", "acquisition": "in_house", "features": [], "annex_i_product": null},
  "documents": [{"path": "docs/system-specification.md", "version": 1, "text": "..."}],
  "feedback": {"source": "human", "reason": "It also ranks candidates, see spec §3"},
  "trace": {"name": "classify:CLS-SYS-004-20261115-1405"}
}
```

Returns `ClassificationResult` (§8.2) with `kb_version` filled. Errors: reg-memory down → 502 (backend marks `failed`); Gemini error after 2 attempts → 502.

### 7.5 Stale rule (backend, `utils/classifications.py: mark_stale_for_change(db, change)`)

Called inside `utils/regulation.py` `decide_change` right after a change is **accepted** (next to `judge_systems`); the Telegram accept path already goes through `decide_change` (`utils/telegram_gates.py` l.425), so both are covered. No LLM:

- `changed` = the change's provision and interpretation ids + their `relates_to` (same logic as `agents/pipeline/impact.py` `changed_provisions` / `_touches`, ~15 lines copied, prefix match both ways).
- For each `approved` classification: `relied_on` = its citation ids ∪ core set of its route (`AIA.5`, `AIA.6`, `AIA.ANNEX_III.<point>`, `AIA.50`, `AIA.25`, `AIA.3.3`, `AIA.3.4`).
- Touch → event `stale` with `{change_id, provisions: [...]}`, status `stale`. The card is **not** changed (the approved class stays in force until a human approves a new one); the UI shows the badge and *Re-classify* (`previousId` = the stale one).
- Optional: a Telegram text message "SYS-004 classification is stale after RC-…" via the existing notifier (no buttons).

---

## 8. Prompts and the output schema

### 8.1 `agents/pipeline/prompts/classify_risk.md` (≤ 200 words; layered by `compose_step_prompt`: rules → this → method → memory → date)

```markdown
# Classify an AI system under the AI Act
Propose the system's risk class and route. A human approves; you only propose.

Parameters: kb_version = the brief's; binding sources = AIA.*, OMNIBUS.*; guidance (INT.*) is non-binding,
Art. 6 guidelines are a draft.

Order (stop at the first that holds, but record why the earlier ones do not):
1. Art. 3(1): is it an AI system at all?
2. Art. 5: each pre-check flag, then any other practice that fits. 
3. Art. 6(1): Annex I product or safety component needing third-party assessment.
4. Art. 6(2): Annex III point; confirm or reject each candidate.
5. Art. 6(3): does a condition (a)-(d) hold? Never if the system profiles people.
6. Art. 50: transparency duties (also on top of high-risk).
7. GPAI: is it a GPAI model, or built on one?
8. Role: provider or deployer (Art. 3(3), 3(4), 25).

Look up the text before you rely on it (lookup_provision, read_guidance). Cite every
conclusion. Give the strongest counter-argument and what would change the answer.
Say what you could not establish from the dossier; do not guess facts. Dates are added by code.
```

`prompts/rules.md` and `prompts/method.md` are reused unchanged (precedence, result contract, verification). The brief (`render_brief`) carries: `system` (card), `prechecks`, `provisions` (texts), `documents` (untrusted), `kb_version`, `feedback`.

### 8.2 `ClassificationResult` (pydantic `_Strict` in `agents/pipeline/schemas.py`; copied to `backend/schema/classifications.py` and `frontend/src/features/classification/lib/types.ts`)

```text
risk_class           prohibited | high_risk | limited_risk | minimal_risk | out_of_scope
route                art5 | art6_1_annex_i | art6_2_annex_iii | art6_3_exempt | art50_only | none | not_ai_system
annex_basis          "Annex III 4(a)" | "Annex I: <act>" | null
annex_basis_id       AIA.ANNEX_III.4.a | null
role                 provider | deployer
role_reasoning       str (≤ 60 words) + citations
art5_screening[]     {provision_id, applies: bool, why}
annex_iii_considered[] {provision_id, applies: bool, why}
art6_3               {considered: bool, condition: a|b|c|d|null, profiling: yes|no|unknown, holds: bool|null, why}
transparency         {features: [...], provisions: [AIA.50.1, ...]}
gpai                 {is_gpai_model: bool, built_on_gpai: bool, note}
reasoning            str (≤ 200 words)
counter_arguments[]  {argument, would_change_to}           (≥ 1)
would_change_if[]    str                                    (≥ 1)
uncertainties[]      {question, why_it_matters, ask}        (ask = PM | legal | engineer)
next_steps[]         str  (e.g. "Document the Art. 6(4) assessment before placing on the market")
confidence           0..1
citations[]          {id, kb_version, quote (≤ 200 chars), binding: bool, status: final|draft}
--- added by code ---
kb_version, prechecks, key_dates[] {what, date, provision_id, amended_by}, iris {choice, probabilities,
confidence, profiling} | null, agreement: bool | null, needs_human: bool, needs_human_reasons[],
verifier_problems[], decided_by: gemini+iris | gemini, trace_id
```

---

## 9. Tests (no paid API calls: `AGENTS_FAKE_LLM`, fake Iris client injected, `httpx.MockTransport`)

| File | Covers |
|---|---|
| `tests/agents/test_classify.py` | pre-checks: CV text → `4.a` candidate; "emotion recognition of employees" → `AIA.5.1.f` flag; profiling `yes` → 6(3) blocked. Verifier: unknown citation, high_risk without basis, 6(3) with profiling, unaddressed flag, missing counter-argument. Compare: agree → `needs_human false`; disagree / low confidence / no Iris → `true`. Dates from fake provision `valid_from`. Route `POST /systems/{id}/classify` end to end with fakes (fake reg-memory transport) |
| `tests/agents/test_classify.py` (same file) | `read_guidance` windows the query, caps length, returns `binding`/`status`; tool error → text, not an exception |
| `tests/backend/test_classifications.py` | create → background → `proposed` (agents MockTransport); second create while running → 409; approve → new `system-card.yaml` version with the §7.3 keys + `classification.yaml` + `data.card` merged + previous approved `superseded`; reject without reason → 422; decide twice → 409; agents 502 → `failed`; `mark_stale_for_change` touches / does not touch; obligations preview maps `high_risk`→`high` and `exempt_6_3` |
| `tests/backend/test_classifications.py` (same file) | `alembic check` passes; on Postgres (skip on SQLite), `UPDATE classification_events` fails |
| `frontend/src/features/onboarding/**/*.test.tsx` | wizard validation (id pattern, required purpose), "Fill example", create calls in order |
| `frontend/src/features/classification/**/*.test.tsx` | result card renders class, 6(3), citations (draft badge), counter-arguments, `needs_human` banner; reject requires a reason; stale badge |

Commands: `uv run python -m pytest tests/agents -k classif`, `mnamon\backend\.venv\Scripts\python -m pytest tests/backend -k classif`, `npm run typecheck && npm run lint && npm run test` in `mnamon/frontend/`.

---

## 10. Work split (3 agents, parallel, own paths only; the §7-§8 contract is frozen first)

| Agent | Owns (create/edit) | Shared files (small additive edits, commit last) | Effort |
|---|---|---|---|
| **A · agents** | `mnamon/agents/pipeline/classify.py`, `pipeline/classification/hints.yaml`, `pipeline/prompts/classify_risk.md`, `pipeline/prompts/decisions/risk_classification.yaml`, `router/classifications.py`, `schema/classifications.py`, `utils/classify_runs.py`, `tests/agents/test_classify.py` | `pipeline/steps.py` (`STEP_*`, `read_guidance`, ranked search), `pipeline/prompting.py` (`STEP_PROMPTS`), `pipeline/schemas.py` (`ClassificationResult`, `STEP_RESULTS`), `pipeline/fakes.py`, `pipeline/clients.py` (`RegMemory.interpretation(id)`), `main.py` (router), `docs/contracts/agents-contract.md`, `docs/services/agents-pipeline.md` | ~2.5 h |
| **B · backend** | `mnamon/backend/router/classifications.py`, `utils/classifications.py`, `schema/classifications.py`, `core/database/migrations/versions/0008_system_classifications.py`, `tests/backend/test_classifications.py` | `core/database/models.py`, `main.py` (router), `utils/regulation.py` (one call in `decide_change`), `docs/services/backend-systems.md` | ~2.5 h |
| **C · frontend** | `mnamon/frontend/src/features/onboarding/**` (wizard), `features/classification/**` (panel, result card, decision dialog, history, hooks, types), `pages/RegisterSystemView.tsx`, `shared/lib/mocks/handlers/classifications.ts` (+ fixture: a CV Parser proposal with 6(3)(a), one `needs_human` case, one stale) | `features/systems/components/SystemsGallery.tsx` (button), `detail_parts/OverviewTab.tsx` (panel), `detail_parts/SystemHeader.tsx` (dot), `detail_parts/ObligationsTab.tsx` (preview fallback), `lib/routes.ts` (`classifications`, `obligations` api paths), app router (`/systems/new`), `docs/services/frontend.md` | ~3 h (mock mode first, live at the end) |

Order: 0:00 freeze contract (this file) → A, B, C in parallel (C on mocks) → 2:30 wire live (B calls A; C turns mocks off) → 3:00 demo dry run → 3:30 fixes, `CHANGELOG.md` `[Unreleased]` (whoever finishes last), `.\scripts\check.ps1`.

New env vars (add to the agents section of `.env.example`): `CLASSIFY_TIMEOUT_S=120` (backend), `CLASSIFY_IRIS_MIN_CONFIDENCE=0.6` (agents). No new secrets.

Stretch **S-T** (only if done by 17:00): Telegram gate "Approve / Reject" for a `proposed` classification via `utils/telegram_gates.py`; chat tool `classify_system` (HITL).

---

## 11. Demo script (~2 min, inside the 3-minute pitch)

1. Systems → **Register a system** → *Fill example* (SYS-004 "CV Parser": turns CVs into structured fields for recruiters, no ranking; profiling: no) → upload `system-specification.md` → Create. Card shows **Unclassified**.
2. **Classify risk** (~30-60 s). Result: **minimal / not high-risk via Art. 6(3)(a)**, Annex III 4(a) considered, cites `AIA.6.3`, `AIA.ANNEX_III.4.a` and the guideline example (`INT.demo-art6-guideline-mirror...`, *draft, non-binding*); counter-argument "if it filters or ranks, 4(a) applies in full"; next step "document the Art. 6(4) assessment, register under Art. 49(2)"; Iris agrees (p shown).
3. Open the Langfuse trace: pre-checks, tool calls (`lookup_provision AIA.6.3`, `read_guidance`), verifier, `iris.decide`.
4. **Approve** → card updated, Obligations tab shows `OBL.AIA.6.4` + `OBL.AIA.49.2` (+ Art. 4, Art. 5 screening).
5. Regulation → edit the demo mirror (remove Example 12; `PUT /v1/demo/mirror` via "Simulate change") → *Check now* → **Accept** → SYS-004 classification shows **Stale** ("RC-… changed guidance on AIA.6.3").
6. **Re-classify** → now **high-risk, Annex III 4(a)** (or `needs_human` if Iris disagrees: shown as the safety net) → Approve → the obligation list grows to the full provider set; the engineer's Plugins tab is next.

Backup: SYS-001 (CV Screener) re-classified from its card → high-risk 4(a), confirms the seeded class.

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Gemini call slow or hits recursion limit | Provision texts pre-fetched into the brief; recursion limit 24; timeout 120 s → `failed` with a *Retry* button |
| Draft Art. 6 guideline PDFs missing from the active kb | Pre-flight check (§4.1 item 3); the demo mirror alone covers the demo |
| Iris unavailable or not trained for this question | `needs_human` with the reason; the demo still works; Iris span visible when it answers |
| Parallel migration number clash | Check `alembic heads` before commit; renumber |
| Wrong legal answer presented as fact | Always `proposed`; counter-arguments + uncertainties mandatory (verifier); guidance marked draft/non-binding; UI copy "proposal, not legal advice" |
| Prompt injection in uploaded docs | Docs framed as untrusted data in the brief; the step has no write tools |
| Card drift (dossier file vs `data.card`) | Approve writes both in one transaction through one function |

---

## 13. Acceptance checklist

1. A PM registers SYS-004 from the UI in under a minute; the system exists with `status: draft`, `system-card.yaml` v1 and its documents in the Folder tab.
2. *Classify risk* returns a `proposed` classification in < 90 s with: class, route, basis, Art. 6(3) assessment, role, ≥ 1 counter-argument, ≥ 1 `would_change_if`, uncertainties, confidence, `key_dates` from the kb, and every citation valid at the pinned `kb_version`.
3. Iris's choice and probabilities are shown; a forced disagreement (test fixture) shows `needs_human` with the reason.
4. Approve writes `system-card.yaml` v2 (the §7.3 keys) and `classification.yaml`, updates the header badge, and the Obligations tab preview lists the obligations reg-memory activates for that card.
5. Reject requires a reason; the next run's Langfuse trace shows it in the brief's `feedback`.
6. `classification_events` rejects `UPDATE`/`DELETE` (Postgres); a re-run is a new row; history lists all runs.
7. Accepting a regulation change that touches a cited provision marks the approved classification `stale` without changing the card.
8. The pipeline's `card_profile()` reads the approved card unchanged (an audit of SYS-004 after approval resolves the expected obligation map).
9. All tests pass with no paid API calls; `.\scripts\check.ps1` is green; docs (`agents-contract.md`, `agents-pipeline.md`, `backend-systems.md`, `frontend.md`) and `CHANGELOG.md` updated.

---

## 14. Open questions

| # | Question | Default if no answer |
|---|---|---|
| Q1 | Who may approve: PM or AI Officer? | Anyone (no login); the actor is recorded; UI copy says "AI Officer approves" |
| Q2 | Should a `stale` class keep driving obligations? | Yes, until a new one is approved (shown with the stale badge) |
| Q3 | `out_of_scope` (not an AI system): keep the system in Mnamon? | Yes, `status: archived` suggestion, no obligations |
| Q4 | Deployer systems (SYS-003 style): classify too? | Yes, same flow; obligations preview uses `role=deployer` (catalogue has few deployer rows; say so) |
| Q5 | Read PDFs uploaded by the PM? | Not in this slice; listed as "not read" in the result's `uncertainties` |
