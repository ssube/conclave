#!/bin/bash
# =============================================================================
# Conclave SSH Tunnel — forward all service ports to localhost
#
# Creates SSH tunnels for all Conclave services through a single SSH connection.
# No ports are exposed directly — all traffic goes through the SSH tunnel.
#
# For N.eko (WebRTC) to work through a tunnel, the container must be started
# with NEKO_NAT1TO1=127.0.0.1 and NEKO_TCPMUX_PORT=8081.
#
# Usage:
#   bash scripts/tunnel.sh local [container-name]
#   bash scripts/tunnel.sh k8s [namespace] [app-label]
#   bash scripts/tunnel.sh runpod <pod-id>
#
# Options:
#   --minimal   Skip full-image-only ports (Matrix, Ollama, Planka)
#   --no-neko   Skip N.eko ports (8080, 8081)
#
# Examples:
#   bash scripts/tunnel.sh local
#   bash scripts/tunnel.sh local conclave-dev
#   bash scripts/tunnel.sh k8s
#   bash scripts/tunnel.sh k8s conclave-agent
#   bash scripts/tunnel.sh k8s conclave-agent conclave-minimal
#   bash scripts/tunnel.sh runpod abc123xyz --minimal
#
# Once connected, services are available at:
#   http://localhost:8888       Dashboard (nginx)
#   http://localhost:8000       ChromaDB
#   http://localhost:7681       Terminal (ttyd)
#   http://localhost:9222       Chromium CDP
#   http://localhost:8080       N.eko web UI
#   http://localhost:8008       Matrix / Synapse  [full only]
#   http://localhost:11434      Ollama            [full only]
#   http://localhost:1337       Planka            [full only]
# =============================================================================

set -euo pipefail

MODE="${1:-}"
if [[ -z "$MODE" || "$MODE" == "--help" || "$MODE" == "-h" ]]; then
    sed -n '2,/^# ===/p' "$0" | grep '^#' | sed 's/^# \?//'
    exit 0
fi
shift

# ── Parse remaining args and flags ───────────────────────────────────────────

MINIMAL=false
NO_NEKO=false
POSITIONAL=()

for arg in "$@"; do
    case "$arg" in
        --minimal) MINIMAL=true ;;
        --no-neko) NO_NEKO=true ;;
        *)         POSITIONAL+=("$arg") ;;
    esac
done

# ── Resolve SSH connection details per mode ───────────────────────────────────

SSH_HOST=""
SSH_PORT=22
SSH_USER="dev"

