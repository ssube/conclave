#!/bin/bash
# Build and run the Conclave container locally for development.
# Compatible with docker, podman, and nerdctl.
#
# Usage:
#   bash scripts/dev.sh              # build and run
#   bash scripts/dev.sh build        # build only
#   bash scripts/dev.sh run          # run only (image must exist)
#   bash scripts/dev.sh stop         # stop running container
#   bash scripts/dev.sh logs         # tail container logs
#
# Override the container runtime with CONTAINER_RUNTIME=podman, etc.
set -euo pipefail

IMAGE="conclave:dev"
CONTAINER="conclave-dev"
WORKSPACE_VOL="conclave-dev-workspace"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Auto-detect container runtime: prefer $CONTAINER_RUNTIME, then docker, podman, nerdctl
if [ -n "${CONTAINER_RUNTIME:-}" ]; then
    CTR="$CONTAINER_RUNTIME"
elif command -v docker &>/dev/null; then
    CTR=docker
elif command -v podman &>/dev/null; then
    CTR=podman
elif command -v nerdctl &>/dev/null; then
    CTR=nerdctl
else
    echo "ERROR: No container runtime found. Install docker, podman, or nerdctl." >&2
    exit 1
fi
echo "Using container runtime: $CTR"

# Default env vars for local development
: "${NGINX_PASSWORD:=admin}"
: "${TTYD_USER:=admin}"
: "${TTYD_PASSWORD:=$NGINX_PASSWORD}"
: "${NEKO_PASSWORD:=neko}"
: "${NEKO_ADMIN_PASSWORD:=admin}"

do_build() {
    echo "=== Building $IMAGE ==="
    "$CTR" build -t "$IMAGE" "$REPO_DIR"
}

do_run() {
    # Remove existing container if present (works across docker/podman/nerdctl)
    if "$CTR" inspect "$CONTAINER" &>/dev/null; then
        echo "Removing existing container..."
        "$CTR" rm -f "$CONTAINER"
    fi

    echo "=== Running $CONTAINER ==="
    "$CTR" run -d \
        --name "$CONTAINER" \
        -p 8888:8888 \
        -p 2222:22 \
        -p 7681:7681 \
        -p 1337:1337 \
        -p 8081:8081 \
        -v "${WORKSPACE_VOL}:/workspace" \
        -e NGINX_PASSWORD="$NGINX_PASSWORD" \
        -e TTYD_USER="$TTYD_USER" \
        -e TTYD_PASSWORD="$TTYD_PASSWORD" \
        -e NEKO_PASSWORD="$NEKO_PASSWORD" \
        -e NEKO_ADMIN_PASSWORD="$NEKO_ADMIN_PASSWORD" \
        -e EXTERNAL_HOSTNAME=localhost \
        ${SSH_AUTHORIZED_KEYS:+-e SSH_AUTHORIZED_KEYS="$SSH_AUTHORIZED_KEYS"} \
        "$IMAGE"

    echo ""
    echo "Container started: $CONTAINER"
    echo "  Dashboard: http://localhost:8888"
    echo "  ttyd:      http://localhost:7681"
    echo "  SSH:       ssh -p 2222 dev@localhost"
    echo ""
    echo "  Logs:      bash scripts/dev.sh logs"
    echo "  Stop:      bash scripts/dev.sh stop"
}

do_stop() {
    echo "=== Stopping $CONTAINER ==="
    "$CTR" stop "$CONTAINER" 2>/dev/null && "$CTR" rm "$CONTAINER" 2>/dev/null || echo "Container not running"
}

do_logs() {
    "$CTR" logs -f "$CONTAINER"
}

case "${1:-}" in
    build) do_build ;;
    run)   do_run ;;
    stop)  do_stop ;;
    logs)  do_logs ;;
    "")    do_build && do_run ;;
    *)     echo "Usage: $0 [build|run|stop|logs]"; exit 1 ;;
esac
