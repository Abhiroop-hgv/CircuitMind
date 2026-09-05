# One-time setup: create the scip role and database.
#
# Run this in a REAL PowerShell window (not an embedded terminal panel) so that
# psql can read the password prompt from the console.

$psql = 'C:\Program Files\PostgreSQL\17\bin\psql.exe'

Write-Host ''
Write-Host 'Creating the scip role and database.' -ForegroundColor Cyan
Write-Host 'psql will ask for your PostgreSQL superuser (postgres) password.'
Write-Host 'It does not echo what you type - no dots, no asterisks. Type it and press Enter.'
Write-Host ''

& $psql -U postgres -c "DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'scip') THEN CREATE ROLE scip LOGIN PASSWORD 'scip'; END IF; END `$`$;"

if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Role creation failed. Check the password and try again.' -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

& $psql -U postgres -c "CREATE DATABASE scip OWNER scip;"

Write-Host ''
Write-Host 'Verifying...' -ForegroundColor Cyan
$env:PGPASSWORD = 'scip'
& $psql -U scip -d scip -h localhost -c "SELECT current_database(), current_user, version();"
Remove-Item Env:\PGPASSWORD

Write-Host ''
Write-Host 'If you saw a row above, you are done. Close this window and go back to Claude.' -ForegroundColor Green
Read-Host 'Press Enter to close'
