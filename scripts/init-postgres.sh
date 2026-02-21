#!/bin/bash
set -euo pipefail

PG_VERSION=16
PG_DATA="/workspace/data/postgres"
PG_BIN="/usr/lib/postgresql/$PG_VERSION/bin"

echo "=== Initializing PostgreSQL $PG_VERSION ==="

# Initialize data directory if not already done
# Check for postgresql.conf (not PG_VERSION) because pg_createcluster puts
# config in /etc/postgresql/ rather than the data directory, leaving stale
# data that initdb-based startup can't use.
if [ ! -f "$PG_DATA/postgresql.conf" ]; then
    rm -rf "${PG_DATA:?}"/*
    chown postgres:postgres "$PG_DATA"
    sudo -u postgres "$PG_BIN/initdb" -D "$PG_DATA" --auth-local peer --auth-host scram-sha-256 --no-instructions
fi

# Ensure runtime directories exist (tmpfs clears /var/run on container start)
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql
chown postgres:postgres /workspace/logs/postgres

# Start postgres temporarily
PG_LOG="/workspace/logs/postgres/init.log"
if ! sudo -u postgres "$PG_BIN/pg_ctl" -D "$PG_DATA" -l "$PG_LOG" start; then
    echo "=== PostgreSQL failed to start. Log output: ==="
    cat "$PG_LOG" 2>/dev/null || true
    exit 1
fi

# Wait for postgres to be ready
for i in $(seq 1 30); do
    if pg_isready -q; then
        break
    fi
    sleep 1
done

# Create synapse user and database
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'synapse') THEN
        CREATE USER synapse WITH PASSWORD '${SYNAPSE_DB_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'planka') THEN
        CREATE USER planka WITH PASSWORD '${PLANKA_DB_PASSWORD}';
    END IF;
END
\$\$;
SQL

sudo -u postgres createdb --owner=synapse --encoding=UTF8 --locale=C synapse 2>/dev/null || true
sudo -u postgres createdb --owner=planka planka 2>/dev/null || true

# Stop postgres (supervisord will start it properly)
sudo -u postgres "$PG_BIN/pg_ctl" -D "$PG_DATA" stop

echo "=== PostgreSQL initialized ==="
