# Agents service

`mnamon/agents/` runs the agents and streams their work to the backend as
AG-UI events over SSE. It implements [the backend contract](../contracts/agents-contract.md)
exactly; this page is how it is built inside. Port **8003**, FastAPI, **Google
Gemini** models through LangChain (`langchain-google-genai`) and deepagents, durable state in the
`agent_runtime` Postgres database.

It ships two agents: the chat's **`mnamon`** (*Mnamon Copilot*, a declarative deep agent in
`mnamon/agents/definitions/mnamon/`, the default: [The chat agent](#the-chat-agent-mnamon-copilot)) and the
Python **`audit-pipeline`** (the engineer audit pipeline and the change judge, a `workflow`:
[agents pipeline](agents-pipeline.md)). More declarative agents go in `mnamon/agents/definitions/<slug>/`
(see [Adding an agent](#adding-an-agent)).

## Routes

| Method | Path | Auth | What |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Liveness (`{"status": "ok"}`), no I/O |
| `GET` | `/agents` | secret | The agents this service runs (manifest list, `default: true` on `DEFAULT_AGENT_SLUG`, `kind: chat\|workflow`), so a UI can pick one; the chat lists only `kind: "chat"` |
| `POST` | `/agents/{slug}/stream` | secret | Start a run (contract § `/stream`) |
| `POST` | `/agents/{slug}/resume` | secret | Resume a run paused on HITL interrupt(s) (contract § `/resume`) |
| `*` | `/ap/...` | secret + launch token | The Agent Protocol the async sub-agents call, in process |
| `*` | `/tasks/...` | secret | The backend's internal task API (async sub-agents) |
| `POST` | `/audits/{id}/run`, `/audits/{id}/resume`; `GET /audits/{id}/state` | secret | Start / resume (a gate decision) / inspect an audit's pipeline ([agents pipeline](agents-pipeline.md)) |
| `POST` | `/changes/{id}/judge` | secret | Impact index + change judge for a RegChange |
| `GET` | `/internal/systems/{id}/memory` | secret | Read-only view of a system's agent memory: `MEMORY.md` + every entry with provenance (debugging, judges; [Memory](#memory)) |

"Secret" is `X-Internal-Service-Secret` equal to `INTERNAL_SERVICE_SECRET`
(the backend sends its `AGENTS_SERVICE_SECRET`, the same value). Missing or
wrong is `403`. With no secret configured every caller is accepted, which the
settings allow only for `APP_ENV=development|test`; anywhere else the service
refuses to start without one.

## Structure

```text
mnamon/agents/
  main.py              app, lifespan (Langfuse, agent_runtime + checkpointer, TaskRunner), /health
  router/              thin HTTP: inference (stream/resume), catalog (GET /agents),
                       agent_protocol + tasks (async sub-agents)
  utils/               endpoint logic: inference (the run), agents (registry), mcp_tools,
                       hitl_resume (the resume Command), checkpointer (head + bindings),
                       declarative (YAML helpers), async_tasks
  schema/              DTOs, one module per concept (import the leaf module)
  definitions/         declarative agent definitions, one folder per agent
  pipeline/            the audit pipeline (graph, deep-agent steps, prompts, verifiers) and the
                       impact pipeline (impact index, change judge): agents-pipeline.md
  core/                settings, logging (hashed ids), security (internal secret), error_handling
  harness/
    abstractions/      BaseAgent, DeepAgent, LangGraphAgent, AgentSpec, YamlDeepAgent
    agui/              emitter, normalizer (LangGraph chunks -> AG-UI), keepalive, previews
    async_tasks/       background sub-agents: runner, store, token, specs, middleware
    checkpointer/      agent_runtime pool + AsyncPostgresSaver, fork seeding
    conversation_files/ a conversation's files as encrypted rows, uploads ingest
    filesystem/        the run's mount table, branch scratch, sandbox backend
    memory/            per-system agent memory: system_memories table, /memory/ mount, binding
    middlewares/       tool errors, summarization (compaction), rate-limit retry
    models/            Gemini model access (gemini.py), the scripted fake model (fake.py),
                       reasoning requests (Gemini include_thoughts; OpenAI summaries)
    observability/     Langfuse (opt-in, fail-open), nested under the backend's trace
    prompt_engineering/ the composed system prompt, one module per section
    tools/             ask_user, present_artifact, view_image, render_chart, remember, forget;
                       gates, registry
```

## A run, end to end

1. `POST /agents/{slug}/stream` → `utils.inference.stream_run`: the slug is
   looked up in the registry (404 when unknown), `config.context` must carry
   `client_id` and `conversation_id` (400 otherwise), and the agent is built
   for this run (one instance per request).
2. The request's inline uploads are written into `/conversation/input/`
   (next section). The agent gets the messages without their `attachments`;
   a message that brought uploads gets one text line naming their paths.
3. The optional MCP session opens (`MCP_GATEWAY_URL`); its tools attach to the
   agent: the ones the spec declares, or all of them with `all_mcp_tools`.
4. With `fork_from`, the new branch thread is seeded from the parent's
   checkpoint (state, compaction and branch scratch rows).
5. The graph streams (`messages`, `updates`, `tasks`, with sub-graphs); the
   normalizer turns each chunk into AG-UI frames. A keepalive comment goes out
   after 15 s of silence. A client disconnect cancels the run.
   Gemini streams give the same contract as OpenAI's (replayed from recorded
   runs in `tests/agents/test_agui_gemini.py`): list-of-parts content becomes
   text deltas (the thought-signature part never reaches the UI); its thought
   summary, all on one content index, is split into one thinking step per
   titled section (`**Title**`); tool calls come whole and open their cards
   from the settled message, parallel ones in call order; a HITL pause closes
   the open thinking phase (`THINKING_END`) before `HITL_INTERRUPT`.
6. At the end: `CUSTOM CHECKPOINT_COMMITTED {thread_id, checkpoint_id}`. A
   failure is one `RUN_ERROR` (public message only) and nothing after it.

`/resume` builds the same agent on the paused thread, reads the pending
interrupts from the durable checkpoint and turns the decisions into a
`Command(resume=...)` keyed by interrupt id (`utils/hitl_resume.py`). A named
interrupt that is no longer pending is `409` with `stale_interrupt_ids` and
`pending_interrupt_ids`, and nothing is applied.

**Identity.** There are no users. Everything is keyed by the backend's
anonymous `client_id` (the files, the scratch rows, the tasks). It is a
capability, not authentication: logs show it only as `h:<16 hex>` (HMAC-SHA256
with `LOG_REDACTION_SECRET`, the backend's scheme, so set the same secret in
both services), Langfuse gets the same pseudonym, and the sandbox runner gets
the hash without its `h:` prefix.

## Filesystem

Every path the agent sees is a virtual route of one `CompositeBackend`
(`harness/filesystem/workspace.py`). Nothing is a directory a run can write.

| Path the agent sees | Backed by | Agent can write | Shared with |
| --- | --- | --- | --- |
| `/conversation/input/` | `conversation_files` rows (the user's uploads) | no (read-only) | every agent and sub-agent of the conversation, the sandbox |
| `/conversation/output/` | `conversation_files` rows | yes | same; deliverables, presented with `present_artifact` |
| `/conversation/…` (anything else) | `conversation_files` rows | yes | every agent of the conversation |
| `/large_tool_results/` | `conversation_files` rows (offloaded tool results) | no | the conversation |
| `/conversation_history/` | `conversation_files` rows (history the summarizer offloaded) | no | the conversation |
| `/reference/` | the agent's definition folder in the image | no | only that agent |
| `/memory/MEMORY.md` | derived from `system_memories` rows on every read (only with `system_id`) | no (writes ignored) | every agent and step of every audit of the system |
| `/memory/audits/<audit_id>/<name>.md` | one `system_memories` row | own audit only (`remember`, `write_file`) | same |
| any other path (`/notes.md`) | `branch_scratch_files` rows, keyed by (conversation, branch thread) | yes | the orchestrator and every async task of that branch, live |

- **Conversation files** (`harness/conversation_files/store.py`): two tables.
  `conversation_file_blobs` holds each content once per client
  (`(client_id, sha256)`, AES-encrypted with `LANGGRAPH_AES_KEY`);
  `conversation_files` maps `(conversation_id, path)` to a blob. Listing and
  globbing never read bytes.
- **Sub-agents see the same files.** A blocking sub-agent runs inside the
  run's graph on the same backend. An async task is rebuilt by the task runner
  with the same `client_id` and `conversation_id` (so the same
  `/conversation/` rows) and with the orchestrator's `branch_thread_id` in its
  context (so the same scratch rows).
- **Branch scratch** forks with the branch: an edit or retry copies the source
  branch's rows to the new branch thread, after which they diverge.

### How uploads land in `/conversation/input/`

The backend sends every non-image file of a message (and any image past its
inline budget) as an `attachments` entry with `data_base64` (contract
§ Attachment). Before the run, `harness/conversation_files/inputs.py`
`ingest_uploads` writes each one to `/conversation/input/<name>`:

- only `role: user` messages and `origin: upload` entries; the bytes must
  match the declared `sha256` and `size_bytes`;
- the name is reduced to one safe path segment; a different file under a name
  already taken becomes `<stem>-<id8>.<ext>`;
- idempotent: an upload already stored under its name is left alone, so a
  full-history seed that re-sends every upload costs a hash per file;
- skipped and logged, never a failed run: `data_base64: null`
  (`"omitted": "budget"`), a mismatch, an unusable name, a file over
  `CONVERSATION_FILE_MAX_BYTES`.

Images that arrive inline as `image_url` parts are seen by the model directly
and are not copied to `input/`.

### Deliverables: `present_artifact`

The agent writes a file to `/conversation/output/` and calls
`present_artifact(path, title, summary)`. The tool reads the bytes then and
parks them for the stream (`PresentedFiles`), and the normalizer turns the
call's successful result into `CUSTOM PRESENT_ARTIFACT` with
`{artifact_id, path, filename, title, summary, mime, size, data_base64}`. The
backend stores `data_base64` as a generated attachment of the answer. Bytes
ride the event up to `OUTPUT_MAX_FILE_BYTES` (25 MB) per file and
`OUTPUT_MAX_FILES` (20) files per run; past either, the card is sent without
them. Only the orchestrator's calls produce a card: a sub-agent writes the
file and the orchestrator presents it.

## Memory

Agent memory is **per audited system** (`harness/memory/`): every step, agent and sub-agent working on any
audit of `SYS-00X` shares one memory. It is **not user-visible** (no public API, no UI); the backend keeps no
memory of its own. Design background: [agent context § 4](../architecture/agent-context.md#4-agent-memory-per-system).

- **When.** Only when `config.context.system_id` is set ([contract § Config](../contracts/agents-contract.md)).
  `audit_id` makes it writable (`remember` / `forget` attach); `step` is recorded as provenance. Without a
  `system_id` nothing changes: no `/memory/` route, no tools, no prompt section. A background task inherits
  the three keys from the run that started it (`InheritedContext`).
- **Table** `system_memories` in `agent_runtime`, created on boot (`CREATE TABLE IF NOT EXISTS`, no Alembic):
  PK `(system_id, audit_id, name)`, `summary`, `content_md` (the body the agent reads, verbatim), and provenance
  columns `step`, `agent_name`, `source_run_id`, `source_thread_id`, `created_by`, `trust_level`,
  `created_at`, `updated_at`.
- **Mount.** `/memory/` is a deepagents `StoreBackend` over `SystemMemoryFiles` (a LangGraph `BaseStore`
  bound to the run's system). `MEMORY.md` is derived on every read (one line per entry: date · step · agent ·
  **name** — summary, grouped by audit, newest first); a write to it is accepted and ignored. A `write_file` /
  `edit_file` may write `audits/<current audit>/<slug>.md` only (body stored verbatim, provenance from the
  run, never from the body); other audits' folders, deletes and unknown paths are refused with a tool error.
- **Prompt.** `ensure_built` loads `MEMORY.md` once and the `memory` section (`prompts/memory_prompt.py`)
  injects it into the main agent's prompt and every sub-agent's (blocking and async). Entries are read on
  demand. A memory outage is logged and the run continues without it.
- **Tools.** `remember(name, summary, content)`: slugged name (`[a-z0-9-]`, 80 chars), summary ≤ 200 and
  content ≤ 8000 characters, idempotent upsert by name, never raises (every failure is a string), refuses a
  new entry past the cap. `forget(name, audit_id?)`: HITL-gated, idempotent. Both names are reserved: an MCP
  tool called `remember` / `forget` is dropped. A sub-agent whose `tools:` list narrows its tools still gets them.
- **Gate contract.** When a human rejects or requests changes at a gate, the pipeline passes the reason to the
  next agent run (same `system_id` / `audit_id`, the step being redone); that agent records the lesson with
  `remember` before redoing the work. The backend only records the decision.
- **Debugging.** `GET /internal/systems/{id}/memory` (internal secret) returns `{systemId, index, entries}`
  with each entry's path and provenance.

## The chat agent: Mnamon Copilot

`definitions/mnamon/` (`agent.yaml`, `AGENT.md`, `subagents/`): the engineer's EU AI Act compliance
copilot. It answers questions about the regulation (citing provisions with their `kb_version`), a
system's dossier and plugins, and an audit's findings, tests, critic and reports; explains a finding
with its counter-arguments; drafts evidence or gap notes as `proposed`; starts an audit only on request.

- **Model:** `google_genai:${GEMINI_MODEL}` (the placeholder is the deployment's `GEMINI_MODEL`,
  `utils/declarative.py::expand_model_id`). With `AGENTS_FAKE_LLM=true` every declarative agent runs on
  `DryRunChatModel` (`harness/models/fake.py`): it calls one real tool for the conversation's scope
  (`read_audit`, `list_system_files` or `list_systems`) and answers with a "Dry run" note and an excerpt.
- **Tools** (native, `harness/tools/workspace_api/`, bound to the run's `client_id` and scope; a missing
  `system_id` / `audit_id` argument defaults to the scope): `list_systems`, `list_system_files`,
  `read_system_file`, `list_audits`, `read_audit`, `read_audit_artifact` (the backend's `/v1/systems` and
  `/v1/audits` with the run's `X-Client-Id`), `lookup_provision`, `search_regulation` (reg-memory, pinned to
  the active `kb_version` read once per run), and two gated writes: `propose_system_note` (writes
  `proposed/{evidence,gaps}/<name>.md` into the system folder with `status: proposed`) and `start_audit`
  (`POST /v1/systems/{id}/audits`). Plus the platform's `present_artifact`, `render_chart`, the sandbox
  `execute` (always gated), and with a `system_id` the `/memory/` mount. No MCP tools (`all_mcp_tools:
  false`): answers come from the knowledge base.
- **Sub-agents:** `regulation-researcher` (only `lookup_provision` + `search_regulation`) and
  `evidence-analyst` (inherits every tool and gate). Delegation is not gated (`hitl.task: false`).
- **Prompt:** layered per the prompt-engineering plan: the precedence statement, `<platform_rules>`
  (HITL, cite with `kb_version`, no legal certainty, thresholds are the organisation's, no invented
  numbers) and `<agent_instructions>` in `AGENT.md`; then the platform defaults (harness sections), the
  `<user_context>` scope block, the memory index and the date.
- **Scoping:** a conversation started from a system or audit carries `context.system_id` / `audit_id`.
  The `scope` prompt section (`prompts/scope_prompt.py`) tells the agent what it is scoped to and to start
  there; the tools default to it. Unscoped, it is general AI Act Q&A and picks a system by name with
  `list_systems`.

## Tools and approvals

| Tool | Where from | Approval by default |
| --- | --- | --- |
| `ls`, `read_file`, `glob`, `grep`, `write_todos` | deepagents | no |
| `write_file`, `edit_file` | deepagents | yes (an agent's `hitl:` may clear it) |
| `execute` | deepagents, only with the sandbox on | **always** (locked) |
| `task` / `start_async_task` | deepagents (blocking / async sub-agents) | yes (one gate under two names) |
| `check_/update_/cancel_/list_async_tasks` | deepagents async sub-agents | no |
| `present_artifact`, `view_image`, `render_chart` | native (`harness/tools/`) | no |
| `remember` | native; only with `system_id` + `audit_id` in the context | no |
| `forget` | native; same | **yes** |
| `list_systems`, `list_system_files`, `read_system_file`, `list_audits`, `read_audit`, `read_audit_artifact`, `lookup_provision`, `search_regulation` | native, selected in `agent.yaml` ([chat agent](#the-chat-agent-mnamon-copilot)) | no |
| `propose_system_note`, `start_audit` | same | **yes** |
| `ask_user` | native; main agent of a chat run only | never (the call is the pause) |
| MCP gateway tools | `MCP_GATEWAY_URL` | per the agent's `hitl:` |

The merge (`harness/tools/gates.py`) is: builtin defaults, then the agent's
`hitl:`, then the locked gates, and `execute` forced once more by name. A
gateway tool named like a prebuilt tool is dropped, so no MCP tool can shadow
a gated one.

## MCP and the sandbox

- **MCP gateway** (sibling `mcp_gateway`): `MCP_GATEWAY_URL`, e.g.
  `http://mcp_gateway:8005/sse`. One SSE session per run; empty URL, or a
  gateway that does not finish its handshake within
  `MCP_CONNECT_TIMEOUT_SECONDS`, means the run goes on without MCP tools.
- **Sandbox runner** (`mnamon/sandbox`, compose `sandbox_runner`, [sandbox.md](sandbox.md)): `execute` exists only when
  `SANDBOX_EXECUTION_ENABLED=true` **and** `SANDBOX_RUNNER_URL` is set (e.g.
  `http://sandbox_runner:8090`). Each call is `POST /v1/exec` with
  `X-Internal-Proxy-Secret: <SANDBOX_RUNNER_SECRET>` (the runner's
  `TRUSTED_PROXY_SECRET`; unset means `INTERNAL_SERVICE_SECRET`). The
  conversation's `input/` and `output/` travel in the body; returned `output/`
  files are written back to `/conversation/output/`. A runner that is down is
  an error result for the model, never a fallback.

## Public dataset discovery

`harness/tools/public_datasets/` (pure Python + httpx; no LLM inside except an optional Gemini note) finds
public datasets that match an audited system before any synthetic data is made
([synthetic-data.md § 2a](../architecture/synthetic-data.md#2a-public-data-first-find_public_data)):

- `search_public_datasets(audit_id, plugin?)`: reads the system folder through the backend's internal API,
  queries OpenML, UCI, Hugging Face and (with `FIRECRAWL_API_KEY`) Firecrawl, scores every candidate against the
  plugin's `data-dictionary.yaml` and writes a `public_dataset_candidates` artifact (`status: proposed`).
- `fetch_public_dataset(audit_id, candidate_id)`: refuses unless that artifact is **approved** (and matches a
  human-set `data.selected`); downloads capped rows, drops PII columns and stores `datasets/public/<slug>/`
  through `PUT /internal/audits/{id}/datasets/public/{slug}/{file}` (`BACKEND_INTERNAL_URL`, default
  `http://backend:8000`, secret `INTERNAL_SERVICE_SECRET`).

`build_public_dataset_tools()` returns both as LangChain tools; the audit pipeline calls `run_search` /
`run_fetch` directly in its `find_public_data` node and gate. Local try-out: `python -m harness.tools.public_datasets search --system-dir <case> --out-dir <dir>`,
then `fetch --candidates <json> --id <id> --approved-by <who> --out-dir <dir>`. Tests:
`tests/agents/test_public_datasets.py` (mocked HTTP).

## Tracing

With `LANGFUSE_BASE_URL` and both keys set, each run gets a Langfuse
LangChain handler. When the request carries `config.trace`, the run's spans
are children of `parent_observation_id` in the backend's `trace_id`, with the
trace's `user_id` / `session_id`; async tasks nest under the run that started
them. Everything is masked (keys, tokens, e-mails, URL credentials) and
fail-open: a Langfuse outage costs traces, never a run.

## Environment

| Variable | Default | What |
| --- | --- | --- |
| `APP_ENV` | `development` | Anything but `development`/`test` requires `INTERNAL_SERVICE_SECRET` |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `console` | `json` for structured logs |
| `LOG_REDACTION_SECRET` | random per process | Keys the `h:` id hashes; use the backend's value |
| `GOOGLE_API_KEY` | | Gemini, the only provider; empty = a clear `RUN_ERROR` ([agents pipeline](agents-pipeline.md#model-access-gemini)) |
| `GEMINI_MODEL` / `GEMINI_MODEL_REASONING` | `gemini-3.5-flash-lite` / empty | Default and reasoning-role models |
| `GEMINI_THINKING_LEVEL` | empty (model default) | `minimal`/`low`/`medium`/`high` for the chat agents' Gemini models. Their thoughts are requested (`include_thoughts`) and shown as THINKING steps; `gemini-3.5-flash-lite` returns none, `gemini-3.5-flash` does |
| `REASONING_SUMMARY` | `auto` | `off` requests no thoughts from any model (Gemini thoughts, OpenAI summaries) |
| `AGENTS_FAKE_LLM` | `false` | Deterministic stub model for dry runs (the pipeline steps and every declarative agent) |
| `REG_MEMORY_URL`, `PIPELINE_*`, `CHANGE_JUDGE_MODEL`, `OUMI_*` | | The pipelines ([settings](agents-pipeline.md#pipeline-settings)) |
| `AGENT_RUNTIME_DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/agent_runtime` | psycopg conninfo; the database is created if missing |
| `LANGGRAPH_AES_KEY` | empty (plaintext) | 16, 24 or 32 **characters** (e.g. `openssl rand -hex 16`); encrypts checkpoints and files. Never change it once data exists |
| `INTERNAL_SERVICE_SECRET` | empty | The caller secret (see Routes) |
| `REDIS_URL` / `REDIS_PASSWORD` | `redis://redis:6379/0` / empty | Async-task streams |
| `ASYNC_SUBAGENTS_ENABLED` | `true` | Sub-agents as background tasks; `false` = blocking `task` |
| `MCP_GATEWAY_URL` | empty | MCP off when empty |
| `SANDBOX_EXECUTION_ENABLED` / `SANDBOX_RUNNER_URL` | `false` / empty | Both needed for `execute` |
| `SANDBOX_RUNNER_SECRET` | `INTERNAL_SERVICE_SECRET` | The runner's `TRUSTED_PROXY_SECRET` |
| `LANGFUSE_BASE_URL` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | empty | Tracing off unless all three are set |
| `DEFAULT_AGENT_SLUG` | `mnamon` | Marked `default` in `GET /agents` (the chat copilot) |
| `AGENTS_DIR` | the image's `definitions/` | Folder of `<slug>/agent.yaml` definitions |
| `AGENT_MODELS` | `google_genai:gemini-3.5-{flash-lite,flash,pro}` | JSON `{"provider:model": {"reasoning": bool, "context_window": int}}` |
| `OUTPUT_MAX_FILE_BYTES` / `OUTPUT_MAX_FILES` | 26214400 / 20 | Presented bytes per file / per run |
| `CONVERSATION_FILE_MAX_BYTES` | 104857600 | One stored file |
| `MEMORY_MAX_ENTRIES_PER_SYSTEM` | 200 | New memory entries per audited system (updates always allowed) |

Every secret also accepts `<NAME>_FILE`. Tuning knobs not listed (pool sizes,
timeouts, summarization thresholds, rate-limit retry, `ASYNC_TASKS_*`) are in
`core/settings.py`.

## Adding an agent

A folder `mnamon/agents/definitions/<agent-name>/` (the folder name is the slug;
set `DEFAULT_AGENT_SLUG` to it) with:

- `agent.yaml`: `id`, `slug`, `name`, `version`, `type: deep_agent`,
  `description`, `icon`, `prompt: ./AGENT.md`, `model: {main: google_genai:<model>}`
  (or `google_genai:${GEMINI_MODEL}`),
  `tools` (`{native: render_chart}` or `{server_id: tavily, tool_name: tavily-search}`),
  `all_mcp_tools`, `subagents` (name, description, prompt, optional model and
  tool subset, nested `subagents` up to 3 levels), `hitl` (`tool: true|false`;
  `execute` cannot be false).
- `AGENT.md` and the sub-agent prompts; any other notes are readable by the
  agent at `/reference/`.

Rebuild the `agents` image to pick it up (definitions are read at boot). A
working example is the test fixture `tests/agents/fixtures/agents/assistant/`
(a deep agent with two sub-agents). An invalid definition is logged and skipped at boot. A Python agent (a
`DeepAgent` or `LangGraphAgent` subclass) is registered in
`utils/agents.py::PYTHON_AGENTS`.

## Tests and checks

From the repo root (the suite needs the service's own venv):

```bash
mnamon/agents/.venv/Scripts/python -m pytest tests/agents -q   # no network, no Postgres, fake models
uv run ruff format mnamon/agents tests/agents
uv run ruff check mnamon/agents tests/agents
```

`tests/agents/conftest.py` puts `mnamon/agents` on `sys.path`, restores the
settings tree around every test and wires a stub `agent_runtime` pool;
`MemoryFileStore` is the in-memory twin of the conversation-files store.
