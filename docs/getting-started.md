# Getting started

## Prerequisites

| Tool | Version | Install |
| --- | --- | --- |
| Docker + Compose | recent | <https://docs.docker.com/get-docker/> |
| Python | 3.12+ | <https://www.python.org/downloads/> |
| uv | latest | <https://docs.astral.sh/uv/getting-started/installation/> |
| Git | any recent | <https://git-scm.com/> |

## Setup

```bash
./scripts/setup.sh          # Windows: .\scripts\setup.ps1
```

The script:

1. installs dependencies into `.venv` (`uv sync`),
2. creates `.env` from `.env.example` if it does not exist,
3. installs the pre-commit git hooks.

## Configuration

All configuration comes from environment variables, loaded from `.env` locally. See [`.env.example`](../.env.example) for the full list. Never commit `.env` or real keys.

## Run

The product's services run with Docker Compose from the product folder (`product/` until it is named). Its variables are in [`product/.env.example`](../product/.env.example) (copy to `product/.env`); services and ports in [product/README.md](../product/README.md).

```bash
docker compose -f product/docker-compose.yaml up -d --build
docker compose -f product/docker-compose.yaml logs -f
docker compose -f product/docker-compose.yaml down
```

## Verify

```bash
./scripts/check.sh          # Windows: .\scripts\check.ps1
```

This runs the same lint, format, test and `docker compose config` steps as CI.

## Dependencies

- **Service dependencies** belong to each service (its own `pyproject.toml`, `package.json`, etc.) and are installed in its Docker image.
- **Repo tooling** (ruff, pytest, pre-commit) is in the root `pyproject.toml`: `uv add --dev <package>`, then commit `pyproject.toml` and `uv.lock`.
