# Set up a local development environment (Windows).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is required: https://docs.astral.sh/uv/'
}

uv sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host 'Created .env from .env.example; fill in your keys.'
}

uv run pre-commit install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'Setup complete. Run .\scripts\check.ps1 to verify.'
