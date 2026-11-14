#!/usr/bin/env bash
# Run the same checks as CI: lint, format check, tests.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ruff check"
uv run ruff check .
echo "==> ruff format --check"
uv run ruff format --check .
echo "==> pytest"
uv run python -m pytest

# Service suites: each in its own venv (mnamon/<service>/.venv), created on
# first run; the tests live in tests/<service>/ (dashes as underscores).
for service in backend agents reg-memory model-gateway mlflow-seed sandbox; do
  echo "==> $service tests"
  venv="mnamon/$service/.venv"
  if [ ! -d "$venv" ]; then
    uv venv "$venv" --python 3.12
  fi
  python="$venv/bin/python"
  [ -x "$python" ] || python="$venv/Scripts/python.exe"
  uv pip install --quiet --python "$python" -r "mnamon/$service/requirements.txt"
  if [ "$service" = sandbox ]; then
    # synthkit is the image's `synthkit` command; the exec tests run it.
    uv pip install --quiet --python "$python" -e mnamon/sandbox/synthkit
  fi
  "$python" -m pytest "tests/${service//-/_}" -q
done

# Frontend: typecheck, lint, format, tests, build (needs Node 20+).
echo "==> frontend checks"
(cd mnamon/frontend && npm ci && npm run typecheck && npm run lint && npm run format:check && npm test && npm run build)

# Validate every docker compose file with the repo's single .env.example
find . -path ./.venv -prune -o \( -name 'docker-compose*.y*ml' -o -name 'compose*.y*ml' \) -print |
  while read -r f; do
    echo "==> docker compose config: $f"
    docker compose -f "$f" --env-file .env.example config --quiet
  done

echo "All checks passed."
