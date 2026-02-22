#!/bin/bash
set -e

ERRORS=0

# Load credentials if available
[[ -f /workspace/config/generated-secrets.env ]] && source /workspace/config/generated-secrets.env 2>/dev/null || true
ADMIN_PASSWORD="${CONCLAVE_ADMIN_PASSWORD:-}"
CHROMADB_TOKEN="${AGENT_CHROMADB_TOKEN:-${CHROMADB_TOKEN:-}}"

check() {
    local name="$1"
    local url="$2"
    shift 2
    if curl -sf --max-time 5 "$@" "$url" > /dev/null 2>&1; then
        echo "OK: $name"
    else
        echo "FAIL: $name ($url)"
        ERRORS=$((ERRORS + 1))
    fi
}

if [ -n "$ADMIN_PASSWORD" ]; then
    check "nginx" "http://127.0.0.1:8888/" -u "admin:${ADMIN_PASSWORD}"
else
    check "nginx" "http://127.0.0.1:8888/"
fi

if [ "${CONCLAVE_SYNAPSE_ENABLED:-true}" = "true" ]; then
    check "synapse" "http://127.0.0.1:8008/_matrix/client/versions"
fi

if [ -n "$CHROMADB_TOKEN" ]; then
    check "chromadb" "http://127.0.0.1:8000/api/v2/heartbeat" -H "Authorization: Bearer ${CHROMADB_TOKEN}"
else
    check "chromadb" "http://127.0.0.1:8000/api/v2/heartbeat"
fi

if [ "${CONCLAVE_OLLAMA_ENABLED:-true}" = "true" ]; then
    check "ollama" "http://127.0.0.1:11434/api/tags"
fi

if [ -n "$ADMIN_PASSWORD" ]; then
    check "ttyd" "http://127.0.0.1:7681/" -u "admin:${ADMIN_PASSWORD}"
else
    check "ttyd" "http://127.0.0.1:7681/"
fi
check "neko"     "http://127.0.0.1:8080/"

if [ "${CONCLAVE_PLANKA_ENABLED:-true}" = "true" ]; then
    check "planka" "http://127.0.0.1:1337/"
fi

if [ "${CONCLAVE_PUSHGATEWAY_ENABLED:-true}" = "true" ]; then
    check "pushgateway" "http://127.0.0.1:9091/-/healthy"
fi

# PostgreSQL check via pg_isready
if [ "${CONCLAVE_POSTGRES_ENABLED:-true}" = "true" ]; then
    if pg_isready -q 2>/dev/null; then
        echo "OK: postgres"
    else
        echo "FAIL: postgres"
        ERRORS=$((ERRORS + 1))
    fi
fi

# CDP check
check "chromium-cdp" "http://127.0.0.1:9222/json/version"

if [ "$ERRORS" -gt 0 ]; then
    echo "=== $ERRORS service(s) unhealthy ==="
    exit 1
fi

echo "=== All services healthy ==="
