# Backend → agents service contract

The backend never calls a model. It starts runs on the **agents service**, reads
their **AG-UI event stream** (SSE), stores it and fans it out to browsers. This page
is what the agents service must implement. The client side is
[`product/backend/utils/agents.py`](../../product/backend/utils/agents.py) (its docstring repeats
this contract) and the run engine is
[`product/backend/utils/inference_runs.py`](../../product/backend/utils/inference_runs.py).

## Endpoints

Base URL: `AGENTS_SERVICE_URL` (default `http://agents:8003`). `{slug}` is the
conversation's agent (`^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$`, URL-quoted). The backend
has no agent catalog: the agents service decides whether a slug exists.

| Method | Path | Purpose | Response |
| --- | --- | --- | --- |
| `POST` | `/agents/{slug}/stream` | Start a run | `200 text/event-stream` |
| `POST` | `/agents/{slug}/resume` | Resume a run paused on HITL interrupt(s) | `200 text/event-stream`, same framing as `/stream` |

The audit pipeline adds four internal routes (same secret header, JSON, answered at once; the pipeline runs
in the background and reports through the backend's internal API):

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| `POST` | `/audits/{audit_id}/run` | `{"system_id", "trigger"?, "client_id"?, "trace"?}` | `202 {audit_id, thread_id, status: started\|resumed}`; `409` while running or waiting at a gate (`detail.pending_gates`) |
| `POST` | `/audits/{audit_id}/resume` | `{"system_id", "gate": public_data\|scenarios\|datasets, "decision": approved\|rejected\|changes_requested, "reasonCategory", "comment", "edits", "artifactId", "decidedBy"}` (the backend's `utils/audit_pipeline.py` `resume_body`) | `202`; `409` when not waiting at `gate` |
| `GET` | `/audits/{audit_id}/state?system_id=` | | `{next, pending_gate, status, stage_artifacts}` |
| `POST` | `/changes/{change_id}/judge` | `{"system_ids"?, "rerun"?, "change"?}` | `{change_id, kb_version, impacted_requirements, judgements: [...]}`; also writes `PUT /internal/regulation/changes/{id}/judgement` on the backend |

Details: [agents pipeline](../services/agents-pipeline.md).

### Headers (both endpoints)

| Header | Value |
| --- | --- |
| `Content-Type` | `application/json` |
| `Accept` | `text/event-stream` |
| `X-Request-Id` | The browser request's id, when there is one (log correlation) |
| `X-Internal-Service-Secret` | Only when `AGENTS_SERVICE_SECRET` is set. The agents service should reject requests without it when it is configured. |

## `/stream` request

```json
{
  "messages": [Message, ...],
  "config": Config
}
```

### `Config` (also sent on every `/resume`)

```json
{
  "run_config": {"configurable": {"thread_id": "<branch thread id>"}},
  "context": {
    "client_id": "<anonymous browser id>",
    "conversation_id": "<conversation id>",
    "run_id": "<run id = assistant message id>",
    "system_id": "SYS-001",
    "audit_id": "<audit id>",
    "step": "plan_tests"
  },
  "fork_from": {"thread_id": "...", "checkpoint_id": "..."},
  "trace": {
    "trace_id": "<32 hex>",
    "parent_observation_id": "<16 hex>",
    "traceparent": "00-<trace_id>-<parent_observation_id>-01",
    "user_id": "h:<16 hex>",
    "session_id": "<conversation id>"
  }
}
```

| Field | Meaning |
| --- | --- |
| `thread_id` | Key of the agent's durable checkpointer. One thread per conversation **branch**: a `send` continues its branch's thread; an edit, a retry and a new conversation each get a new one. |
| `messages` | Only the new user message when the thread already has committed state (**delta resume**), or when `fork_from` is present (**delta fork**). Otherwise the whole branch history (**full seed**), oldest first. |
| `fork_from` | Optional. Copy checkpoint `checkpoint_id` of thread `thread_id` into the new `thread_id`, then run. Ignored by `/resume`. |
| `context.client_id` | The anonymous browser id (`X-Client-Id`). It scopes a browser's data and is **not** authentication. Treat it as sensitive: do not log or trace it raw. |
| `context.system_id` | Optional. The audited system the run works on (`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`). Turns on the system's agent memory: the `/memory/` mount, the `MEMORY.md` index in every prompt, and `remember` / `forget` ([agents service § Memory](../services/agents-service.md#memory)). Absent = a plain chat run, unchanged. A malformed value is `400`. |
| `context.audit_id` | Optional, needs `system_id` (same id format). The audit `remember` records into (`/memory/audits/<audit_id>/`). Without it the memory is read-only and the memory tools are absent. |
| `context.step` | Optional, ≤ 64 chars: the pipeline step (`plan_scenarios`, `critic`, ...), stored as provenance on each entry and shown in `MEMORY.md`. When a human rejected the previous attempt at a gate, start the redo with the same `step` and put the reviewer's reason in the user message; the agent records the lesson with `remember`. |
| `trace` | Present only when Langfuse is on in the backend. Create the run's spans as children of `parent_observation_id` in trace `trace_id` (Langfuse SDK: `trace_context={"trace_id": ..., "parent_span_id": ...}`), or use `traceparent` with any W3C propagator. Set `user_id` / `session_id` as the trace attributes. |

### `Message`

```json
{
  "id": "<message id>",
  "role": "user" | "assistant",
  "content": "plain text" | [Part, ...],
  "attachments": [Attachment, ...]
}
```

`Part` is `{"type": "text", "text": "..."}` or, for images (inline so a vision
model sees them),
`{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<data>", "detail": "auto"}}`.
When a message has other files, a text part `Attachments:\n- name (mime)` names them.

`Attachment` (every non-image file, and images that did not fit the budget):

```json
{
  "id": "...", "name": "report.pdf", "mime_type": "application/pdf",
  "size_bytes": 12345, "sha256": "<hex>", "origin": "upload" | "generated",
  "data_base64": "<base64>" | null,
  "omitted": "budget"
}
```

Bytes are inline because the agents service has no route back to the backend's
blobs. Limits: at most `ATTACHMENT_MAX_SIZE_BYTES` per file and
`ATTACHMENT_MAX_TOTAL_BYTES` per request (both 25 MB by default). A file past the
budget comes with `data_base64: null` and `"omitted": "budget"`.

## `/resume` request

```json
{
  "config": Config,
  "thread_id": "<branch thread id>",
  "interrupt_id": "...",
  "decision": "approve" | "reject",
  "reason": "string" | null,
  "value": any | null,
  "decisions": [{"decision": "approve" | "reject", "reason": "..." | null}] | null,
  "resumes": [ResumeItem, ...]
}
```

- The top-level decision fields carry the first decision.
- `resumes` is present only when several pending interrupts are answered at once. Each item has the same fields keyed by `interrupt_id`; apply them together, e.g. `Command(resume={interrupt_id: value, ...})`. When present, it is the whole request.
- `decisions` is the per-action list of one batched interrupt, index-aligned to its `action_requests`.
- `value` carries structured answers, e.g. an `ask_user` reply's `{"answers": [...]}`.
- If some named interrupts are no longer pending, answer **409** with this body, and apply nothing:
  `{"detail": {"stale_interrupt_ids": [...], "pending_interrupt_ids": [...]}}`.
  The backend voids the stale decisions and re-sends the others. Any other 409 means "no paused checkpoint" and fails the run.

## Response: AG-UI over SSE

`text/event-stream`: `data: <one AG-UI event as JSON>` frames separated by a blank
line (CRLF accepted; `:` comment lines and non-JSON frames are ignored). Each event is
an object with a `type`.

| Event | What the backend does |
| --- | --- |
| `RUN_STARTED`, `RUN_FINISHED`, `TEXT_MESSAGE_START/END` | Stored and relayed. |
| `TEXT_MESSAGE_CHUNK` / `TEXT_MESSAGE_CONTENT` (`messageId`, `delta`) | Builds the answer text. Consecutive deltas of one message are merged in storage. |
| `THINKING_START`, `THINKING_TEXT_MESSAGE_CONTENT` (`delta`), `THINKING_END` | Reasoning steps and their duration. Each content event is one step and is never merged. |
| `TOOL_CALL_START` (`toolCallId`, `toolCallName`), `TOOL_CALL_ARGS` (`delta`), `TOOL_CALL_END` | Stored and relayed. Args deltas are merged per call. |
| `TOOL_CALL_RESULT` (`content`) | Content longer than `INFERENCE_TOOL_RESULT_MAX_CHARS` (16 000) is cut and flagged `"truncated": true`, unless it contains `preview_base64`. |
| `RUN_ERROR` (`message`) | Fails the run, with `message` as its error. Send nothing after it. |
| `CUSTOM HITL_INTERRUPT` (`value.interrupt.id`) | Pauses the run. When the stream ends, the backend waits for decisions and calls `/resume`. The interrupt `id` is required for answering approvals in parallel. |
| `CUSTOM SUBAGENT_EVENT` (`value.task_id`, `value.event`) | A sub-agent's event, wrapped. An inner `HITL_INTERRUPT` pauses the run too (deduplicated by id). An inner `TOOL_CALL_RESULT` is truncated the same way. |
| `CUSTOM CHECKPOINT_COMMITTED` (`value.thread_id`, `value.checkpoint_id`) | Send it once the durable checkpoint is written, before the stream ends. The backend stores `checkpoint_id` on the answer: the next turn resumes from it, and a later edit forks from it. It is never sent to browsers. |
| `CUSTOM PRESENT_ARTIFACT` (`value.artifact_id`, `path`, `filename`, `mime`, `title`, `summary`, `size`, optional `data_base64`; sent by the agents service once the file was read, orchestrator only) | Relayed as a card. With `data_base64`, the bytes are stored as a **generated attachment** of the answer when the run ends, and stripped from the relayed and stored event. Bounded by the same attachment limits. |
| Anything else (`PLAN_SNAPSHOT`, `TASK_SUBAGENT`, `RENDER_CHART`, …) | Stored and relayed untouched. |

The stream ending without `RUN_ERROR` and without a pending interrupt completes the run.

### Errors

| Upstream answer | Run error shown to the user |
| --- | --- |
| `404` on `/stream` | "This agent is not available." |
| Other `4xx`/`5xx` on `/stream` | "The agents service refused the run (`<status>`)." |
| Connection failure or broken stream | "The agents service could not be reached." |
| `409` (not stale) on `/resume` | "The agent has no paused checkpoint for this run. Start a new message instead." |

### Cancel

When a user cancels, the backend closes the HTTP stream. The agents service should
treat a client disconnect as "stop the run".

## Async sub-agents

With `ASYNC_SUBAGENTS_ENABLED` (default on) every sub-agent of an agent runs as a
**background task** in the agents service. The orchestrator calls
`start_async_task`, gets a task id back at once, and its run ends; the task keeps
working on its own LangGraph thread (`task_id` = thread id) while the user chats.
Tasks nest up to depth 3. When a depth-1 task's whole subtree has settled, the
backend **wakes** the orchestrator with a notification. The agents service owns
the tasks (tables `async_tasks` / `async_task_runs`) and runs them; the backend
mirrors them for the UI, relays their events and does the wake-ups.

```text
agents ──XADD──► tasks:status · tasks:outbox · task:{id}:events ──XREADGROUP──► backend
backend ──HTTP──► POST /agents/{slug}/stream (wake-up run) · /tasks/... (internal task API)
```

Redis is the **doorbell, never the record**: a failed write is logged and the run
goes on; `GET /tasks/unnotified` rebuilds the outbox from the rows. Every task
belongs to the anonymous `client_id` and the `conversation_id` of the run that
started its tree. `client_id` travels raw in the streams and the task API (the
backend needs it to check ownership) and is never logged or traced raw
(`h:<16 hex>` only).

### Redis streams

Written by the agents service with `XADD ... MAXLEN ~ n`. Every entry has one
field, `data`, holding JSON (datetimes as ISO 8601). The agents service never
creates consumer groups: the group (`XGROUP CREATE <stream> <group> $ MKSTREAM`),
its name and its consumer names are the backend's.

| Stream | Entry (`data`) | When | Cap |
| --- | --- | --- | --- |
| `tasks:status` | `{"event": "TASK_STARTED" \| "TASK_STATUS" \| "TASK_SETTLED", "task": TaskOut}` | `TASK_STARTED` at creation. `TASK_STATUS` on every non-settled change, including a settled task being **reopened** (clear the mirrored settle and `notified_at`). `TASK_SETTLED` on settle, and once more when a stopped task's run reports its final usage (book only the delta). | `ASYNC_TASKS_STREAMS_MAXLEN` (10 000) |
| `tasks:outbox` | `OutboxItem` | A depth-1 task's subtree settled and the orchestrator has not been told. | same |
| `task:{task_id}:events` | One AG-UI event, exactly as a top-level run's SSE `data:`, plus `CUSTOM TASK_INPUT {"text"}` where a follow-up's run begins | Every event of every run of the task | `ASYNC_TASKS_EVENTS_MAXLEN` (20 000). `EXPIRE ASYNC_TASKS_EVENTS_TTL_SECONDS` (3 600) after settle, `PERSIST` on reopen. |

Delivery is at least once: handle an entry idempotently, `XACK` it once handled,
leave it pending on a database or Redis failure, and ack and log a malformed one.

A task paused on an approval emits `CUSTOM HITL_INTERRUPT` in its own
`task:{id}:events` stream (task events are never wrapped in `SUBAGENT_EVENT`);
`value.interrupt.id` is the key the answer goes under in `/tasks/{id}/resume`.

### `TaskOut`

```json
{
  "task_id": "<uuid>",
  "conversation_id": "...",
  "client_id": "<anonymous client id>",
  "parent_task_id": "<uuid>" | null,
  "root_run_id": "<run id of the turn that started the tree>",
  "branch_thread_id": "<orchestrator branch thread>",
  "spawned_by_message_id": "<same as root_run_id>",
  "depth": 1,
  "name": "researcher",
  "subagent_path": "researcher/helper",
  "description": "<the task text, at most 2000 chars>" | null,
  "model": "<model the calls went to>" | null,
  "status": "pending" | "running" | "waiting_children" | "waiting" | "success" | "error" | "cancelled",
  "result_preview": "<at most 2000 chars>" | null,
  "error": "<short, internals-free>" | null,
  "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
            "reasoning_tokens": 0, "calls": 0, "model_latency_ms": 0},
  "started_at": "<ISO 8601>",
  "settled_at": "<ISO 8601>" | null
}
```

| Status | Meaning |
| --- | --- |
| `pending`, `running` | Its run has not started / is running. |
| `waiting_children` | Its own run ended, a descendant has not settled. |
| `waiting` | Paused on an approval; answered through `POST /tasks/{id}/resume`. |
| `success`, `error`, `cancelled` | **Settled.** |

`root_run_id` is the backend's run id (`config.context.run_id`) of the
orchestrator turn that started the tree; book the task's usage on that answer.
`usage` sums every run of the task.

### `OutboxItem` and the notification message

```json
{
  "task_id": "...",
  "client_id": "...",
  "conversation_id": "...",
  "branch_thread_id": "...",
  "root_run_id": "...",
  "agent_slug": "...",
  "interactive": true,
  "status": "success" | "error" | "cancelled",
  "cancelled_by_user": false,
  "notification": {"content": [Part, ...], "additional_kwargs": {...}}
}
```

`notification` is deepagents' task notification. `content` is text parts: a
"this is not a message from the user" note,
`<task-notification><task-id>…</task-id><agent-name>…</agent-name><status>…</status>`,
then `<result>…</result>` (success) or `<details>{"error": "The subagent failed."}</details>`
(error), and a closing instruction. `additional_kwargs` has exactly three keys,
which the orchestrator's middleware uses to record the task as reported, so it is
never reported twice:

```json
{
  "lc_source": "async_subagent",
  "lc_data": {"task_id": "...", "agent_name": "researcher", "status": "success", "run_id": "..."},
  "deepagents_notification": {"task_id": "...", "agent_name": "researcher", "status": "success", "run_id": "..."}
}
```

### Wake-up flow (backend side)

For each `OutboxItem` (from `tasks:outbox`, the run-end hook, or the reconcile
loop over `GET /tasks/unnotified`):

1. `cancelled_by_user: true`: skip (the user stopped it and knows), then mark it notified.
2. The conversation must still exist and belong to `client_id`, and the branch
   (`branch_thread_id`) and the agent must still be there. Otherwise skip and mark notified.
3. Persist a **notice row** after the newest answer of `branch_thread_id`: a
   user-side message with `kind = "task_notification"`, the notification's
   `content`, and its `additional_kwargs` kept server side (never sent to browsers).
4. Start an ordinary send run on that branch's thread (`POST /agents/{slug}/stream`,
   delta resume). The notice goes into `messages` as
   `{"id", "role": "user", "content": [Part, ...], "kind": "task_notification", "additional_kwargs": {...}}`;
   a full seed sends every earlier notice row the same way. The agents service
   turns such a message back into the exact `HumanMessage`, keeping only the
   three `additional_kwargs` keys.
5. Once the run exists, `POST /tasks/{task_id}/notified`. **Never** on 409 (a run
   is already active and pulls the result itself) or 429: an unnotified task is
   what the safety nets (run end, reconcile) look for.

A result the orchestrator pulled during an active run (its middleware reads
settled tasks before every model call, and on `check_async_task` /
`list_async_tasks`) is marked notified by the agents service itself, so it no
longer appears in `/tasks/unnotified`.

### Internal task API

Every route needs `X-Internal-Service-Secret`, like `/stream`. The `client_id`
in each request is checked against the task row: a mismatch or an unknown id is
**404**. JSON bodies. With async sub-agents off, `/tasks/unnotified` answers
`[]`, `/tasks/cancel-scope` answers `{"cancelled": 0}`, and the others **503**.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/tasks/{task_id}?client_id=` | | `TaskOut` |
| `GET` | `/tasks?client_id=&conversation_id=&limit=` | `limit` 1–500, default 200 | `[TaskOut]`, oldest first |
| `GET` | `/tasks/unnotified?limit=&client_id=&conversation_id=` | `limit` 1–1000, default 100; both filters optional | `[OutboxItem]`, oldest settle first |
| `POST` | `/tasks/{task_id}/notified` | `{"client_id": "..."}` | `204` |
| `POST` | `/tasks/{task_id}/cancel` | `{"client_id": "...", "reason": "user"}` | `TaskOut`. Stops the whole subtree; the outbox item says `cancelled_by_user`. |
| `POST` | `/tasks/{task_id}/resume` | `{"client_id": "...", "decisions": {"<interrupt_id>": {"decision": "approve" \| "reject", "reason": "..." \| null, "value": any \| null, "decisions": [...] \| null}}}` (1–64 entries) | `TaskOut`. 409: not `waiting`, or a stale interrupt id; 422: wrong per-action decision count; 429: run cap. |
| `POST` | `/tasks/cancel-scope` | `{"client_id": "...", "conversation_id": "..." \| null, "root_run_id": "..." \| null}` | `{"cancelled": n}`: every depth-1 task in scope with its subtree. Conversation delete sends `client_id` + `conversation_id`. |

### Caps (fail closed: the model reads a tool error)

| Cap | Setting | Default |
| --- | --- | --- |
| Unsettled tasks per client | `ASYNC_TASKS_MAX_ACTIVE_PER_USER` | 16 |
| Open children per parent | `ASYNC_TASKS_MAX_CHILDREN_PER_TASK` | 8 |
| One run's duration (then `error`) | `ASYNC_TASKS_RUN_TIMEOUT_SECONDS` | 1800 |
| Runs per task | `ASYNC_TASKS_MAX_RUNS_PER_TASK` | 50 |
| Depth | | 3 |

### Inside the agents service (for reference)

- **`/ap`**: the six Agent Protocol calls deepagents' `AsyncSubAgentMiddleware`
  makes (`POST /ap/threads`, `GET /ap/threads/{id}`, `POST`/`GET /ap/threads/{id}/runs`,
  `GET /ap/threads/{id}/runs/{run_id}`, `POST /ap/threads/{id}/runs/{run_id}/cancel`).
  Served **in process** (an ASGI transport onto the app, never the network); not
  for the backend.
- **Signed launch token** (`X-Task-Launch-Token`): who is calling `/ap`, never
  read from a body. `base64url(zlib(json claims)) "." base64url(HMAC-SHA256)`, keyed
  by `ASYNC_TASKS_LAUNCH_SECRET` or, unset, a key derived from
  `INTERNAL_SERVICE_SECRET` under a domain label; TTL
  `ASYNC_TASKS_LAUNCH_TOKEN_TTL_SECONDS` (7200). Claims: `client_id`,
  `conversation_id`, `root_run_id`, `branch_thread_id`, the caller's task (none
  for the orchestrator), its depth and path, the agent slug and definition
  version, and what children inherit (`interactive`, the Langfuse `trace`). Every
  call on a task is authorised against its row (same client, conversation, agent
  and version, and the caller is the task's parent); anything else is a 404.
- **Shared files.** A task run's context carries the root's `branch_thread_id`,
  so the whole tree reads and writes the orchestrator's branch scratch files.
- **Tracing.** The spawning run's `config.trace` rides the token into the task
  row, and every task run is built with it as its `config.trace`: its spans nest
  under the trace of the run that spawned the tree (fail-open).
- **Restart.** No run survives a restart. At startup every cut run becomes
  `error("interrupted by restart")` and its task settles as `error` (an outbox
  item at depth 1). The orchestrator may continue it with `update_async_task`,
  which reopens it on the same thread. A `waiting` task stays waiting.
