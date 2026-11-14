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

# Service suites: each in its own venv (product/<service>/.venv), created on
# first run; the tests live in tests/<service>/ (dashes as underscores).
for service in backend agents reg-memory model-gateway mlflow-seed sandbox; do
  echo "==> $service tests"
  venv="product/$service/.venv"
  if [ ! -d "$venv" ]; then
    uv venv "$venv" --python 3.12
  fi
  python="$venv/bin/python"
  [ -x "$python" ] || python="$venv/Scripts/python.exe"
  uv pip install --quiet --python "$python" -r "product/$service/requirements.txt"
  if [ "$service" = sandbox ]; then
    # synthkit is the image's `synthkit` command; the exec tests run it.
    uv pip install --quiet --python "$python" -e product/sandbox/synthkit
  fi
  "$python" -m pytest "tests/${service//-/_}" -q
done

# Validate every docker compose file, with its sibling .env.example if present
find . -path ./.venv -prune -o \( -name 'docker-compose*.y*ml' -o -name 'compose*.y*ml' \) -print |
  while read -r f; do
    echo "==> docker compose config: $f"
    env_file="$(dirname "$f")/.env.example"
    if [ -f "$env_file" ]; then
      docker compose -f "$f" --env-file "$env_file" config --quiet
    else
      docker compose -f "$f" config --quiet
    fi
  done

echo "All checks passed."
