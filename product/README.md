# product

The product stack (placeholder name until the branding is chosen): the backend with its Postgres and Redis, plus a self-hosted **Langfuse v4** for full agent tracing. One compose file, project name `genai-summit`.

## Run

```bash
cp .env.example .env        # repo root: the ONE env file (optional: dev defaults built in)
./scripts/stack.sh up       # Windows: .\scripts\stack.ps1 up
./scripts/stack.sh ps       # all services (healthy)
./scripts/stack.sh down     # add -v to wipe the data
```

First start takes about a minute: Langfuse runs its Postgres and ClickHouse migrations, then creates the org, project, API keys and login user.

## Services

| Service | Image | Host port | Networks | Healthcheck |
| --- | --- | --- | --- | --- |
| `backend` | built from `./backend` (python:3.12-slim) | `127.0.0.1:${BACKEND_PORT:-8100}` → 8000 | `backend`, `edge`, `langfuse` | `GET /health` (python urllib) |
| `frontend` | built from `./frontend` (node:22 build → nginx-unprivileged 1.27.3), read-only root fs | `127.0.0.1:${FRONTEND_PORT:-8080}` → 8080 | `edge` | `GET /healthz` (wget) |
| `agents` | built from `./agents` (python:3.12-slim) | none (8003 internal) | `backend`, `edge`, `langfuse`, `mcp_net`, `sandbox_net` | `GET /health` (python urllib) |
| `reg-memory` | built from `./reg-memory` (python:3.12-slim), volume `reg-memory-data` → `/data` | none (8010 internal) | `backend`, `edge` | `GET /health` (python urllib) |
| `model-gateway` | built from `./model-gateway` (python:3.12-slim) | `127.0.0.1:${MODEL_GATEWAY_PORT:-8200}` → 8000 | `backend`, `edge`, `sandbox_models` | `GET /health` (python urllib) |
| `mlflow` | built from `./mlflow` (python:3.12-slim, MLflow 3.17.2), volume `mlflow_artifacts` → `/mlartifacts`; metadata in the `mlflow` database on `postgres` | `127.0.0.1:${MLFLOW_PORT:-5500}` → 5000 | `backend`, `edge`, `sandbox_models` | `GET /health` (python urllib) |
| `sandbox_runner` | built from `./sandbox` (python:3.12-slim + ML stack + synthkit); read-only rootfs, tmpfs `/work` + `/tmp`, 4 GB | none (8090 internal) | `sandbox_net`, `sandbox_models` | `GET /health` (python urllib) |
| `mlflow-seed` | built from `./mlflow-seed` (python:3.12-slim); one-shot (`restart: "no"`), volume `seed_cases` → `/seed-cases` | none | `backend` | none (exits 0; `model-gateway` waits for `service_completed_successfully`) |
| `postgres` | `postgres:16.14-alpine` | none | `backend` | `pg_isready` |
| `redis` | `redis:7.4.9-alpine` (256 MB, `volatile-lru`, no persistence) | none | `backend` | `redis-cli ping` (auth) |
| `langfuse-web` | `langfuse/langfuse:4.70.0` | `127.0.0.1:${LANGFUSE_PORT:-3400}` → 3000 | `langfuse`, `langfuse_internal` | `GET /api/public/health` |
| `langfuse-worker` | `langfuse/langfuse-worker:4.70.0` | none | `langfuse_internal` | `GET :3030/api/health` |
| `langfuse-postgres` | `postgres:16.14-alpine` | none | `langfuse_internal` | `pg_isready` |
| `langfuse-clickhouse` | `clickhouse/clickhouse-server:26.3.60.2-alpine` | none | `langfuse_internal` | `GET :8123/ping` |
| `langfuse-redis` | `valkey/valkey:8.1.10-alpine3.24` (`noeviction`, AOF) | none | `langfuse_internal` | `valkey-cli ping` (auth) |
| `langfuse-minio` | `cgr.dev/chainguard/minio` (pinned by digest) | none | `langfuse_internal` | `mc ready local` |

Default host ports avoid the ones already taken on the dev machine (8000, 3000, 3300). Both bind to `127.0.0.1` only.

## Networks

| Network | Internal | Members | Purpose |
| --- | --- | --- | --- |
| `backend` | yes | backend, agents, reg-memory, model-gateway, mlflow, mlflow-seed, postgres, redis | Data plane; no route out |
| `edge` | no | backend, agents, reg-memory, model-gateway, mlflow | Published port and egress (LLM APIs; reg-memory downloads from public EU sites) |
| `langfuse` | no | backend, langfuse-web | Apps send traces to `http://langfuse-web:3000`; web's published UI port |
| `langfuse_internal` | yes | all `langfuse-*` | Langfuse datastores and worker; no route out |
| `sandbox_net` | yes | agents, sandbox_runner | `execute` → `POST http://sandbox_runner:8090/v1/exec` |
| `sandbox_models` | yes | sandbox_runner, mlflow, model-gateway | The sandbox reaches only the model under test; no internet |

## Langfuse

| Item | Value |
| --- | --- |
| UI | <http://localhost:3400> |
| Login | `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` (dev default `admin@example.com` / `genai-summit-dev-1`); sign-up is disabled |
| Org / project | `GenAI Summit` / `product` |
| API keys | `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`: created in Langfuse on first start and passed to the backend, so tracing works with no clicks |
| Ingestion | OpenTelemetry only (`/api/public/otel/v1/traces`): use the Langfuse Python SDK v3 or newer. The legacy `/api/public/ingestion` accepts scores only in v4 |

Design choices:

- **Own Postgres for Langfuse**, not a database on `postgres`: an init script only runs on an empty volume (fragile once the backend's volume exists), and a separate instance keeps Langfuse's migrations, upgrades and load away from the product database. Cost: about 100 MB RAM.
- **Own Redis (Valkey) for Langfuse**: its BullMQ queues need `noeviction` (an evicted job is a lost trace); the backend's cache uses `volatile-lru`.
- **v4, not v3**: self-hosted v3 is deprecated (security fixes only until January 2027) and its images carry critical CVEs. Config copied from the team's verified self-hosted Langfuse.
- Media uploads and batch exports are off: both need MinIO reachable from the browser, and MinIO is not published.
- No trace retention is set (Langfuse's retention is an Enterprise feature); `down -v` wipes everything.

## Configuration

Every variable is listed in the repo's single [`.env.example`](../.env.example) with its dev default. For anything shared, generate real secrets with `openssl rand -hex 32`. Database, ClickHouse, Redis and MinIO passwords are baked into the volumes on first start: change them before the first `up`, or recreate the volumes.
