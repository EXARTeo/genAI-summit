# product

The product stack (placeholder name until the branding is chosen): the backend with its Postgres and Redis, plus a self-hosted **Langfuse v4** for full agent tracing. One compose file, project name `genai-summit`.

## Run

```bash
cp product/.env.example product/.env       # optional: every variable has a dev default
docker compose -f product/docker-compose.yaml up -d --build
docker compose -f product/docker-compose.yaml ps        # all services (healthy)
docker compose -f product/docker-compose.yaml down      # add -v to wipe the data
```

First start takes about a minute: Langfuse runs its Postgres and ClickHouse migrations, then creates the org, project, API keys and login user.

## Services

| Service | Image | Host port | Networks | Healthcheck |
| --- | --- | --- | --- | --- |
| `backend` | built from `./backend` (python:3.12-slim) | `127.0.0.1:${BACKEND_PORT:-8100}` → 8000 | `backend`, `edge`, `langfuse` | `GET /health` (python urllib) |
| `agents` | built from `./agents` (python:3.12-slim) | none (8003 internal) | `backend`, `edge`, `langfuse`, `mcp_net`, `sandbox_net` | `GET /health` (python urllib) |
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
| `backend` | yes | backend, postgres, redis | Data plane; no route out |
| `edge` | no | backend | Published port and egress (LLM APIs, future agents service) |
| `langfuse` | no | backend, langfuse-web | Apps send traces to `http://langfuse-web:3000`; web's published UI port |
| `langfuse_internal` | yes | all `langfuse-*` | Langfuse datastores and worker; no route out |

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

Every variable is listed in [`.env.example`](.env.example) with its dev default. For anything shared, generate real secrets with `openssl rand -hex 32`. Database, ClickHouse, Redis and MinIO passwords are baked into the volumes on first start: change them before the first `up`, or recreate the volumes.
