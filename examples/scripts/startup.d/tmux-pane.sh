#!/bin/bash
# Example startup.d script: create a new tmux pane in the workspace session.
#
# Copy this to /workspace/config/startup.d/ and edit the COMMAND variable.
# The pane is created as a horizontal split in the "dev" window.
#
# Startup scripts run as root before supervisord, but the tmux session is
# owned by the dev user, so we use su to run tmux commands as dev.

SESSION="workspace"
WINDOW="dev"
COMMAND="htop"

# Wait for the tmux session to exist (created by supervisord's tmux-session program)
for i in $(seq 1 30); do
    if su - dev -c "tmux has-session -t '$SESSION'" 2>/dev/null; then
        break
    fi
    sleep 1
done

if ! su - dev -c "tmux has-session -t '$SESSION'" 2>/dev/null; then
    echo "WARN: tmux session '$SESSION' not found, skipping pane creation"
    exit 0
fi

su - dev -c "tmux split-window -t '$SESSION:$WINDOW' -v -c /workspace/data/coding/projects '$COMMAND'"
