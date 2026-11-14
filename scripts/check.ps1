# Run the same checks as CI: lint, format check, tests (Windows).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$steps = @(
    @{ Name = 'ruff check';            Args = @('run', 'ruff', 'check', '.') },
    @{ Name = 'ruff format --check';   Args = @('run', 'ruff', 'format', '--check', '.') },
    @{ Name = 'pytest';                Args = @('run', 'python', '-m', 'pytest') }
)

foreach ($step in $steps) {
    Write-Host "==> $($step.Name)"
    & uv @($step.Args)
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Service suites: each in its own venv (product/<service>/.venv), created on
# first run; the tests live in tests/<service>/ (dashes as underscores).
foreach ($service in 'backend', 'agents', 'reg-memory', 'model-gateway', 'mlflow-seed', 'sandbox') {
    Write-Host "==> $service tests"
    $venv = "product\$service\.venv"
    if (-not (Test-Path $venv)) {
        uv venv $venv --python 3.12
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $python = Join-Path $venv 'Scripts\python.exe'
    uv pip install --quiet --python $python -r "product\$service\requirements.txt"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($service -eq 'sandbox') {
        # synthkit is the image's `synthkit` command; the exec tests run it.
        uv pip install --quiet --python $python -e "product\sandbox\synthkit"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & $python -m pytest "tests\$($service -replace '-', '_')" -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Validate every docker compose file, with its sibling .env.example if present
$composeFiles = Get-ChildItem -Recurse -File -Include 'docker-compose*.yml', 'docker-compose*.yaml', 'compose*.yml', 'compose*.yaml' |
    Where-Object { $_.FullName -notmatch '[\\/]\.venv[\\/]' }
foreach ($file in $composeFiles) {
    Write-Host "==> docker compose config: $($file.FullName)"
    $envFile = Join-Path $file.DirectoryName '.env.example'
    if (Test-Path $envFile) {
        docker compose -f $file.FullName --env-file $envFile config --quiet
    } else {
        docker compose -f $file.FullName config --quiet
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host 'All checks passed.'
