#!/bin/bash
# Connect to N.eko on a Kubernetes deployment.
#
# N.eko uses NodePort for direct WebRTC access:
#   - HTTP/WebSocket signaling on NodePort (neko)
#   - TCPMUX (WebRTC media) on NodePort (neko-tcpmux)
#
# NEKO_TCPMUX inside the container is set to match the NodePort,
# so ICE candidates advertise the correct externally reachable port.
#
# Supports both the full (conclave) and minimal (conclave-minimal) pods.
#
# Usage:
#   bash scripts/connect-neko-k8s.sh [namespace]
#   bash scripts/connect-neko-k8s.sh [namespace] [app-label]
#
# Examples:
#   bash scripts/connect-neko-k8s.sh                          # conclave-agent ns, auto-detect pod
#   bash scripts/connect-neko-k8s.sh my-namespace             # custom namespace, auto-detect pod
#   bash scripts/connect-neko-k8s.sh my-namespace conclave    # explicit full pod

set -euo pipefail

NAMESPACE="${1:-conclave-agent}"
APP_LABEL="${2:-}"

# Auto-detect: try conclave-minimal first, then conclave
if [ -z "$APP_LABEL" ]; then
    for candidate in conclave-minimal conclave; do
        NODE_IP=$(kubectl -n "$NAMESPACE" get pod -l "app=$candidate" -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || true)
        if [ -n "$NODE_IP" ]; then
            APP_LABEL="$candidate"
            break
        fi
    done
    if [ -z "$APP_LABEL" ]; then
        echo "ERROR: No conclave or conclave-minimal pod found in namespace $NAMESPACE"
        exit 1
    fi
else
    NODE_IP=$(kubectl -n "$NAMESPACE" get pod -l "app=$APP_LABEL" -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || true)
    if [ -z "$NODE_IP" ]; then
        echo "ERROR: Could not find pod with app=$APP_LABEL in namespace $NAMESPACE"
        exit 1
    fi
fi

# Get the NodePorts for neko web and TCPMUX
NEKO_PORT=$(kubectl -n "$NAMESPACE" get svc "$APP_LABEL" -o jsonpath='{.spec.ports[?(@.name=="neko")].nodePort}' 2>/dev/null)
TCPMUX_PORT=$(kubectl -n "$NAMESPACE" get svc "$APP_LABEL" -o jsonpath='{.spec.ports[?(@.name=="neko-tcpmux")].nodePort}' 2>/dev/null)

if [ -z "$NEKO_PORT" ] || [ -z "$TCPMUX_PORT" ]; then
    echo "ERROR: Could not find neko/neko-tcpmux NodePorts on service $APP_LABEL"
    exit 1
fi

echo "=== N.eko Connection ==="
echo ""
echo "  Pod:     $APP_LABEL (namespace: $NAMESPACE)"
echo "  Web UI:  http://${NODE_IP}:${NEKO_PORT}/"
echo "  TCPMUX:  ${NODE_IP}:${TCPMUX_PORT}"
echo ""
echo "Open the Web UI URL in your browser to connect."
