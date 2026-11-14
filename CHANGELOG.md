# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- `docs/` split into `guides/`, `architecture/`, `services/` and `contracts/` (index in `docs/README.md`); all repo references updated. `docs/architecture/README.md` now summarises the AI Act Governance Copilot design (MVP containers, engineer pipeline, regulation-change flow) and links the full design PDF, renamed to `docs/architecture/ai-act-governance-copilot.pdf`.

### Added

- Repository scaffolding: README, license, docs, tests, scripts, CI workflow and contribution templates.
- `branding/`: brand tokens (`brand.json`), guidelines, logo and font folders, CSS token export.
- `presentations/`: YAML-to-PowerPoint deck builder using the brand tokens, with an example deck.
- `product/docker-compose.yaml`: backend, Postgres 16, Redis 7.4 and a self-hosted Langfuse v4 (web, worker, Postgres, ClickHouse, Valkey, MinIO) with headless init of org, project, API keys and login; `product/.env.example`, `product/README.md`.
- Compose checks (CI, `scripts/check.*`) pass a compose file's sibling `.env.example` as `--env-file`.
- `product/agents/`: the agents service (FastAPI, port 8003) implementing `docs/contracts/agents-contract.md`: AG-UI streaming with keepalives, HITL resume (stale-interrupt 409), durable Postgres checkpoints in `agent_runtime` (created at start) with copy-on-fork, conversation files as encrypted rows with the request's inline uploads written to `/conversation/input/`, `present_artifact` cards carrying the file bytes (`data_base64`), the MCP gateway and sandbox-runner siblings, Langfuse traces nested under the backend's trace, client ids hashed in logs, the internal-secret gate (fail-closed outside development), and the generic `assistant` agent; `GET /agents` for a UI. Suite in `tests/agents/`, docs in `docs/services/agents-service.md`.
- Agents service async sub-agents: background tasks keyed by the anonymous `client_id` (TaskRunner, task tables, signed launch token, in-process `/ap`, internal `/tasks` API, `tasks:status` / `tasks:outbox` / `task:{id}:events` streams); task runs nest under the spawning run's Langfuse trace. Protocol in `docs/contracts/agents-contract.md` § Async sub-agents.
- Backend async sub-agents: `conversation_tasks` mirror fed by the `tasks:status` consumer (group `backend`), `tasks:outbox` wake-ups (notice row with `kind`/`taskNotice` + a `send` run on the task's branch), run-end hook (queued message first, then one wake-up), reconcile loop (also sends a queued message a restart left unsent), `task` frames on the conversation channel, task routes (`GET /v1/conversations/{id}/tasks`, `GET /v1/tasks/active-conversations`, `POST /v1/tasks/{id}/cancel|resume`, `WS /v1/tasks/{id}/ws`) with task read/mutate rate limits, `hasActiveTasks` / `activeTaskMessageId`, migration `0002_async_tasks`, `ASYNC_TASKS_*` settings. See `docs/services/backend.md`.
