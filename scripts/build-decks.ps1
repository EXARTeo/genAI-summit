# Build branded .pptx decks from presentations/decks/*/deck.yaml (Windows).
# Usage: .\scripts\build-decks.ps1 [deck ...] [--theme light|dark]
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

uv run python presentations/build.py @args
exit $LASTEXITCODE
