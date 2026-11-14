# Backend: systems, workspace files, memory and audits

The backend stores the audited AI systems, their versioned folders (the dossier the agent reads), the agent
memory, and every audit with its stage outputs and human decisions. Design background:
[agent context](../architecture/agent-context.md) (§2 dossier, §3 plugins, §4 memory, §5 filesystem).

> **Ownership exception.** Systems, audits and memory are **not** scoped by `X-Client-Id`: every caller sees
> every system (for now). The client id is still required for rate limiting and logging, and is the actor
> (`client:<id>`) recorded on every write. A conversation attachment copied into a system folder must still
> belong to the caller.

## Files

| File | Holds |
| --- | --- |
| `core/database/models.py`, migration `0003_systems_audits` | the tables below + `conversations.system_id` / `audit_id` |
| `utils/workspace.py` | versioned files: path safety, write (new version, no-op on same bytes), tree, read, versions, delete, ledger, `dossier_version` |
| `utils/systems.py` | systems CRUD, the write body (JSON or multipart), attachment → system folder |
| `utils/audits.py` | audits, artifacts (versioning + supersede), approvals (+ memory proposal on rejection) |
| `utils/seed_import.py` | `SEED_CASES_DIR` → systems + files |
| `router/systems.py`, `router/memory.py`, `router/workspace_files.py` | public routes; the file routes are one factory reused per namespace |
| `router/audits.py`, `router/admin.py` | audits, artifacts, approvals; seed import |
| `router/internal.py`, `core/security/internal.py` | the agents service's internal API and its shared-secret guard |

## Tables

Few typed columns (what is filtered or joined on); everything else in JSONB `data`.

| Table | Typed columns | Notes |
| --- | --- | --- |
| `systems` | `id` (`SYS-001`), `name`, `status` | `data`: parsed `system-card.yaml` (`card`), anything else |
| `workspace_file_blobs` | `sha256` (pk), `data`, `size_bytes` | content stored once per hash (plain bytes) |
| `workspace_files` | `namespace`, `path`, `version`, `blob_sha256`, `content_type`, `size_bytes`, `created_by`, `is_current` | one row per version; at most one current row per `(namespace, path)`; old rows stay |
| `workspace_events` | `namespace`, `path`, `version`, `action`, `actor`, `reason`, `audit_id`, `run_id`, `trace_id`, `at` | append-only ledger: `create`, `update`, `delete`, `read` |
| `audits` | `system_id`, `status`, `stage`, `created_by` | `data`: `dossier_version` (locked at creation), `plugin_ids`, `kb_version`, ... |
| `audit_artifacts` | `audit_id`, `kind`, `name`, `version`, `status`, `parent_id`, `created_by` | `data`, `file_refs` (workspace paths, MLflow URIs, trace ids) |
| `approvals` | `audit_id`, `artifact_id`, `gate`, `decision`, `reason_category`, `comment`, `decided_by`, `at` | `edits` JSONB; append-only |

**Namespaces:** `system:<id>` (the system folder; plugins under `plugins/<name>/`), `memory:system:<id>`,
`memory:org`, `memory:proposals` (the only one an agent writes; entries live under `<system id>/`).

**Writes:** `PUT` adds version `n+1` and logs `create` / `update`. Writing the same bytes and content type as
the current version changes nothing (`changed: false`, `200`), so re-imports are idempotent. `DELETE` clears
the current version (history stays) and logs `delete`; a later write continues the numbering.

**Artifacts** are versioned per `(audit, kind, name)`: `name` is `main` for single outputs (`context`,
`model_profile`, `scenarios`, `scenario_analysis`, `generation_spec`, `dataset`, `dataset_analysis`,
`test_plan`, `test_result`, `critic`, `report`) or e.g. a finding id for `kind=finding`. A new version marks the
slot's earlier `proposed` / `approved` / `changes_requested` versions `superseded`.

**Approvals:** `decision` = `approved | rejected | changes_requested` sets the artifact's status. A rejection or
change request with a `reasonCategory` or `comment` also writes a memory proposal
`memory:proposals/<system>/PROP-<id>.yaml` (`status: proposed`, the reason, edits and source ids), inactive
until a human copies it into `memory:system:<id>` or `memory:org`. Reason categories: `wrong_fact`,
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
| `/v1/memory/org/...`, `/v1/memory/proposals/...`, `/v1/memory/systems/{id}/...` | the same `files`, `files/{path}`, `versions`, `events` routes over the memory namespaces |
| `GET /v1/audits[?systemId=]`, `GET / PATCH /v1/audits/{id}` | list; detail with every artifact and approval; set `status` / `stage` / merge `data` |
| `GET / POST /v1/audits/{id}/artifacts[?kind=&liveOnly=]` | list; new version `{kind, name?, data, fileRefs, parentId?, status?}` |
| `GET / PATCH /v1/audits/{id}/artifacts/{artifactId}` | one artifact; set `status` / merge `data` |
| `GET / POST /v1/audits/{id}/approvals` | list; record `{gate, decision, artifactId?, reasonCategory?, comment?, edits?}` |
| `POST /v1/admin/import-seed` | import every `SYS-xxx/` folder of `SEED_CASES_DIR` (`_answer-key/`, hidden and `_`-prefixed dirs skipped) |

`POST /v1/conversations` also accepts optional `systemId` / `auditId` (404 if unknown); summaries return them.

## Internal API (agents service)

`/internal/...`, guarded by `X-Internal-Secret` (or `X-Internal-Service-Secret`) = `AGENTS_SERVICE_SECRET`
(compose: `AGENTS_INTERNAL_SECRET`). Without a configured secret it is open only when `APP_ENV` is
`development` / `test`. Rate-limited per IP (`INTERNAL_RATE_LIMIT_*`). Every call is scoped to **one audit**
and through it one system; optional headers `X-Run-Id`, `X-Trace-Id`, `X-Agent-Name` go into the ledger.

| Route | Does |
| --- | --- |
| `GET /internal/audits/{id}` | `{audit (artifacts, approvals), system}` |
| `PATCH /internal/audits/{id}` | move `stage` / `status`, merge `data` |
| `GET /internal/audits/{id}/files[?scope=system\|memory\|org&prefix=]` | tree of the audit's system folder, its memory, or org memory |
| `GET /internal/audits/{id}/files/{path}[?scope=&version=]` | JSON content; logs a `read` event (`audit_id`, `run_id`, `trace_id`) |
| `POST /internal/audits/{id}/artifacts` | new artifact version (actor `agent[:name]`) |
| `POST /internal/audits/{id}/memory-proposals` | `{name?, content, contentType?, reason?}` → `memory:proposals/<system>/<name>` |

The agent cannot write the system folder or active memory: no internal route does.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `SEED_CASES_DIR` | `/seed-cases` | seed cases; compose mounts the `seed_cases` volume read-only |
| `WORKSPACE_MAX_FILE_BYTES` | `10485760` | largest single file (413 above) |
| `WORKSPACE_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `240` / `60` | per client, all `/v1` routes above |
| `INTERNAL_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | `1200` / `60` | per IP, `/internal` |

## Not included yet

- `workspace_file_meta` (indexed fields + pgvector) from the design: filters run on JSONB `data` for now.
- Blob encryption at rest (conversation blobs are plain too).
- Promote / retire / stale actions as first-class routes: today a human activates a proposal with a `PUT` into
  the scope folder, and the ledger records it.
- The agents-service side (mounting `/systems/<id>/` and `/memory/...` from these routes).
