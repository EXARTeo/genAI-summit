#!/usr/bin/env bash
# Set up a local development environment.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }

uv sync
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example; fill in your keys."; }
uv run pre-commit install

echo "Setup complete. Run ./scripts/check.sh to verify."
