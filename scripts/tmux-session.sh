#!/bin/bash
# Pre-create the tmux workspace session so it's ready for ttyd/SSH connections.
# Each agent tab starts its respective coding CLI.

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

# Create new session with agent windows
tmux new-session -d -s "$SESSION" -n dev -c /workspace/data/coding/projects
tmux new-window -t "$SESSION" -n pi -c /workspace/data/coding/projects 'pi; exec bash'
tmux new-window -t "$SESSION" -n claude -c /workspace/data/coding/projects 'claude; exec bash'
tmux new-window -t "$SESSION" -n codex -c /workspace/data/coding/projects 'codex; exec bash'
tmux select-window -t "$SESSION":dev

echo "tmux session '$SESSION' created with dev, pi, claude, and codex windows."
