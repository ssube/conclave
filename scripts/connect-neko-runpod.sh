#!/bin/bash
# Connect to N.eko on a Runpod pod via SSH tunnel.
#
# Runpod remaps ports dynamically, so N.eko's WebRTC can't work directly.
# This script creates SSH tunnels for both the N.eko web UI (signaling)
# and TCPMUX (WebRTC media), then opens the local URL.
#
# Prerequisites:
#   The pod must be launched with these env vars to enable N.eko:
#     --env CONCLAVE_NEKO_ENABLED=true
#     --env NEKO_NAT1TO1=127.0.0.1
#     --env NEKO_TCPMUX_PORT=8081
#
# Usage:
#   bash scripts/connect-neko-runpod.sh <pod-id>

set -euo pipefail

POD_ID="${1:?Usage: connect-neko-runpod.sh <pod-id>}"

SSH_HOST="${POD_ID}-22.proxy.runpod.net"
NEKO_WEB_PORT=8080
NEKO_TCPMUX_PORT=8081

echo "=== N.eko SSH Tunnel ==="
echo ""
echo "  Tunneling:"
echo "    localhost:${NEKO_WEB_PORT}  -> ${SSH_HOST}:${NEKO_WEB_PORT}  (web UI / signaling)"
echo "    localhost:${NEKO_TCPMUX_PORT} -> ${SSH_HOST}:${NEKO_TCPMUX_PORT} (TCPMUX / WebRTC media)"
echo ""
echo "  Open in browser: http://localhost:${NEKO_WEB_PORT}/"
echo ""
echo "  Press Ctrl+C to disconnect."
echo ""

ssh -N \
    -L "${NEKO_WEB_PORT}:127.0.0.1:${NEKO_WEB_PORT}" \
    -L "${NEKO_TCPMUX_PORT}:127.0.0.1:${NEKO_TCPMUX_PORT}" \
    "root@${SSH_HOST}"
