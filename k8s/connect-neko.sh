#!/bin/bash
# Connect to N.eko from a local browser.
#
# N.eko uses NodePort for direct WebRTC access:
#   - HTTP/WebSocket signaling on NodePort 30080
#   - TCPMUX (WebRTC media) on NodePort 30181
#
# NEKO_TCPMUX inside the container is set to 30181 to match the NodePort,
# so ICE candidates advertise the correct externally reachable port.
#
# Usage:
#   bash k8s/connect-neko.sh [namespace]

set -euo pipefail

NAMESPACE="${1:-agent-severa}"

# Get the node IP where the pod is running
NODE_IP=$(kubectl -n "$NAMESPACE" get pod -l app=conclave-minimal -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null)
if [ -z "$NODE_IP" ]; then
    echo "ERROR: Could not find conclave-minimal pod in namespace $NAMESPACE"
    exit 1
fi

# Get the NodePort for the neko web service
NEKO_PORT=$(kubectl -n "$NAMESPACE" get svc conclave-minimal -o jsonpath='{.spec.ports[?(@.name=="neko")].nodePort}' 2>/dev/null)
TCPMUX_PORT=$(kubectl -n "$NAMESPACE" get svc conclave-minimal -o jsonpath='{.spec.ports[?(@.name=="neko-tcpmux")].nodePort}' 2>/dev/null)

echo "=== N.eko Connection ==="
echo ""
echo "  Web UI:  http://${NODE_IP}:${NEKO_PORT}/"
echo "  TCPMUX:  ${NODE_IP}:${TCPMUX_PORT}"
echo ""
echo "Open the Web UI URL in your browser to connect."
