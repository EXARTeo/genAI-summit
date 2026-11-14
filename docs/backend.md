# Backend: async sub-agents

The agents service runs every sub-agent as a **background task** and announces it on
Redis streams (protocol: [agents-contract.md § Async sub-agents](agents-contract.md#async-sub-agents)).
The backend's half:

- **mirrors** the tasks into `conversation_tasks` for the UI;
- **relays** their events to the browser;
- **wakes** the orchestrator when a depth-1 task's subtree settles;
- **sends** the composer's queued message when a run ends.

No login: everything is scoped by the anonymous `client_id`, and every miss is a 404
(a WebSocket closes 4404).

```text
agents ──XADD──► tasks:status · tasks:outbox · task:{id}:events
                       │ XREADGROUP (group "backend")
backend ──► conversation_tasks · messages (notice rows) ──► conversation channel ──► browser
backend ──HTTP──► POST /agents/{slug}/stream (wake-up run) · /tasks/... (internal task API)
```

## Files

| File | What it does |
| --- | --- |
| `utils/task_streams.py` | Redis access to the three task streams. Consumer group `backend`; consumer name `ASYNC_TASKS_CONSUMER_NAME`, else the host name. |
| `utils/task_consumers.py` | The lifespan loops: status consumer, outbox consumer, reconcile loop. |
| `utils/async_tasks.py` | The mirror (`apply_status_entry`), the routes' logic (list, stop, approve) and the drill-down frames. |
| `utils/task_wakeups.py` | The wake-up (`handle_outbox_item`), the run-finished hook, `reconcile_once`. |
| `utils/agents_tasks.py` | The client for the agents service's internal `/tasks` API. |
| `utils/websockets.py` | The lifecycle every socket shares: Origin, caller, connect rate, `subscribe`, pump. |
| `router/tasks.py` | The task routes and the drill-down socket. |
| `schema/tasks.py` | `TaskOut`, `TaskStatusEntry`, `OutboxItem`, `TaskResumeIn`, `TaskFrame`. |

## Routes

| Method | Path | Purpose | Rate limit |
| --- | --- | --- | --- |
| `GET` | `/v1/conversations/{id}/tasks?limit=` | The task tree from the mirror, parents before children. `limit` is capped at `ASYNC_TASKS_LIST_LIMIT_MAX`. | `task_read_rate_limit` |
| `GET` | `/v1/tasks/active-conversations` | `{"conversationIds": [...]}`: the caller's conversations whose tasks still work (sidebar poll). | `task_read_rate_limit` |
| `POST` | `/v1/tasks/{task_id}/cancel` | Stop: proxied as `POST /tasks/{id}/cancel {"client_id", "reason": "user"}`. Stops the subtree and never wakes the orchestrator. | `task_mutate_rate_limit` |
| `POST` | `/v1/tasks/{task_id}/resume` | Approval for a `waiting` task: the run-resume body with `interruptId` required, proxied as `{"client_id", "decisions": {interruptId: item}}`. Also writes a `BRIDGE_HITL_RESOLVED` marker into `task:{id}:events`. | `task_mutate_rate_limit` |
| `WS` | `/v1/tasks/{task_id}/ws?client_id=` | The drill-down socket. | WS connect limit |
| `WS` | `/v1/inference/conversations/{id}/ws?client_id=` | The conversation channel. It now carries `task` frames too. | WS connect limit |

The task limits are `TASK_READ_RATE_LIMIT_*` (120/min) and `TASK_MUTATE_RATE_LIMIT_*`
(30/min). A task that is not yet in the mirror is authorised through
`GET /tasks/{id}?client_id=`, and its conversation must also be the caller's.
Upstream answers keep their status: 404, 409, 422 and 429 pass through, and a
transport failure or 5xx becomes 502.

`TaskOut` never carries `client_id` to the browser.

## Frames

**Conversation channel.** One Redis stream per conversation. Every frame has its `seq`;
send it back as `since` after a reconnect.

| Frame | When |
| --- | --- |
| `{"type": "queue", "queued_message"}` | Always first (from the database), then on every change of the slot. |
| `{"type": "task", "event": "TASK_STARTED" \| "TASK_STATUS" \| "TASK_SETTLED", "task": TaskOut}` | Every mirrored status entry. |
| `{"type": "run_started", "run": InferenceRunOut, "from_queue": bool}` | A run the browser did not start: a wake-up (`from_queue: false`) or the queued message being sent. Attach through the run socket. |

**Drill-down socket.** The first client frame is `{"type": "subscribe", "since"?}`. Then:

| Frame | Meaning |
| --- | --- |
| `{"type": "snapshot", "task", "events"?}` | The task. `events` (the stored, coalesced log) comes only for a settled task with no `since`, followed at once by `terminal`. |
| `{"type": "event", "seq", "event"}` | One entry of `task:{id}:events`; `seq` is its stream id. |
| `{"type": "terminal", "status"}` | The task has settled and the stream is drained. |

## Messages and conversations

| Field | Where | Meaning |
| --- | --- | --- |
| `kind` | `MessageOut` | `"task_notification"` on a notice row, else null. Sender stays `user` (it is the orchestrator's input); the UI renders it as a compact notice. |
| `taskNotice` | `MessageOut` | `{task_id, name, status, duration_ms}`. The stored `task_notice` also keeps `agent_kwargs` and `agent_content` for the agents service; those never leave the backend. |
| `hasActiveTasks` | conversation summary and detail | A task of the conversation has not settled: the row spins like a streaming answer. |
| `activeTaskMessageId` | conversation detail | The answer that started the newest working task: open the conversation on its branch. |

A fork copies the notice rows. A conversation delete first calls
`POST /tasks/cancel-scope {"client_id", "conversation_id"}` (best effort, and only when
the conversation has tasks), then deletes the mirror rows in the same transaction.

## The mirror

Each `tasks:status` entry is upserted into `conversation_tasks`.

- **Ownership.** An entry whose conversation does not exist, or whose conversation
  belongs to another `client_id`, is dropped and never stored. A task id never moves
  between conversations.
- **Settle.** When a task settles, `task:{id}:events` is read into `raw_events`,
  coalesced and seq-stamped like a run's log and capped at `ASYNC_TASKS_RAW_EVENTS_MAX`
  behind a `TASK_EVENTS_TRUNCATED` marker. Then the `task` frame is published.
- **`notified_at`.** A non-settled entry (a reopened task) clears it, and so does a
  settle newer than the last handling. A re-announced settle with the same
  `settled_at` stays handled.
- **Delivery.** At least once. A handled entry is acked. A database or Redis failure
  leaves the entry pending, to be read again on the next pending pass (every
  `ASYNC_TASKS_CLAIM_IDLE_MS`). Entries a dead replica left pending are taken over
  with `XAUTOCLAIM`. A malformed entry is logged and acked.
- **First boot.** The group is created from id `0`, so the first boot reads the
  backlog; every handler is idempotent.

## The wake-up flow

Each `OutboxItem` (from `tasks:outbox`, the run-end hook, or the reconcile loop)
is handled like this:

1. `cancelled_by_user`: skip.
2. The conversation must exist and be the item's `client_id`'s. Otherwise skip.
3. The mirror row already handled (`notified_at`): skip. A task the status stream
   has not delivered yet is mirrored first through `GET /tasks/{id}`.
4. Find the **leaf of the task's branch**: the newest answer whose
   `checkpoint_thread_id` is the item's `branch_thread_id`, even if the user has
   switched branch since. None left: skip.
5. Write the **notice row** under the leaf: sender `user`, `kind = task_notification`,
   content = the notification's text, and `task_notice = {task_id, name, status,
   duration_ms, agent_kwargs, agent_content}`.
6. Create a `send` run under the notice (same agent as the leaf). This is a delta
   resume on the branch thread, and the run request carries the notice as
   `{"id", "role": "user", "content": <the notification's own blocks>,
   "kind": "task_notification", "additional_kwargs": {...}}`. A full seed sends
   every earlier notice row the same way.
7. Launch the run, publish `run_started`, then mark the task handled (mirror
   `notified_at`, and `POST /tasks/{id}/notified {"client_id"}`).

| Outcome | What happens | Marked notified? |
| --- | --- | --- |
| Woken | Steps 5–7 ran. | Yes |
| Skipped (steps 1–4) | Nothing runs. | Yes |
| 409, the conversation is busy | The active run's middleware pulls the result; the run-end hook re-checks. | No |
| 429, the client's run cap | Retried `ASYNC_TASKS_WAKE_RETRY_ATTEMPTS` times, waiting `ASYNC_TASKS_WAKE_RETRY_BASE_SECONDS · 2^n`, then left to the reconcile loop. | No |

At most `ASYNC_TASKS_WAKE_CONCURRENCY` wake-ups run at once.

### Run end (the run-finished hook)

1. The conversation's **queued message goes first**.
2. If nothing was sent, and the run was **stopped by the user**: the pending
   results are held. Each is marked notified, so the orchestrator stays stopped; its
   next run pulls them.
3. Otherwise, wake **once** for a settled, unhandled depth-1 task. The agents service
   is asked (`GET /tasks/unnotified?client_id=&conversation_id=`) only when the
   mirror shows such a task, so an ordinary run end costs one query.

### Reconcile loop

The loop runs at startup, after orphaned runs are failed, and then every
`ASYNC_TASKS_RECONCILE_INTERVAL_SECONDS`. Each pass:

1. Sends queued messages older than `ASYNC_TASKS_QUEUE_SWEEP_AFTER_SECONDS` whose
   conversation has no active run. This closes the gap where a queued message was
   left unsent after a restart.
2. Works through `GET /tasks/unnotified`, one wake per conversation per pass.

Redis is only the doorbell; this is why no notification is lost across a restart.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `ASYNC_TASKS_ENABLED` | `true` | Kill switch for the consumers and the reconcile loop (routes and mirror stay). |
| `ASYNC_TASKS_CONSUMER_NAME` | host name | This process's consumer name. |
| `ASYNC_TASKS_READ_BLOCK_MS` / `ASYNC_TASKS_READ_COUNT` | 5000 / 50 | One `XREADGROUP`. |
| `ASYNC_TASKS_CLAIM_IDLE_MS` | 60000 | Pending pass interval and claim idle time. |
| `ASYNC_TASKS_RECONCILE_INTERVAL_SECONDS` | 60 | Reconcile loop period. |
| `ASYNC_TASKS_UNNOTIFIED_LIMIT` | 100 | Items per `GET /tasks/unnotified`. |
| `ASYNC_TASKS_QUEUE_SWEEP_AFTER_SECONDS` | 15 | Age before the loop sends a queued message. |
| `ASYNC_TASKS_WAKE_RETRY_ATTEMPTS` / `_BASE_SECONDS` | 3 / 2.0 | The 429 backoff. |
| `ASYNC_TASKS_WAKE_CONCURRENCY` | 4 | Wake-ups at once. |
| `ASYNC_TASKS_RAW_EVENTS_MAX` | 5000 | Stored events per task. |
| `ASYNC_TASKS_TASK_WS_BLOCK_MS` | 5000 | Drill-down poll for a settle while the stream is quiet. |
| `ASYNC_TASKS_LIST_LIMIT_MAX` | 500 | Cap of the task list route. |
| `TASK_READ_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | 120 / 60 | Task reads. |
| `TASK_MUTATE_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | 30 / 60 | Stop and approve. |

The conversation channel's size and TTL stay `CONVERSATION_CHANNEL_*`.

## Not included

| Left out | Why |
| --- | --- |
| Usage booking | There are no usage tables. `TaskOut.usage` is stored on the mirror only. |
| Scheduled (headless) wake-ups | There is no scheduler. `OutboxItem.interactive` is accepted and ignored. |
| Trials, account freeze and purge | There is no login. |
| Export | There is no export route. |
| CSRF | There are no cookies. |
