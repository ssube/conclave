#!/bin/bash
set -euo pipefail

PG_VERSION=16
PG_DATA="/workspace/data/postgres"

echo "=== Initializing PostgreSQL $PG_VERSION ==="

# Create cluster if not exists
if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    pg_createcluster "$PG_VERSION" main --datadir="$PG_DATA"
fi

# Start postgres temporarily
pg_ctlcluster "$PG_VERSION" main start

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
pg_ctlcluster "$PG_VERSION" main stop

echo "=== PostgreSQL initialized ==="
