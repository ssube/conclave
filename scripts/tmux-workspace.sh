#!/bin/bash
# Launched by ttyd — sets up agent env and creates tmux workspace with named windows.
# If the session already exists (reconnect), just attach.

# Source agent credentials into the environment
if [ -f /workspace/config/agent-env.sh ]; then
    set -a
    # shellcheck source=/dev/null
    source /workspace/config/agent-env.sh
    set +a
fi

SESSION="workspace"

# If session exists, attach and exit
if tmux has-session -t "$SESSION" 2>/dev/null; then
    exec tmux attach-session -t "$SESSION"
fi

# Create new session with agent windows
tmux new-session -d -s "$SESSION" -n dev -c /workspace/data/coding/projects
tmux new-window -t "$SESSION" -n pi -c /workspace/data/coding/projects 'pi; exec bash'
tmux new-window -t "$SESSION" -n claude -c /workspace/data/coding/projects 'claude; exec bash'
tmux new-window -t "$SESSION" -n codex -c /workspace/data/coding/projects 'codex; exec bash'
tmux select-window -t "$SESSION":dev
exec tmux attach-session -t "$SESSION"
