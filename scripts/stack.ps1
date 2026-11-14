# Run the product stack with the repo's single .env (falls back to .env.example).
# Uses Docker on Windows if present, otherwise Docker Engine inside WSL.
# Usage: .\scripts\stack.ps1 up|down|ps|logs|config|<any docker compose args>
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$envFile = if (Test-Path .env) { '.env' } else { '.env.example' }
$cmd = if ($args.Count -gt 0) { $args[0] } else { 'up' }
$rest = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }
$composeArgs = if ($cmd -eq 'up') { @('up', '-d', '--build') + $rest } else { @($cmd) + $rest }
$full = @('compose', '--env-file', $envFile, '-f', 'mnamon/docker-compose.yaml') + $composeArgs
# Docker writes progress to stderr; under 'Stop', Windows PowerShell 5.1 turns
# that into a terminating error once stderr is redirected. Judge by exit code.
$ErrorActionPreference = 'Continue'
if (Get-Command docker -ErrorAction SilentlyContinue) { & docker @full } else { & wsl -d Ubuntu -- docker @full }
exit $LASTEXITCODE
