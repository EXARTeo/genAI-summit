#!/usr/bin/env bash
# Run profile -> generate -> run-tests for the seed systems inside the real sandbox
# container and compare with the answer keys (scripts/sandbox_selfcheck/).
# Needs the stack up and the sandbox venv (product/sandbox/.venv).
# Usage: ./scripts/sandbox-selfcheck.sh [--cases SYS-001,SYS-004]
set -euo pipefail
cd "$(dirname "$0")/.."
py=product/sandbox/.venv/bin/python; [ -x "$py" ] || py=product/sandbox/.venv/Scripts/python.exe
PYTHONIOENCODING=utf-8 "$py" scripts/sandbox_selfcheck/selfcheck.py "$@"
