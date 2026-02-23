#!/bin/bash
# Helper script for E2E tests — runs a skill command with the agent environment loaded.
# Baked into the container image to avoid shell quoting issues with docker/nerdctl exec.
#
# Usage: e2e-skill-test.sh <skill-dir> <command...>
# Example: e2e-skill-test.sh /opt/conclave/pi/skills/planka python3 planka.py boards
set -euo pipefail

SKILL_DIR="$1"
shift

# Load agent environment
set -a
[[ -f /workspace/config/agent-env.sh ]] && source /workspace/config/agent-env.sh 2>/dev/null || true
set +a

cd "$SKILL_DIR"
exec "$@"
