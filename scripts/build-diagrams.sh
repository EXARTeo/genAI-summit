#!/usr/bin/env bash
# Build the architecture diagrams (SVG + PNG) in docs/architecture/diagrams/ from brand.json.
# Usage: ./scripts/build-diagrams.sh [--svg-only]
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python docs/architecture/diagrams/build.py "$@"
