#!/bin/bash
set -e

ERRORS=0

check() {
    local name="$1"
    local url="$2"
    if curl -sf --max-time 5 "$url" > /dev/null 2>&1; then
        echo "OK: $name"
    else
        echo "FAIL: $name ($url)"
        ERRORS=$((ERRORS + 1))
    fi
}

check "nginx"    "http://127.0.0.1:8888/"
check "synapse"  "http://127.0.0.1:8008/_matrix/client/versions"
check "chromadb" "http://127.0.0.1:8000/api/v1/heartbeat"
check "ollama"   "http://127.0.0.1:11434/api/tags"
check "ttyd"     "http://127.0.0.1:7681/"
check "neko"     "http://127.0.0.1:8080/"
check "planka"   "http://127.0.0.1:1337/"

# PostgreSQL check via pg_isready
if pg_isready -q 2>/dev/null; then
    echo "OK: postgres"
else
    echo "FAIL: postgres"
    ERRORS=$((ERRORS + 1))
fi

# CDP check
check "chromium-cdp" "http://127.0.0.1:9222/json/version"

if [ "$ERRORS" -gt 0 ]; then
    echo "=== $ERRORS service(s) unhealthy ==="
    exit 1
fi

echo "=== All services healthy ==="
