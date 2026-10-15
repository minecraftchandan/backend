$ErrorActionPreference = "Stop"

$backendRoot = $PSScriptRoot
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $backendRoot ".env"

if (-not (Test-Path $python)) {
    Write-Error "Backend virtual environment not found. Create it with: python -m venv .venv; then run: .\.venv\Scripts\pip.exe install -r requirements.txt"
    exit 1
}

if (-not (Test-Path $envFile)) {
    Write-Error "Backend .env file not found. Copy env.example to .env and configure DATABASE_URL before starting."
    exit 1
}

Set-Location $backendRoot
& $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
