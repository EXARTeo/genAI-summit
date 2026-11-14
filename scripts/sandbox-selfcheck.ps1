# Run profile -> generate -> run-tests for the seed systems inside the real sandbox
# container and compare with the answer keys (scripts/sandbox_selfcheck/).
# Needs the stack up and the sandbox venv (mnamon/sandbox/.venv).
# Usage: .\scripts\sandbox-selfcheck.ps1 [--cases SYS-001,SYS-004]
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$env:PYTHONIOENCODING = 'utf-8'
& mnamon\sandbox\.venv\Scripts\python.exe scripts\sandbox_selfcheck\selfcheck.py @args
exit $LASTEXITCODE
