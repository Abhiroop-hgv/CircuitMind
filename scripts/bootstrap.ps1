# CircuitMind - one-shot setup on a fresh machine.
#
# Prerequisites you install yourself first (see SETUP.md):
#   Python 3.10+, Node.js 20+, PostgreSQL 16/17, Git
#
# Then, from the repo root:
#   1. Copy-Item .env.example .env   and paste your GROQ_API_KEY into .env
#   2. pwsh scripts/bootstrap.ps1
#
# Safe to re-run. It rebuilds the database from scratch each time.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Ok($m)   { Write-Host "  ok   $m" -ForegroundColor Green }
function Die($m)  { Write-Host "`nFAILED: $m" -ForegroundColor Red; exit 1 }

# --- 1. prerequisites -------------------------------------------------------
Write-Host "`n[1/7] prerequisites" -ForegroundColor Cyan
foreach ($t in 'python','node','npm','git') {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        Die "$t is not on PATH. Install it (see SETUP.md) and open a new terminal."
    }
    Ok $t
}
$pgBin = @(
    'C:\Program Files\PostgreSQL\17\bin',
    'C:\Program Files\PostgreSQL\16\bin'
) | Where-Object { Test-Path (Join-Path $_ 'psql.exe') } | Select-Object -First 1
if (-not $pgBin) { Die "PostgreSQL 16 or 17 not found under C:\Program Files\PostgreSQL." }
$psql = Join-Path $pgBin 'psql.exe'
Ok "PostgreSQL ($pgBin)"

# --- 2. .env ---------------------------------------------------------------
Write-Host "`n[2/7] .env" -ForegroundColor Cyan
if (-not (Test-Path .env)) {
    Die "No .env file. Run:  Copy-Item .env.example .env  then paste your GROQ_API_KEY into it."
}
if (-not (Select-String -Path .env -Pattern 'GROQ_API_KEY=gsk_' -Quiet)) {
    Write-Host "  WARN  GROQ_API_KEY in .env is not set - the assistant and live 'analyse' will not work until it is." -ForegroundColor Yellow
}
# Point the app at the standard local PostgreSQL service on 5432.
(Get-Content .env) `
    -replace '^DATABASE_URL=.*', 'DATABASE_URL=postgresql://scip:scip@localhost:5432/scip' `
    | Set-Content .env
Ok "DATABASE_URL -> postgresql://scip:scip@localhost:5432/scip"

# --- 3. role + database ---------------------------------------------------
Write-Host "`n[3/7] database role and database" -ForegroundColor Cyan
Write-Host "  Enter the 'postgres' superuser password you set when installing PostgreSQL."
$pw = Read-Host "  postgres password" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))

& $psql -U postgres -h localhost -v ON_ERROR_STOP=1 -c @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'scip') THEN
    CREATE ROLE scip LOGIN SUPERUSER PASSWORD 'scip';
  END IF;
END `$`$;
"@
if ($LASTEXITCODE -ne 0) { Die "could not create the scip role - wrong postgres password, or the service is stopped." }

$exists = (& $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='scip'").Trim()
if ($exists -ne '1') {
    & $psql -U postgres -h localhost -c "CREATE DATABASE scip OWNER scip"
    if ($LASTEXITCODE -ne 0) { Die "could not create the scip database." }
}
Remove-Item Env:\PGPASSWORD
Ok "role 'scip' and database 'scip' ready on localhost:5432"

# --- 4. python deps -----------------------------------------------------
Write-Host "`n[4/7] python dependencies" -ForegroundColor Cyan
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "pip install failed." }
Ok "requirements.txt installed"

# --- 5. schema + seed -------------------------------------------------
Write-Host "`n[5/7] schema and seed data" -ForegroundColor Cyan
python scripts/init_db.py            ; if ($LASTEXITCODE -ne 0) { Die "init_db.py failed." }
python scripts/create_readonly_role.py ; if ($LASTEXITCODE -ne 0) { Die "create_readonly_role.py failed." }
Ok "dummy ERP built, read-only role created"

# --- 6. demo data ---------------------------------------------------
Write-Host "`n[6/7] demo recommendation" -ForegroundColor Cyan
python scripts/demo.py --offline     ; if ($LASTEXITCODE -ne 0) { Die "demo.py failed." }
Ok "STM32 export-licence recommendation generated (PENDING_APPROVAL)"

# --- 7. web build --------------------------------------------------
Write-Host "`n[7/7] web app" -ForegroundColor Cyan
Push-Location web
npm install --no-audit --no-fund ; if ($LASTEXITCODE -ne 0) { Pop-Location; Die "npm install failed." }
npm run build                    ; if ($LASTEXITCODE -ne 0) { Pop-Location; Die "npm run build failed." }
Pop-Location
Ok "web app built"

Write-Host "`nDone. Start everything with:  pwsh scripts/run.ps1" -ForegroundColor Green
