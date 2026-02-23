#!/bin/bash
# Build and run the Conclave container locally for development.
# Compatible with docker, podman, and nerdctl.
#
# Usage:
#   bash scripts/dev.sh              # build, run, and test
#   bash scripts/dev.sh build        # build only
#   bash scripts/dev.sh run          # run only (image must exist)
#   bash scripts/dev.sh test         # run browser tests (container must be running)
#   bash scripts/dev.sh stop         # stop running container
#   bash scripts/dev.sh clean        # stop container and remove volume
#   bash scripts/dev.sh logs         # tail container logs
#   bash scripts/dev.sh creds        # print admin and agent passwords
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
: "${TTYD_USER:=admin}"

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
        -e TTYD_USER="$TTYD_USER" \
        -e EXTERNAL_HOSTNAME=localhost \
        ${CONCLAVE_ADMIN_PASSWORD:+-e CONCLAVE_ADMIN_PASSWORD="$CONCLAVE_ADMIN_PASSWORD"} \
        ${CONCLAVE_AGENT_PASSWORD:+-e CONCLAVE_AGENT_PASSWORD="$CONCLAVE_AGENT_PASSWORD"} \
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

    # Wait for user/resource creation to finish (Planka project, Matrix room)
    echo "Waiting for user and resource creation..."
    for _i in $(seq 1 60); do
        if "$CTR" exec "$CONTAINER" grep -q "User and resource creation complete" /workspace/logs/create-users.log 2>/dev/null; then
            echo "First-boot setup complete."
            break
        fi
        sleep 2
    done

    # Run end-to-end tests if playwright is available
    if [ -f "$REPO_DIR/scripts/test-e2e.mjs" ] && command -v node &>/dev/null; then
        # Ensure Playwright Chromium is installed locally
        npx playwright install chromium 2>/dev/null || true
        echo ""
        echo "=== Running E2E tests ==="
        local test_flags=""
        if [[ "$IMAGE" == *"minimal"* ]]; then
            test_flags="--minimal"
        fi
        if node "$REPO_DIR/scripts/test-e2e.mjs" $test_flags; then
            echo "=== All E2E tests passed ==="
        else
            echo "WARNING: Some E2E tests failed (see output above)."
        fi
    fi

    ADMIN_PASS=$("$CTR" exec "$CONTAINER" sh -c 'grep CONCLAVE_ADMIN_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2' 2>/dev/null || true)
    AGENT_PASS=$("$CTR" exec "$CONTAINER" sh -c 'grep CONCLAVE_AGENT_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2' 2>/dev/null || true)
    if [ -n "$ADMIN_PASS" ]; then
        echo ""
        echo "=== Credentials ==="
        echo "  Admin password:   $ADMIN_PASS  (nginx, Matrix, Planka, Neko, ttyd, dev SSH)"
        echo "  Agent password:   $AGENT_PASS  (Matrix agent, Planka agent)"
    fi
}

do_test() {
    if [ -f "$REPO_DIR/scripts/test-e2e.mjs" ] && command -v node &>/dev/null; then
        # Ensure Playwright Chromium is installed locally
        if ! npx playwright install chromium 2>/dev/null; then
            echo "WARNING: Could not install Playwright Chromium." >&2
        fi
        echo "=== Running E2E tests ==="
        local test_flags=""
        if [[ "$IMAGE" == *"minimal"* ]]; then
            test_flags="--minimal"
        fi
        node "$REPO_DIR/scripts/test-e2e.mjs" $test_flags "$@"
    else
        echo "ERROR: E2E test script not found or node not available." >&2
        exit 1
    fi
}

do_stop() {
    echo "=== Stopping $CONTAINER ==="
    "$CTR" stop "$CONTAINER" 2>/dev/null && "$CTR" rm "$CONTAINER" 2>/dev/null || echo "Container not running"
}

do_clean() {
    echo "=== Cleaning up $CONTAINER ==="
    "$CTR" stop "$CONTAINER" 2>/dev/null && "$CTR" rm "$CONTAINER" 2>/dev/null || true
    "$CTR" volume rm "$WORKSPACE_VOL" 2>/dev/null || true
    echo "Container and volume removed."
}

do_logs() {
    "$CTR" logs -f "$CONTAINER"
}

do_creds() {
    ADMIN_PASS=$("$CTR" exec "$CONTAINER" sh -c 'grep CONCLAVE_ADMIN_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2' 2>/dev/null || true)
    AGENT_PASS=$("$CTR" exec "$CONTAINER" sh -c 'grep CONCLAVE_AGENT_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2' 2>/dev/null || true)
    if [ -n "$ADMIN_PASS" ]; then
        echo "Admin password:   $ADMIN_PASS  (nginx, Matrix, Planka, Neko, ttyd, dev SSH)"
        echo "Agent password:   $AGENT_PASS  (Matrix agent, Planka agent)"
    else
        echo "ERROR: Could not read credentials. Is the container running?" >&2
        exit 1
    fi
}

case "${1:-}" in
    build) do_build ;;
    run)   do_run ;;
    test)  do_test ;;
    stop)  do_stop ;;
    clean) do_clean ;;
    logs)  do_logs ;;
    creds) do_creds ;;
    "")    do_build && do_run ;;
    *)     echo "Usage: $0 [build|run|test|stop|clean|logs|creds]"; exit 1 ;;
esac
