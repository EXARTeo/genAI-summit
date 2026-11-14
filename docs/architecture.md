# Architecture

> To be written once the project scope is set. Keep this page current as the design changes.

## Overview

_What the system does, in two or three sentences._

## Layout

The product lives in one folder named after it. Each service is a subfolder with its own Dockerfile, and the folder's `docker-compose.yaml` wraps them all:

```text
<product>/
├── <service-a>/
│   └── Dockerfile
├── <service-b>/
│   └── Dockerfile
└── docker-compose.yaml
```

## Services

The product folder is `product/` until a name is chosen. Full table (images, networks, healthchecks): [product/README.md](../product/README.md).

| Service | Folder | Port (host → container) | Responsibility |
| --- | --- | --- | --- |
| `backend` | `product/backend/` | 8100 → 8000 | FastAPI API; runs `alembic upgrade head` on start |
| `agents` | `product/agents/` | not published (8003) | Runs the agents (OpenAI, deep agents, async sub-agents, MCP, sandbox) and streams AG-UI to the backend: [agents-service.md](agents-service.md), [agents-contract.md](agents-contract.md) |
| `postgres` | (image) | not published | Backend database + `agent_runtime` (checkpoints, conversation files, tasks) |
| `redis` | (image) | not published | Backend cache (`volatile-lru`) |
| `langfuse-web` + `langfuse-worker` | (images) | 3400 → 3000 | Langfuse v4: trace UI, ingestion API, async processing |
| `langfuse-postgres`, `-clickhouse`, `-redis`, `-minio` | (images) | not published | Langfuse's own datastores |

## Data flow

_Diagram or step list of how a request moves through the system (input → model/provider → output)._

## Decisions

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-13 | Services run in Docker, wrapped by one compose file in the product folder | One command starts the whole product, locally and on a server |
| 2026-11-13 | Repo tooling: Python 3.12 + uv, pytest, ruff | Fast, reproducible checks with one lockfile |
| 2026-11-13 | Self-hosted Langfuse v4 in the product compose, with its own Postgres and Valkey | Full traceability without a SaaS; v3 is deprecated; Langfuse's queues need `noeviction` and its migrations stay off the product database |