case "$MODE" in
    local)
        CONTAINER="${POSITIONAL[0]:-conclave-dev}"
        # Find the mapped SSH port from the running container
        for runtime in docker podman nerdctl "sudo nerdctl" "sudo docker" "sudo podman"; do
            if SSH_PORT=$($runtime port "$CONTAINER" 22 2>/dev/null | head -1 | cut -d: -f2); then
                [[ -n "$SSH_PORT" ]] && break
            fi
        done
        SSH_PORT="${SSH_PORT:-2222}"
        SSH_HOST="127.0.0.1"
        echo "Mode: local (container: $CONTAINER, SSH port: $SSH_PORT)"
        ;;

    k8s)
        NAMESPACE="${POSITIONAL[0]:-conclave-agent}"
        APP_LABEL="${POSITIONAL[1]:-}"

        # Auto-detect pod type
        if [[ -z "$APP_LABEL" ]]; then
            for candidate in conclave-minimal conclave; do
                NODE_IP=$(kubectl -n "$NAMESPACE" get pod -l "app=$candidate" \
                    -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || true)
                if [[ -n "$NODE_IP" ]]; then
                    APP_LABEL="$candidate"
                    break
                fi
            done
            if [[ -z "$APP_LABEL" ]]; then
                echo "ERROR: No conclave or conclave-minimal pod found in namespace $NAMESPACE"
                exit 1
            fi
        else
            NODE_IP=$(kubectl -n "$NAMESPACE" get pod -l "app=$APP_LABEL" \
                -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || true)
            if [[ -z "$NODE_IP" ]]; then
                echo "ERROR: Could not find pod with app=$APP_LABEL in namespace $NAMESPACE"
                exit 1
            fi
        fi

        SSH_PORT=$(kubectl -n "$NAMESPACE" get svc "$APP_LABEL" \
            -o jsonpath='{.spec.ports[?(@.name=="ssh")].nodePort}' 2>/dev/null || true)
        # Fall back to searching services by selector
        if [[ -z "$SSH_PORT" ]]; then
            SSH_PORT=$(kubectl -n "$NAMESPACE" get svc \
                -o jsonpath="{.items[?(@.spec.selector.app=='$APP_LABEL')].spec.ports[?(@.name=='ssh')].nodePort}" \
                2>/dev/null | tr ' ' '\n' | head -1 || true)
        fi
        if [[ -z "$SSH_PORT" ]]; then
            echo "ERROR: Could not find SSH NodePort for $APP_LABEL in namespace $NAMESPACE"
            echo "  Try: kubectl get svc -n $NAMESPACE"
            exit 1
        fi

        SSH_HOST="$NODE_IP"
        echo "Mode: k8s (namespace: $NAMESPACE, pod: $APP_LABEL, node: $NODE_IP:$SSH_PORT)"
        ;;

    runpod)
        POD_ID="${POSITIONAL[0]:?runpod mode requires a pod ID}"
        : "${RUNPOD_API_KEY:?RUNPOD_API_KEY must be set for runpod mode}"
        SSH_USER="root"

        # Query the Runpod API for the pod's public IP and SSH port.
        # The HTTP proxy (pod-id-PORT.proxy.runpod.net) does not support raw
        # TCP, so SSH port forwarding requires the pod's direct public IP.
        PORTS_JSON=$(curl -sf "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "{\"query\": \"query { pod(input: { podId: \\\"${POD_ID}\\\" }) { runtime { ports { ip isIpPublic privatePort publicPort type } } } }\"}" \
            | jq '.data.pod.runtime.ports')

        SSH_HOST=$(echo "$PORTS_JSON" \
            | jq -r '[.[] | select(.isIpPublic == true and .privatePort == 22)] | first | .ip // empty')
        SSH_PORT=$(echo "$PORTS_JSON" \
            | jq -r '[.[] | select(.isIpPublic == true and .privatePort == 22)] | first | .publicPort // empty')

        if [[ -z "$SSH_HOST" || -z "$SSH_PORT" ]]; then
            echo "ERROR: Could not find public SSH port for pod $POD_ID"
            echo "  Check that the pod is running and has port 22 exposed."
            echo "  Raw ports: $(echo "$PORTS_JSON" | jq -c .)"
            exit 1
        fi

        echo "Mode: runpod (pod: $POD_ID, public SSH: $SSH_HOST:$SSH_PORT)"
        ;;

    *)
        echo "ERROR: Unknown mode '$MODE'. Use: local, k8s, or runpod"
        exit 1
        ;;
esac

# ── Build tunnel forwarding flags ─────────────────────────────────────────────

TUNNELS=()

# Always-on ports (both full and minimal images)
TUNNELS+=(
    -L "8888:127.0.0.1:8888"   # nginx / dashboard
    -L "8000:127.0.0.1:8000"   # ChromaDB
    -L "7681:127.0.0.1:7681"   # ttyd terminal
    -L "9222:127.0.0.1:9222"   # Chromium CDP
)

# N.eko (requires NEKO_NAT1TO1=127.0.0.1 and NEKO_TCPMUX_PORT=8081 in container)
if ! $NO_NEKO; then
    TUNNELS+=(
        -L "8080:127.0.0.1:8080"   # N.eko web UI / signaling
        -L "8081:127.0.0.1:8081"   # N.eko TCPMUX / WebRTC media
    )
fi

# Full-image-only ports
if ! $MINIMAL; then
    TUNNELS+=(
        -L "8008:127.0.0.1:8008"     # Matrix / Synapse
        -L "11434:127.0.0.1:11434"   # Ollama
        -L "1337:127.0.0.1:1337"     # Planka
    )
fi

# ── Fetch admin password from remote ──────────────────────────────────────────

ADMIN_PASS=$(ssh -p "$SSH_PORT" -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    "${SSH_USER}@${SSH_HOST}" \
    "grep CONCLAVE_ADMIN_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2" \
    2>/dev/null || true)

# ── Print summary and connect ─────────────────────────────────────────────────

echo ""
echo "=== Conclave SSH Tunnel ==="
echo ""
echo "  http://localhost:8888      Dashboard"
echo "  http://localhost:8000      ChromaDB"
echo "  http://localhost:7681      Terminal"
echo "  http://localhost:9222      Chromium CDP"
if ! $NO_NEKO; then
    echo "  http://localhost:8080      N.eko  (requires NEKO_NAT1TO1=127.0.0.1)"
fi
if ! $MINIMAL; then
    echo "  http://localhost:8008      Matrix"
    echo "  http://localhost:11434     Ollama"
    echo "  http://localhost:1337      Planka"
fi
echo ""
if [[ -n "$ADMIN_PASS" ]]; then
    echo "  Admin password: $ADMIN_PASS"
    echo ""
fi
echo "  Press Ctrl+C to disconnect."
echo ""

exec ssh -N -p "$SSH_PORT" "${TUNNELS[@]}" "${SSH_USER}@${SSH_HOST}"
