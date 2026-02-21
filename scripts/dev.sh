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
        -p 8008:8008 \
        -p 8000:8000 \
        -p 11434:11434 \
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
    echo "  Dashboard:  http://localhost:8888       (nginx, all services)"
    echo "  Element:    http://localhost:8888/element/"
    echo "  Planka:     http://localhost:1337"
    echo "  N.eko:      http://localhost:8888/neko/"
    echo "  Terminal:   http://localhost:7681"
    echo "  ChromaDB:   http://localhost:8000"
    echo "  Ollama:     http://localhost:11434"
    echo "  Synapse:    http://localhost:8008"
    echo "  SSH:        ssh -p 2222 dev@localhost"
    echo ""
    echo "  Logs:       bash scripts/dev.sh logs"
    echo "  Stop:       bash scripts/dev.sh stop"

    # Wait for secrets to be generated, then print credentials
    echo ""
    echo "Waiting for first-boot setup to complete..."
    for _i in $(seq 1 30); do
        if "$CTR" exec "$CONTAINER" test -f /workspace/config/generated-secrets.env 2>/dev/null; then
            break
        fi
        sleep 2
    done

    MATRIX_PASS=$("$CTR" exec "$CONTAINER" sh -c 'grep ADMIN_MATRIX_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2' 2>/dev/null || true)
    if [ -n "$MATRIX_PASS" ]; then
        echo ""
        echo "=== Credentials ==="
        echo "  Dashboard/nginx:  ${NGINX_USER:-admin} / $NGINX_PASSWORD"
        echo "  Matrix (admin):   admin / $MATRIX_PASS"
        echo "  Planka (admin):   admin@local / changeme"
        echo "  N.eko (admin):    $NEKO_ADMIN_PASSWORD"
        echo "  ttyd:             $TTYD_USER / $TTYD_PASSWORD"
    fi
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
