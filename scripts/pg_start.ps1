# Start the project's own PostgreSQL instance on port 5433.
#
# This is a standalone instance created with initdb, NOT the PostgreSQL 17
# Windows service. It is not registered as a service, so it does not come back
# by itself after a reboot - run this script.

$bin  = 'C:\Program Files\PostgreSQL\17\bin'
$data = 'C:\Users\DELL\.scip-pgdata'

& "$bin\pg_ctl.exe" -D $data -l "$data\server.log" -o "-p 5433 -c listen_addresses=127.0.0.1" start
Start-Sleep -Seconds 2
& "$bin\pg_isready.exe" -h 127.0.0.1 -p 5433
