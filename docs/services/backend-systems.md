# Backend: systems, workspace files and audits

The backend stores the audited AI systems, their versioned folders (the dossier the agent reads), and every
audit with its stage outputs and human decisions. Design background:
[agent context](../architecture/agent-context.md) (§2 dossier, §3 plugins, §5 filesystem).

**Agent memory is not here.** It lives in the agents service, one namespace per system, in `agent_runtime`
([agents service § Memory](agents-service.md#memory), [agent context §4](../architecture/agent-context.md#4-agent-memory-per-system)).
It is not user-visible and the backend has no memory routes.

> **Ownership exception.** Systems and audits are **not** scoped by `X-Client-Id`: every caller sees
> every system (for now). The client id is still required for rate limiting and logging, and is the actor
> (`client:<id>`) recorded on every write. A conversation attachment copied into a system folder must still
> belong to the caller.

## Files

| File | Holds |
| --- | --- |
| `core/database/models.py`, migrations `0003_systems_audits`, `0004_drop_memory_namespaces`, `0005_regulation_telegram`, `0006_sealed_findings` | the tables below + `conversations.system_id` / `audit_id`; 0004 deletes the old `memory:*` rows (data only) |
| `utils/workspace.py` | versioned files: path safety, write (new version, no-op on same bytes), tree, read, versions, delete, ledger, `dossier_version` |
| `utils/systems.py` | systems CRUD, the write body (JSON or multipart), attachment → system folder |
| `utils/audits.py` | audits, artifacts (versioning + supersede), approvals (decision + reason) |
| `utils/seed_import.py` | `SEED_CASES_DIR` → systems + files |
| `router/systems.py`, `router/workspace_files.py` | public routes; the file routes are one factory (`build_file_router`) |
| `router/audits.py`, `router/admin.py` | audits, artifacts, approvals; seed import |
| `utils/findings.py`, `router/findings.py`, `router/internal_findings.py` | sealed findings: seal (idempotent, hash chain, supersede), annotations, status events |
| `utils/register.py`, `router/register.py`, migration `0007_finding_register` | findings register: per-(system, obligation) state across audits, close / reopen, rebuild |
| `router/internal.py`, `core/security/internal.py` | the agents service's internal API and its shared-secret guard |
| `router/plugins.py`, `utils/plugins.py`, `schema/plugins.py` | plugins: the system graph, form defaults from MLflow, validated `plugin.yaml` writes (tests `tests/backend/test_plugins.py`) |

## Tables

Few typed columns (what is filtered or joined on); everything else in JSONB `data`.

| Table | Typed columns | Notes |
| --- | --- | --- |
| `systems` | `id` (`SYS-001`), `name`, `status` | `data`: parsed `system-card.yaml` (`card`), anything else |
| `workspace_file_blobs` | `sha256` (pk), `data`, `size_bytes` | content stored once per hash (plain bytes) |
| `workspace_files` | `namespace`, `path`, `version`, `blob_sha256`, `content_type`, `size_bytes`, `created_by`, `is_current` | one row per version; at most one current row per `(namespace, path)`; old rows stay |
| `workspace_events` | `namespace`, `path`, `version`, `action`, `actor`, `reason`, `audit_id`, `run_id`, `trace_id`, `at` | append-only ledger: `create`, `update`, `delete`, `read` |
| `audits` | `system_id`, `status`, `stage`, `created_by`, `pins` | `pins` (JSONB, copied from `data.pins` when the pipeline writes it: `kb_version`, `dossier_version`, `config_version`, `model_version`, `seeds`); `data`: `dossier_version` (locked at creation), `plugin_ids`, `kb_version`, ... |
| `audit_artifacts` | `audit_id`, `kind`, `name`, `version`, `status`, `parent_id`, `created_by` | `data`, `file_refs` (workspace paths, MLflow URIs, trace ids) |
| `approvals` | `audit_id`, `artifact_id`, `gate`, `decision`, `reason_category`, `comment`, `decided_by`, `at` | `edits` JSONB; append-only |
| `findings` | `audit_id`, `system_id`, `obligation_id`, `verdict`, `severity`, `gap_id`, `kb_version`, `prev_hash`, `hash` (unique), `created_by` | sealed verdict per obligation; `evidence_refs`, `citations`, `metrics_ref`, `counter_arguments`, `would_change_if`, `judges`, `critic`, extra fields in `data`. **Append-only**: a trigger rejects UPDATE / DELETE. No FK to `audits` on purpose |
| `finding_annotations` | `finding_id`, `kind` (`contest`, `accept_risk`, `remediation_planned`, `comment`), `body`, `actor` | append-only (trigger) |
| `finding_status_events` | `finding_id`, `status` (`stale`, `superseded`, ...), `superseded_by`, `reason`, `actor` | `data`; append-only (trigger). A new finding for the same (system, obligation) adds `superseded` to the earlier ones |
| `regulation_changes` | `id` (reg-memory's RC id), `status` | `data`: reg-memory's payload, the decision (`decidedBy`, `reason`), per-system `affected` |
| `finding_register` | `system_id`, `obligation_id` (unique together), `state` (`open`, `closed`, `resolved`, `monitoring`), `verdict`, `severity`, `article`, `title`, `gap_id`, `first_seen_audit_id`, `last_seen_audit_id`, `last_finding_id`, `opened_at`, `closed_by`, `close_reason`, `closed_at` | `history` (append-only list of events), `data` (`last_status`, `last_reasoning`, `last_evidence`, `closed_verdict`). Mutable state, unlike the sealed findings ([Findings register](#findings-register)) |
| `telegram_prompts` | `id` (callback token), `kind`, `key`, `status`, `decision`, `decided_by` | `data` (what it decides, reject state), `messages` (sent chat / message ids) |

**Namespaces:** `system:<id>` (the system folder; plugins under `plugins/<name>/`).

**Writes:** `PUT` adds version `n+1` and logs `create` / `update`. Writing the same bytes and content type as
the current version changes nothing (`changed: false`, `200`), so re-imports are idempotent. `DELETE` clears
the current version (history stays) and logs `delete`; a later write continues the numbering.

**Artifacts** are versioned per `(audit, kind, name)`: `name` is `main` for single outputs (`context`,
`model_profile`, `scenarios`, `scenario_analysis`, `generation_spec`, `dataset`, `dataset_analysis`,
`test_plan`, `test_result`, `critic`, `report`) or e.g. a finding id for `kind=finding`. A new version marks the
slot's earlier `proposed` / `approved` / `changes_requested` versions `superseded`.

**Approvals:** `decision` = `approved | rejected | changes_requested` sets the artifact's status and records
the `reasonCategory`, `comment` and `edits`. Nothing else is written: the pipeline passes a rejection's reason
to the next agent, which records the lesson in the system's memory with `remember` (agents service). Reason
categories: `wrong_fact`,
`wrong_interpretation`, `missing_info`, `wrong_metric`, `unrealistic_data`, `org_policy`, `other`.

## Routes

All `/v1` routes need `X-Client-Id`, are rate-limited (`WORKSPACE_RATE_LIMIT_*`) and logged.

| Route | Does |
| --- | --- |
| `GET / POST /v1/systems`, `GET / PATCH /v1/systems/{id}` | list, create (409 on a duplicate id), get, update (`data` merged) |
| `GET /v1/systems/{id}/files[?prefix=]` | the tree: current version of every file |
| `GET /v1/systems/{id}/files/{path}[?version=&format=json]` | raw bytes (sandboxed, `nosniff`, `X-File-Version`), or JSON with `text` / `dataB64` |
| `PUT /v1/systems/{id}/files/{path}` | new version: JSON `{content, contentType?, reason?, data?}` or multipart `file` (+ `reason`) |
| `DELETE /v1/systems/{id}/files/{path}[?reason=]` | delete (history kept) |
| `GET /v1/systems/{id}/files/{path}/versions` | every version, newest first |
| `GET /v1/systems/{id}/events[?path=]` | the ledger, newest first |
| `POST /v1/systems/{id}/files/from-attachment` | `{attachmentId, path?, reason?}`: copy one of the caller's attachments (default `uploads/<name>`) |
| `POST /v1/systems/{id}/audits` | start an audit (`{stage?, data?}`); locks `dossier_version` and `plugin_ids` |
| `GET /v1/audits[?systemId=]`, `GET / PATCH /v1/audits/{id}` | list; detail with every artifact and approval; set `status` / `stage` / merge `data` |
| `GET / POST /v1/audits/{id}/artifacts[?kind=&liveOnly=]` | list; new version `{kind, name?, data, fileRefs, parentId?, status?}` |
| `GET / PATCH /v1/audits/{id}/artifacts/{artifactId}` | one artifact; set `status` / merge `data`; **405 for kind `finding`** (sealed) |
| `POST /v1/audits/{id}/retry` | 202 `{auditId, outcome, status: running}`: a `failed` (or never-started `open`) audit calls the agents service's `POST /audits/{id}/run` (`trigger: retry`), which re-runs the failed node from its checkpoint; the error moves to `data.retries[]`. 409 when not failed or the pipeline is running / at a gate, 502 when the agents service is down |
| `GET /v1/audits/{id}/findings` | the audit's sealed findings (`FindingOut[]`, below) |
| `GET /v1/systems/{id}/findings[?current=true]` | the system's findings, newest first; `current` drops superseded ones |
| `GET / POST /v1/findings/{id}/annotations` | list; add `{kind, body}` (actor = `client:<X-Client-Id>`); there is no route that edits a finding |
| `GET / POST /v1/audits/{id}/approvals` | list; record `{gate, decision, artifactId?, reasonCategory?, comment?, edits?}` |
| `POST /v1/admin/import-seed` | import every `SYS-xxx/` folder of `SEED_CASES_DIR` (`_answer-key/`, hidden and `_`-prefixed dirs skipped) |
| `GET /v1/systems/{id}/register` | the findings register: `{system_id, summary: {total, by_state, by_verdict, open_gaps, needs_review, accepted_risks, resolved, monitoring}, items[]}` (each item with its `history`) |
| `GET /v1/systems/{id}/register/{obligation_id}` | one item with its history; 404 when unknown |
| `POST /v1/systems/{id}/register/{obligation_id}/close` | `{reason}` (required, non-blank, else 422): state `closed` (accepted risk), actor `client:<id>`; 409 when already closed |
| `POST /v1/systems/{id}/register/{obligation_id}/reopen` | `{reason?}`: state `open`; 409 when already open |
| `POST /v1/admin/rebuild-register[?reset=true&systemId=]` | fold every `done` audit into the register, oldest first; audits already folded are skipped; `reset` drops the register first (human closures are lost) |

`POST /v1/conversations` (and a `new` run start) also accept optional `systemId` / `auditId` (404 if unknown); summaries return them. Every run of such a conversation sends `system_id` / `audit_id` in the agents run context, which mounts that system's memory.

## Plugins

A plugin is the wrapper around one model of a system: how the audit agent reaches it (`access`), where it sits in
the system graph (`placement`), its I/O (`io.output`: type, label_field, score_field, positive_label) and its
expected behaviour (task, must, must_not, known_limitations). It is stored as `plugins/<name>/plugin.yaml` in the
system folder, because the agents read it from there; the UI edits it in the Plugins tab, not the Folder tab.
Design: [agent context § 3](../architecture/agent-context.md#3-plugins-how-to-reach-a-model-what-it-is-what-it-should-do).

| Route | Does |
| --- | --- |
| `GET /v1/systems/{id}/plugins` | the graph from `architecture.yaml`: `components` (each with `plugin`, `configured`, `testable`: a model or endpoint the agent can call), `edges` (`source`, `target`, `data`), `entry` (the end-to-end entry), and `plugins` (every `plugin.yaml`, parsed, by folder name). A plugin no component names shows as a standalone box |
| `GET /v1/systems/{id}/plugins/defaults?component=\|model=\|name=` | `{name, component, defaults, existing, mlflow}`: `defaults` is a complete card (the form's grey placeholders), `existing` the saved `plugin.yaml`, `mlflow` = `{status: ok \| not_found \| unreachable \| not_mlflow, version, run_id, description, tags, inputs, outputs}`. 404 for an unknown component, 422 when none of the three is given |
| `PUT /v1/systems/{id}/plugins/{name}` | body `{card, component?, reason?, upstream?, downstream?}`: validates, links the component in `architecture.yaml` (adds it when missing) and adds the edges `upstream → it` and `it → downstream` (known components only), then writes a new version of `plugins/<name>/plugin.yaml`. The card's `placement` is recomputed from the graph when the card has none, or when the link changed and edges were given or the old placement was `standalone`. Returns `{name, path, version, changed, card, architecture_updated}`. Invalid → 422 `Invalid plugin: ...` |
| `POST /v1/systems/{id}/plugins/components` | body `{name, kind: ml_model \| upstream_system \| human_review, model?, note?, upstream: [ids], downstream: [ids]}`: adds a box to the graph. Id = `<SYS>.<slug(name)>`; 409 if it exists, 422 for an empty name or a `model` that is not a `models:/` URI. Edges only to known components; sets `end_to_end_entry` (the first component with no incoming edge) when it is missing. 201 + the full graph |
| `DELETE /v1/systems/{id}/plugins/components/{component_id}` | removes the box and its edges (and `end_to_end_entry` if it pointed there); its plugin files stay in the folder. Returns the graph; 404 for an unknown component |

**Who builds the graph.** The PM registers a system with its documents only: no pipeline, no models. The AI
engineer builds the graph in the Plugins tab with these routes (a model, an upstream system or a human review
step per box, plus edges) and registers one plugin per model. Every change is a new version of `architecture.yaml`
(reason `<id> added to the graph`, `<id> removed from the graph` or `plugin <name> linked`).

**Defaults.** The registry is read over MLflow's REST API: `registered-models/alias` (or `model-versions/get` for
a numbered version), then `model-versions/get-download-uri` and the `MLmodel` artifact through the proxied artifact
store for the signature. From that: `access.uri` (the component's `models:/<name>@champion`), `access.rest_url`
(`/v1/models/<name>/predict` on the model gateway), `auth.secret_ref: env://MODEL_GATEWAY_TOKEN`, limits rps 5 /
timeout 10 s / 500 requests, environment `staging`, `expected_behaviour.task` from the version's description (or
its `intended_purpose` tag), `io.input_fields` from the signature inputs and `io.output` guessed from the outputs
(a float score + an int label → `binary_classification`). MLflow being down never fails the call: `mlflow.status`
says why.

**Validation** (`validate_card`): `access.type` in `mlflow_model | rest | llm_chat | batch_file | dataset_only`;
a `models:/<name>@<alias>` or `/<version>` URI for `mlflow_model`; a `url` for `rest` and `llm_chat`;
`auth.secret_ref` must be `env://NAME`; no key that looks like a credential (`token`, `password`, `secret`,
`api_key`, `bearer`; `secret_ref` is the allowed form); non-negative `limits`; a `name`. Plugin folder names match
`^[a-z0-9][a-z0-9-]{0,62}$`.

**One plugin per audit.** The audit pipeline tests `audit.data.target_plugin` when given, else the decision model
([agents pipeline](agents-pipeline.md)); `POST /v1/systems/{id}/audits` merges the request's `data` (e.g. `{"target_plugin": "cv-parser"}`) into the audit's data.

## Internal API (agents service)

`/internal/...`, guarded by `X-Internal-Secret` (or `X-Internal-Service-Secret`) = `AGENTS_SERVICE_SECRET`
(compose: `AGENTS_INTERNAL_SECRET`). Without a configured secret it is open only when `APP_ENV` is
`development` / `test`. Rate-limited per IP (`INTERNAL_RATE_LIMIT_*`). Every call is scoped to **one audit**
and through it one system; optional headers `X-Run-Id`, `X-Trace-Id`, `X-Agent-Name` go into the ledger.

| Route | Does |
| --- | --- |
| `GET /internal/audits/{id}` | `{audit (artifacts, approvals), system}` |
| `PATCH /internal/audits/{id}` | move `stage` / `status`, merge `data` |
| `GET /internal/audits/{id}/files[?prefix=]` | tree of the audit's system folder |
| `GET /internal/audits/{id}/files/{path}[?version=]` | JSON content; logs a `read` event (`audit_id`, `run_id`, `trace_id`) |
| `POST /internal/audits/{id}/artifacts` | new artifact version (actor `agent[:name]`) |
| `PUT /internal/audits/{id}/datasets/public/{slug}/{name}` | store one file of a human-approved public reference dataset (`router/internal_datasets.py`); only `data.csv`, `mapping.yaml`, `datasheet.md`, `source.json` under `datasets/public/<slug>/` (lower-case slug), JSON `{content, contentType?, reason?, data?}`, logged with run/trace ids |

| `POST /internal/audits/{id}/findings` | seal one finding (body below); 201, or 200 with the stored row when its `hash` (or, without a hash, its identical content in this audit) is already sealed; 409 when the hash is sealed in another audit |
| `POST /internal/findings/{id}/status-events` | `{status, superseded_by?, reason?, data?}` (e.g. `stale` from the change judge); 201 |
| `GET /internal/impact-index` | per system: its latest audit (with findings) → live `findings` (artifact data + `id`), `tests` (test_result rows), context `requirements`, `kb_version` (the change judge's impact index) |
| `GET /internal/audits/{id}/register` | the findings register of the audit's system (same shape as the public route): `load_context` hydrates the run with it |
| `POST /internal/systems/{id}/audits` | a new audit started by an agent (the change judge's re-run, actor `agent:<X-Agent-Name>`); starts its pipeline |
| `PUT /internal/regulation/changes/{id}/judgement` | `{affected: [...], decidedBy}` from the change judge onto `regulation_changes.data` (`judge: done`; a human `humanDecision` is kept) |

`POST /v1/systems/{id}/audits` (and the internal one) call the agents service's `POST /audits/{id}/run`
(`utils/audit_pipeline.py: start_pipeline`, best effort, off with `AUDIT_PIPELINE_AUTOSTART=false` or
`data.autostart: false`).

The agent cannot write the system folder, except `datasets/public/<slug>/` (the four files above) for a public dataset a human approved.

## Sealed findings

`FindingIn` (snake_case, what the pipeline's `seal` step posts): `{id?, obligation_id, verdict: pass|partial|gap|inconclusive|not_applicable|not_assessable_by_testing, severity: critical|high|medium|low|null, gap_id, metrics_ref, evidence_refs: [{path, sha256, mlflow_run_id?}], citations: [{provision_id, kb_version}], kb_version, reasoning, counter_arguments, would_change_if, judges: {rule, gemini, iris}, critic: {upheld, objection}, prev_hash?, hash?}`; any other field (`article`, `title`, ...) is kept in `data`. Without `hash` the backend computes `sha256(prev_hash + canonical JSON of the sealed fields)`; without `prev_hash` it chains to the audit's last finding.

`FindingOut` = the same fields + `id, audit_id, system_id, data, created_by, created_at, sealed: true, status` (`current`, `stale`, `superseded`, ... from the status events), `stale`, `annotations[]`, `status_events[]`.

## Findings register

The system's current state per obligation, across audits: an open gap stays open until a human closes it
with a reason, or a later audit finds it fixed. Fed when an audit moves to `status: done` (either PATCH
route; idempotent per audit: a row that already has an event of that audit is skipped). The latest sealed
finding per obligation of the audit counts; obligations the audit did not judge are untouched.

`is_gap` = verdict `gap` / `partial`, or a documentation gap (`gap_id` on a `not_assessable_by_testing`).

| Row now | Finding | State after (event, `register_status`) |
| --- | --- | --- |
| none | gap or `inconclusive` | `open` (`opened`, `new`) |
| none | `pass`, `not_applicable`, not testable | `monitoring` (`first_seen`, `new`) |
| `open` | gap / `inconclusive` / not testable | `open` (`still_open` or `verdict_changed`, `still_open`) |
| `open` | `pass` | `resolved` (`resolved`, `resolved`; `closed_by: audit:<id>`) |
| `resolved` / `monitoring` | gap or `inconclusive` | `open` (`regressed` if it was ever open, else `opened`) |
| `resolved` / `monitoring` | anything else | unchanged (`checked`, `unchanged`) |
| `closed` (human) | `pass` | `resolved` |
| `closed` | worse than the verdict at close | `open` (`reopened`, `regressed`) |
| `closed` | same or better | stays `closed` (`still_open`, `accepted_risk`) |

History event: `{at, audit_id | null, finding_id?, actor, kind, from, to, verdict, previous_verdict?, note}`;
`kind` is one of the events above plus `closed` / `reopened` by a human (`note` = the reason). The pipeline
mirrors these rules to stamp each sealed finding's `data.register_status` before it is sealed
([agents contract](../contracts/agents-contract.md)).

## Audit data and status

`status` is one of `open | running | waiting_approval | done | failed` (422 otherwise; the older
`completed` / `rejected` / `cancelled` / `error` are mapped to `done` / `failed`). `GET /v1/audits` and
`GET /v1/audits/{id}` return `data` with the fields the UI reads, passed through when the pipeline set them
(camelCase, or the snake_case `kb_version`, `card_version`, `trace_id`, `stage_traces`, `stage_durations`)
and derived otherwise: `systemName` (the system's name), `title` (`Audit of <name>`), `kbVersion`,
`cardVersion`, `traceId`, `stageTraces` (`{}`), `stageDurations` (`{}`), `trigger` (`manual`), `summary`.

**Resuming the pipeline.** An approval of a pipeline gate (`public_data`, `scenarios`, `datasets`), from the
UI or from Telegram, is forwarded after it is recorded to the agents service's `POST /audits/{id}/resume`
(`utils/audit_pipeline.py`: `system_id`, `gate`, `decision`, `reasonCategory`, `comment`, `edits`,
`artifactId`, `decidedBy`). Best effort: a pipeline that is not waiting (409) or down is logged; the
approval stays recorded.

## Regulation proxy (`/v1/regulation`)

The browser cannot reach reg-memory (internal, `X-Internal-Secret`), so the backend proxies it
(`router/regulation.py` -> `utils/regulation.py`, `REG_MEMORY_URL` + `REG_MEMORY_INTERNAL_SECRET`) and maps
its shapes to the frontend types (`features/regulation/lib/types.ts`). Rate-limited like `/v1/systems`;
reg-memory down = 502, unknown id = 404.

| Route | Does |
| --- | --- |
| `GET /v1/regulation/sources` | catalog + each source's main-document versions (fetch log collapsed to one entry per version) as `RegSource[]` |
| `GET …/documents/{id}/text?version=` | `DocText` |
| `GET …/documents/{id}/diff?from=&to=` | `DocDiff`: unified diff of the two versions' texts (difflib) |
| `GET …/changes`, `GET …/changes/{id}` | `RegChange`, newest first. `changeType` mapped (`editorial`; `new_interpretation` → `clarification`; `date`, `scope` → `scope_change`; `substantive` → `new_obligation`; removed → `repeal`; the most severe wins), `provisions` = changed node ids, `fromVersion` / `toVersion` = the source's document version in the two releases, `status` = our decision, else `accepted` once the candidate release was activated. Extras: `impactedRequirements`, `judge`, `decidedBy` |
| `POST …/changes/{id}/decision` `{status, reason?}` | `accepted` activates the candidate release in reg-memory; `rejected` records it; already decided = 409 |
| `POST …/changes/{id}/systems/{systemId}` `{decision}` | human override of the judge decision for one system |
| `GET …/releases`, `POST …/releases/{v}/activate`, `POST …/check-now`, `GET …/provisions[/{id}]`, `GET …/requirements` | pass-through (reg-memory's own shapes) |

**Not in reg-memory yet: the per-system change judge.** `affected` is `[]` and `judge` is `pending` until a
judge (or a human override) writes `regulation_changes.data.affected`.

`POST /internal/regulation/changes` (internal secret): reg-memory announces a RegChange (`BACKEND_INTERNAL_URL`,
compose default `http://backend:8000`); the payload is stored in `regulation_changes` (idempotent per id)
and announced on Telegram. `GET /v1/agents` proxies the agents service's `GET /agents` (502 when it is down).

## Telegram approvals

Every HITL gate is also sent to Telegram with **Approve / Reject / Open in app**; a button records the decision
exactly like the UI and resumes the agent. Setup: [Telegram guide](../guides/telegram.md).
Code: `utils/telegram.py` (Bot API over httpx, best effort), `utils/telegram_gates.py` (gates, decisions, the
long-polling worker), `router/telegram.py` (optional webhook), table `telegram_prompts` (migration `0005`).

| Gate | Sent when | Approve / Reject does |
| --- | --- | --- |
| audit `scenarios` / `datasets` | an audit enters `waiting_approval` (`PATCH /v1/audits/{id}` or `/internal/audits/{id}`) | `record_approval` (same as `POST /v1/audits/{id}/approvals`) on the gate's latest reviewed artifact |
| public dataset pick (`public_data`) | the audit waits at `find_public_data`, or a `public_dataset_candidates` artifact is proposed (one message) | one button per top-3 candidate: approves with `edits.selected` (also set on the artifact) |
| regulation change | reg-memory POSTs a RegChange | Accept = activate the candidate release; Reject = rejected |
| chat tool approval | a chat run pauses on a `HITL_INTERRUPT` with `action_requests` (not `ask_user`) | the inference resume queue (same as `POST /v1/inference/runs/{id}/resume`) for every action of the interrupt |

- Messages are compact: system, gate, 2-3 key numbers (scenarios and risks, failed dataset gates, findings) and
  the link `${APP_PUBLIC_URL}/audits/<id>?step=<step>` (in the text; also a URL button when the URL is public,
  since Telegram refuses localhost buttons).
- **Reject** asks why: reason-category buttons, then a ForceReply for a comment (`-` skips it).
- **Allow-list:** only chats in `TELEGRAM_CHAT_ID` receive gates; a button pressed in any other chat is refused.
- **Idempotent:** one open prompt per gate (`key`); a gate already decided (in Telegram, in another chat or in
  the app) answers "Already decided by X". A decision made in the app edits the Telegram message too.
- Decisions are recorded as `decided_by: telegram:<username>`; the message is edited to "✅ Approved by @x".
- **Long polling** (`getUpdates`, no public URL needed) starts in the lifespan when `TELEGRAM_BOT_TOKEN` is set;
  `TELEGRAM_WEBHOOK_URL` (with the required `TELEGRAM_WEBHOOK_SECRET`) switches to the webhook
  `POST /telegram/webhook`. No token: every Telegram call is a no-op (logged once). `/start` or `/chatid` in a
  chat answers its id.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SEED_CASES_DIR` | `/seed-cases` | seed cases; compose mounts the `seed_cases` volume read-only |
| `WORKSPACE_MAX_FILE_BYTES` | `10485760` | largest single file (413 above) |
| `WORKSPACE_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `240` / `60` | per client, all `/v1` routes above |
| `INTERNAL_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `1200` / `60` | per IP, `/internal` |
| `REG_MEMORY_URL` / `REG_MEMORY_INTERNAL_SECRET` | `http://reg-memory:8010` / compose dev value | the regulation proxy |
| `REG_MEMORY_TIMEOUT_SECONDS` / `REG_MEMORY_CHECK_TIMEOUT_SECONDS` | `30` / `300` | reg-memory calls; `check-now` with `wait` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Telegram approvals; comma-separated allow-listed chat ids |
| `TELEGRAM_WEBHOOK_URL` / `TELEGRAM_WEBHOOK_SECRET` | empty | webhook mode instead of long polling |
| `APP_PUBLIC_URL` | `http://localhost:8080` | base of the "Open in app" links |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | the registry the plugin defaults read |
| `MLFLOW_TIMEOUT_SECONDS` | `5` | each MLflow call of the plugin defaults (not passed by compose; the default applies) |

## Not included yet

- `workspace_file_meta` (indexed fields + pgvector) from the design: filters run on JSONB `data` for now.
- Blob encryption at rest (conversation blobs are plain too).
- The agents-service side (mounting `/systems/<id>/` from these routes).
