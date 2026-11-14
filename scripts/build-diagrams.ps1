# Build the architecture diagrams (SVG + PNG) in docs/architecture/diagrams/ from brand.json (Windows).
# Usage: .\scripts\build-diagrams.ps1 [--svg-only]
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

uv run python docs/architecture/diagrams/build.py @args
exit $LASTEXITCODE
