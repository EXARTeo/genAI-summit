#!/usr/bin/env bash
# Run the product stack with the repo's single .env (falls back to .env.example).
# Usage: ./scripts/stack.sh up|down|ps|logs|config|<any docker compose args>
set -euo pipefail
cd "$(dirname "$0")/.."
env_file=.env; [ -f "$env_file" ] || env_file=.env.example
cmd="${1:-up}"; shift || true
case "$cmd" in
  up) set -- up -d --build "$@" ;;
  *)  set -- "$cmd" "$@" ;;
esac
docker compose --env-file "$env_file" -f product/docker-compose.yaml "$@"
