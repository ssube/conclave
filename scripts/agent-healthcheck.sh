#!/bin/bash
# =============================================================================
# Agent Health Check — Deterministic service checks with structured output
#
# No LLM in the loop. Checks every Conclave service with correct URLs,
# outputs structured results. Called by agents via the healthcheck skill.
#
# Usage:
#   bash /opt/conclave/scripts/agent-healthcheck.sh           # Human-readable
#   bash /opt/conclave/scripts/agent-healthcheck.sh --json     # JSON output
#
# Exit codes:
#   0 = all healthy
#   1 = warnings (degraded but functional)
#   2 = critical (something needs immediate attention)
# =============================================================================

set -uo pipefail

# ── Environment ──────────────────────────────────────────────────────────────
[[ -f /workspace/config/agent-env.sh ]] && source /workspace/config/agent-env.sh 2>/dev/null || true
[[ -f /workspace/config/generated-secrets.env ]] && source /workspace/config/generated-secrets.env 2>/dev/null || true

SUPERVISOR_CONF="/etc/supervisor/conf.d/conclave.conf"

# Credentials for authenticated services
NGINX_USER="${NGINX_USER:-admin}"
NGINX_PASSWORD="${NGINX_PASSWORD:-${CONCLAVE_ADMIN_PASSWORD:-}}"
CHROMADB_TOKEN="${AGENT_CHROMADB_TOKEN:-${CHROMADB_TOKEN:-}}"
TTYD_USER="${TTYD_USER:-admin}"
TTYD_PASSWORD="${TTYD_PASSWORD:-${CONCLAVE_ADMIN_PASSWORD:-}}"

JSON_MODE=false
[[ "${1:-}" == "--json" ]] && JSON_MODE=true

# ── Tracking ─────────────────────────────────────────────────────────────────
declare -A RESULTS   # service -> status (ok|warn|critical|down)
declare -A DETAILS   # service -> detail string
MAX_SEVERITY=0       # 0=ok, 1=warn, 2=critical

record() {
    local svc="$1" status="$2" detail="$3"
    RESULTS["$svc"]="$status"
    DETAILS["$svc"]="$detail"
    case "$status" in
        critical|down) [[ $MAX_SEVERITY -lt 2 ]] && MAX_SEVERITY=2 ;;
        warn)          [[ $MAX_SEVERITY -lt 1 ]] && MAX_SEVERITY=1 ;;
    esac
}

# ── Supervisor process check ────────────────────────────────────────────────
check_supervisor() {
    local name="$1"
    local proc_name="${2:-$name}"
    local status
    status=$(supervisorctl -c "$SUPERVISOR_CONF" status "$proc_name" 2>/dev/null | awk '{print $2}')
    if [[ "$status" == "RUNNING" ]]; then
        echo "RUNNING"
    else
        echo "${status:-UNKNOWN}"
    fi
}

# ── HTTP check ──────────────────────────────────────────────────────────────
check_http() {
    local name="$1" url="$2"
    shift 2
    local code
    code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "$@" "$url" 2>/dev/null || echo "000")
    if [[ "$code" =~ ^[23][0-9][0-9]$ ]]; then
        record "$name" ok "HTTP $code"
    elif [[ "$code" == "000" ]]; then
        record "$name" down "unreachable — $url"
    else
        record "$name" warn "HTTP $code — $url"
    fi
}

# ── Combined supervisor + HTTP check ────────────────────────────────────────
check_service() {
    local name="$1" url="$2" proc_name="${3:-$1}"
    local sup_status
    sup_status=$(check_supervisor "$name" "$proc_name")
    if [[ "$sup_status" != "RUNNING" ]]; then
        record "$name" critical "process $sup_status"
        return
    fi
    check_http "$name" "$url"
}

# ── 1. Core Infrastructure ──────────────────────────────────────────────────

# PostgreSQL — no HTTP, use pg_isready
pg_sup=$(check_supervisor postgres)
if [[ "$pg_sup" != "RUNNING" ]]; then
    record postgres critical "process $pg_sup"
elif pg_isready -q 2>/dev/null; then
    record postgres ok "running, accepting connections"
else
    record postgres warn "process running but not accepting connections"
fi

nginx_sup=$(check_supervisor nginx)
if [[ "$nginx_sup" != "RUNNING" ]]; then
    record nginx critical "process $nginx_sup"
elif [[ -n "$NGINX_PASSWORD" ]]; then
    check_http nginx "http://127.0.0.1:8888/" -u "${NGINX_USER}:${NGINX_PASSWORD}"
