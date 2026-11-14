#!/usr/bin/env bash
# Build branded .pptx decks from presentations/decks/*/deck.yaml.
# Usage: ./scripts/build-decks.sh [deck ...] [--theme light|dark]
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python presentations/build.py "$@"
