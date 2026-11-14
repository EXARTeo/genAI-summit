# Agents service

`product/agents/` runs the agents and streams their work to the backend as
AG-UI events over SSE. It implements [the backend contract](../contracts/agents-contract.md)
exactly; this page is how it is built inside. Port **8003**, FastAPI, OpenAI
models through LangChain/deepagents, durable state in the `agent_runtime`
Postgres database.

> Hackathon rule: this is the runtime only. **No agent ships with it**: the
> product agent is written after kickoff as `product/agents/definitions/<agent-name>/`
> (see [Adding an agent](#adding-an-agent)), and the harness is customised to fit
> the idea. Until then `GET /agents` is `[]` and a run answers 404.

## Routes

| Method | Path | Auth | What |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Liveness (`{"status": "ok"}`), no I/O |
| `GET` | `/agents` | secret | The agents this service runs (manifest list, `default: true` on `DEFAULT_AGENT_SLUG`), so a UI can pick one |
| `POST` | `/agents/{slug}/stream` | secret | Start a run (contract § `/stream`) |
| `POST` | `/agents/{slug}/resume` | secret | Resume a run paused on HITL interrupt(s) (contract § `/resume`) |
| `*` | `/ap/...` | secret + launch token | The Agent Protocol the async sub-agents call, in process |
| `*` | `/tasks/...` | secret | The backend's internal task API (async sub-agents) |

"Secret" is `X-Internal-Service-Secret` equal to `INTERNAL_SERVICE_SECRET`
(the backend sends its `AGENTS_SERVICE_SECRET`, the same value). Missing or
wrong is `403`. With no secret configured every caller is accepted, which the
settings allow only for `APP_ENV=development|test`; anywhere else the service
refuses to start without one.

## Structure

```text
product/agents/
  main.py              app, lifespan (Langfuse, agent_runtime + checkpointer, TaskRunner), /health
  router/              thin HTTP: inference (stream/resume), catalog (GET /agents),
                       agent_protocol + tasks (async sub-agents)
  utils/               endpoint logic: inference (the run), agents (registry), mcp_tools,
                       hitl_resume (the resume Command), checkpointer (head + bindings),
                       declarative (YAML helpers), async_tasks
  schema/              DTOs, one module per concept (import the leaf module)
  definitions/         the product's agent definitions, one folder per agent (empty for now)
  core/                settings, logging (hashed ids), security (internal secret), error_handling
  harness/
    abstractions/      BaseAgent, DeepAgent, LangGraphAgent, AgentSpec, YamlDeepAgent
    agui/              emitter, normalizer (LangGraph chunks -> AG-UI), keepalive, previews
    async_tasks/       background sub-agents: runner, store, token, specs, middleware
    checkpointer/      agent_runtime pool + AsyncPostgresSaver, fork seeding
    conversation_files/ a conversation's files as encrypted rows, uploads ingest
    filesystem/        the run's mount table, branch scratch, sandbox backend
    middlewares/       tool errors, summarization (compaction), rate-limit retry
    models/            reasoning summaries for OpenAI reasoning models
    observability/     Langfuse (opt-in, fail-open), nested under the backend's trace
    prompt_engineering/ the composed system prompt, one module per section
    tools/             ask_user, present_artifact, view_image, render_chart; gates, registry
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

## Tools and approvals

| Tool | Where from | Approval by default |
| --- | --- | --- |
| `ls`, `read_file`, `glob`, `grep`, `write_todos` | deepagents | no |
| `write_file`, `edit_file` | deepagents | yes (an agent's `hitl:` may clear it) |
| `execute` | deepagents, only with the sandbox on | **always** (locked) |
| `task` / `start_async_task` | deepagents (blocking / async sub-agents) | yes (one gate under two names) |
| `check_/update_/cancel_/list_async_tasks` | deepagents async sub-agents | no |
| `present_artifact`, `view_image`, `render_chart` | native (`harness/tools/`) | no |
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
- **Sandbox runner** (sibling `sandbox`): `execute` exists only when
  `SANDBOX_EXECUTION_ENABLED=true` **and** `SANDBOX_RUNNER_URL` is set (e.g.
  `http://sandbox_runner:8090`). Each call is `POST /v1/exec` with
  `X-Internal-Proxy-Secret: <SANDBOX_RUNNER_SECRET>` (the runner's
  `TRUSTED_PROXY_SECRET`; unset means `INTERNAL_SERVICE_SECRET`). The
  conversation's `input/` and `output/` travel in the body; returned `output/`
  files are written back to `/conversation/output/`. A runner that is down is
  an error result for the model, never a fallback.

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
| `OPENAI_API_KEY` | | The models |
| `AGENT_RUNTIME_DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/agent_runtime` | psycopg conninfo; the database is created if missing |
| `LANGGRAPH_AES_KEY` | empty (plaintext) | 16, 24 or 32 **characters** (e.g. `openssl rand -hex 16`); encrypts checkpoints and files. Never change it once data exists |
| `INTERNAL_SERVICE_SECRET` | empty | The caller secret (see Routes) |
| `REDIS_URL` / `REDIS_PASSWORD` | `redis://redis:6379/0` / empty | Async-task streams |
| `ASYNC_SUBAGENTS_ENABLED` | `true` | Sub-agents as background tasks; `false` = blocking `task` |
| `MCP_GATEWAY_URL` | empty | MCP off when empty |
| `SANDBOX_EXECUTION_ENABLED` / `SANDBOX_RUNNER_URL` | `false` / empty | Both needed for `execute` |
| `SANDBOX_RUNNER_SECRET` | `INTERNAL_SERVICE_SECRET` | The runner's `TRUSTED_PROXY_SECRET` |
| `LANGFUSE_BASE_URL` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | empty | Tracing off unless all three are set |
| `DEFAULT_AGENT_SLUG` | none | Marked `default` in `GET /agents` (set it to the product agent's slug) |
| `AGENTS_DIR` | the image's `definitions/` | Folder of `<slug>/agent.yaml` definitions |
| `AGENT_MODELS` | gpt-6-luna, gpt-5, gpt-4o(-mini) | JSON `{"provider:model": {"reasoning": bool, "context_window": int}}` |
| `OUTPUT_MAX_FILE_BYTES` / `OUTPUT_MAX_FILES` | 26214400 / 20 | Presented bytes per file / per run |
| `CONVERSATION_FILE_MAX_BYTES` | 104857600 | One stored file |

Every secret also accepts `<NAME>_FILE`. Tuning knobs not listed (pool sizes,
timeouts, summarization thresholds, rate-limit retry, `ASYNC_TASKS_*`) are in
`core/settings.py`.

## Adding an agent

A folder `product/agents/definitions/<agent-name>/` (the folder name is the slug;
set `DEFAULT_AGENT_SLUG` to it) with:

- `agent.yaml`: `id`, `slug`, `name`, `version`, `type: deep_agent`,
  `description`, `icon`, `prompt: ./AGENT.md`, `model: {main: openai:<model>}`,
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
product/agents/.venv/Scripts/python -m pytest tests/agents -q   # no network, no Postgres, fake models
uv run ruff format product/agents tests/agents
uv run ruff check product/agents tests/agents
```

`tests/agents/conftest.py` puts `product/agents` on `sys.path`, restores the
settings tree around every test and wires a stub `agent_runtime` pool;
`MemoryFileStore` is the in-memory twin of the conversation-files store.
