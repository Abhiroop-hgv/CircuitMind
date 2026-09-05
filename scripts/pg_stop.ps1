# Stop the project's PostgreSQL instance on port 5433.
# Leaves the PostgreSQL 17 Windows service on 5432 untouched.

$bin  = 'C:\Program Files\PostgreSQL\17\bin'
$data = 'C:\Users\DELL\.scip-pgdata'

& "$bin\pg_ctl.exe" -D $data -m fast stop
