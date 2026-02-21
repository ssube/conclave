#!/bin/bash
# Pre-create the tmux workspace session so it's ready for ttyd connections.

# Source agent credentials into the environment
if [ -f /workspace/config/agent-env.sh ]; then
    set -a
    # shellcheck source=/dev/null
    source /workspace/config/agent-env.sh
    set +a
fi

SESSION="workspace"

# If session already exists, nothing to do
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already exists."
    exit 0
fi

# Create new session with 3 windows
tmux new-session -d -s "$SESSION" -n dev
tmux new-window -t "$SESSION" -n pi
tmux new-window -t "$SESSION" -n claude
tmux select-window -t "$SESSION":dev

echo "tmux session '$SESSION' created."
