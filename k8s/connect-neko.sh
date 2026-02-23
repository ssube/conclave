#!/bin/bash
# Port-forward N.eko from a Kubernetes pod for local browser access.
#
# N.eko requires two ports:
#   8080 — HTTP + WebSocket (signaling)
#   8081 — TCPMUX (WebRTC media transport)
#
# Usage:
#   bash k8s/connect-neko.sh [namespace]
#
# The script also verifies NEKO_NAT1TO1 is set to 127.0.0.1 inside the
# container, which is required for WebRTC ICE candidates to resolve
# locally. If not, it prints instructions to fix it.

set -euo pipefail

NAMESPACE="${1:-agent-severa}"
SERVICE="svc/conclave-minimal"

echo "Checking N.eko NAT1TO1 config..."
POD=$(kubectl -n "$NAMESPACE" get pod -l app=conclave-minimal -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$POD" ]; then
    NAT1TO1=$(kubectl -n "$NAMESPACE" exec "$POD" -- bash -c 'grep NEKO_NAT1TO1 /workspace/config/neko/.env 2>/dev/null' || true)
    if echo "$NAT1TO1" | grep -q "127.0.0.1"; then
        echo "  NAT1TO1=127.0.0.1 (OK)"
    else
        echo "  WARNING: $NAT1TO1"
        echo "  WebRTC may fail. Set EXTERNAL_HOSTNAME=127.0.0.1 in the secret"
        echo "  and restart the pod, or add NEKO_NAT1TO1=127.0.0.1 to the env."
        echo ""
    fi
fi

echo "Starting port-forward: $SERVICE in namespace $NAMESPACE"
echo "  8080 -> N.eko HTTP/WebSocket"
echo "  8081 -> N.eko TCPMUX (WebRTC media)"
echo ""
echo "Open http://localhost:8080 in your browser"
echo "Press Ctrl+C to stop"
echo ""

kubectl -n "$NAMESPACE" port-forward "$SERVICE" 8080 8081
