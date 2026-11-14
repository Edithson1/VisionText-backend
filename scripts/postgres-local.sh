#!/usr/bin/env bash
set -euo pipefail

runtime="${XDG_DATA_HOME:-$HOME/.local/share}/visiontext-postgres"
postgres="$runtime/portable/usr/lib/postgresql/16/bin"
export LD_LIBRARY_PATH="$runtime/portable/usr/lib/x86_64-linux-gnu"
export PGDATA="$runtime/data"
export PGPORT=55432 PGUSER=visiontext PGHOST=127.0.0.1 PGPASSWORD
PGPASSWORD=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | tr -d '\r')

if [[ ! -x "$postgres/postgres" ]]; then
    echo 'Faltan los binarios portables de PostgreSQL 16 en Ubuntu.' >&2
    exit 1
fi
if [[ -z "$PGPASSWORD" ]]; then
    echo 'Configura POSTGRES_PASSWORD en .env.' >&2
    exit 1
fi
if [[ ! -s "$PGDATA/PG_VERSION" ]]; then
    "$postgres/initdb" --auth=scram-sha-256 --username="$PGUSER" --locale=C --encoding=UTF8 \
        --pwfile=<(printf '%s\n' "$PGPASSWORD")
fi
if ! "$postgres/pg_ctl" status >/dev/null; then
    "$postgres/pg_ctl" start --wait --log="$runtime/postgres.log" \
        --options="-h $PGHOST -p $PGPORT -k $runtime"
fi
if [[ -z $("$postgres/psql" -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname='visiontext'") ]]; then
    "$postgres/createdb" visiontext
fi
