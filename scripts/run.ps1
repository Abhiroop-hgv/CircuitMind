# Start CircuitMind: API on :8000, web on :3000.
#
# Assumes bootstrap.ps1 has been run once and PostgreSQL is running as the
# normal Windows service (it starts on boot by default). If the app cannot
# reach the database, open Services and start "postgresql-x64-17".

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# quick DB reachability check
$pgBin = @(
    'C:\Program Files\PostgreSQL\17\bin',
    'C:\Program Files\PostgreSQL\16\bin'
) | Where-Object { Test-Path (Join-Path $_ 'pg_isready.exe') } | Select-Object -First 1
if ($pgBin) {
    & (Join-Path $pgBin 'pg_isready.exe') -h localhost -p 5432 | Out-Host
}

Write-Host "`nStarting API on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    '-NoExit','-Command',
    "Set-Location '$repo'; python -m uvicorn api.main:app --host 127.0.0.1 --port 8000"
)

Write-Host "Starting web on http://localhost:3000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    '-NoExit','-Command',
    "Set-Location '$repo\web'; npm run start"
)

Write-Host "`nGive them ~15 seconds, then open http://localhost:3000" -ForegroundColor Green
Write-Host "Stop by closing the two PowerShell windows that just opened."