else
    check_http nginx "http://127.0.0.1:8888/"
fi

check_service synapse  "http://127.0.0.1:8008/_matrix/client/versions"

# ── 2. Application Services ─────────────────────────────────────────────────

chromadb_sup=$(check_supervisor chromadb)
if [[ "$chromadb_sup" != "RUNNING" ]]; then
    record chromadb critical "process $chromadb_sup"
elif [[ -n "$CHROMADB_TOKEN" ]]; then
    check_http chromadb "http://127.0.0.1:8000/api/v2/heartbeat" \
        -H "Authorization: Bearer ${CHROMADB_TOKEN}"
else
    check_http chromadb "http://127.0.0.1:8000/api/v2/heartbeat"
fi

check_service ollama   "http://127.0.0.1:11434/api/tags"
check_service planka   "http://127.0.0.1:1337/"

ttyd_sup=$(check_supervisor ttyd)
if [[ "$ttyd_sup" != "RUNNING" ]]; then
    record ttyd critical "process $ttyd_sup"
elif [[ -n "$TTYD_PASSWORD" ]]; then
    check_http ttyd "http://127.0.0.1:7681/" -u "${TTYD_USER}:${TTYD_PASSWORD}"
else
    check_http ttyd "http://127.0.0.1:7681/"
fi
check_service neko     "http://127.0.0.1:8080/"

# ── 3. Browser (CDP) ────────────────────────────────────────────────────────

chromium_sup=$(check_supervisor chromium)
if [[ "$chromium_sup" != "RUNNING" ]]; then
    record chromium-cdp critical "process $chromium_sup"
else
    cdp_code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" \
        "http://127.0.0.1:9222/json/version" 2>/dev/null || echo "000")
    if [[ "$cdp_code" =~ ^2[0-9][0-9]$ ]]; then
        record chromium-cdp ok "HTTP $cdp_code"
    else
        record chromium-cdp warn "process running but CDP HTTP $cdp_code"
    fi
fi

# ── 4. Disk ──────────────────────────────────────────────────────────────────

disk_line=$(df -h /workspace 2>/dev/null | tail -1)
if [[ -n "$disk_line" ]]; then
    disk_pct=$(echo "$disk_line" | awk '{gsub(/%/,""); print $5}')
    disk_avail=$(echo "$disk_line" | awk '{print $4}')
    if [[ "$disk_pct" -lt 80 ]]; then
        record disk ok "${disk_pct}% used (${disk_avail} free)"
    elif [[ "$disk_pct" -lt 90 ]]; then
        record disk warn "${disk_pct}% used (${disk_avail} free)"
    else
        record disk critical "${disk_pct}% used (${disk_avail} free)"
    fi
else
    record disk warn "could not read disk usage"
fi

# ── Output ───────────────────────────────────────────────────────────────────

SERVICE_ORDER=(postgres nginx synapse chromadb ollama planka ttyd neko chromium-cdp disk)

if $JSON_MODE; then
    echo "{"
    echo "  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
    echo "  \"max_severity\": $MAX_SEVERITY,"
    echo "  \"checks\": {"
    first=true
    for svc in "${SERVICE_ORDER[@]}"; do
        [[ -z "${RESULTS[$svc]:-}" ]] && continue
        $first || echo ","
        first=false
        # Escape any quotes in detail string
        detail="${DETAILS[$svc]//\"/\\\"}"
        printf '    "%s": {"status": "%s", "detail": "%s"}' \
            "$svc" "${RESULTS[$svc]}" "$detail"
    done
    echo ""
    echo "  }"
    echo "}"
else
    echo "=== Health Check — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    for svc in "${SERVICE_ORDER[@]}"; do
        [[ -z "${RESULTS[$svc]:-}" ]] && continue
        status="${RESULTS[$svc]}"
        case "$status" in
            ok)       icon="OK" ;;
            warn)     icon="WARN" ;;
            down)     icon="DOWN" ;;
            critical) icon="CRIT" ;;
            *)        icon="????" ;;
        esac
        printf "  %-4s  %-14s  %s\n" "$icon" "$svc" "${DETAILS[$svc]}"
    done
    echo ""
    case $MAX_SEVERITY in
        0) echo "All clear." ;;
        1) echo "Warnings present." ;;
        2) echo "CRITICAL issues detected." ;;
    esac
fi

exit $MAX_SEVERITY
