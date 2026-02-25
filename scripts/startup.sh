#!/bin/bash
set -euo pipefail

WORKSPACE="/workspace"
SECRETS_FILE="$WORKSPACE/config/generated-secrets.env"

# ---------------------------------------------------------------
# 1. Source existing secrets if present
# ---------------------------------------------------------------
if [ -f "$SECRETS_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_FILE"
    set +a
fi

# ---------------------------------------------------------------
# 2. Create directory tree (idempotent)
# ---------------------------------------------------------------
mkdir -p "$WORKSPACE"/{config,data,logs}
mkdir -p "$WORKSPACE"/config/{nginx,synapse,element-web,planka,chromadb,neko,ssh,cron,startup.d,supervisor.d}
mkdir -p "$WORKSPACE"/data/{synapse/media_store,postgres,planka,chromadb,ollama/models,neko/chromium-profile,coding/.pi/agent/{skills,agents,prompts,extensions,themes},coding/.claude,coding/projects}
mkdir -p "$WORKSPACE"/logs/{nginx,synapse,postgres,planka,chromadb,ollama,neko,ttyd,pushgateway,cron}

# Ensure dev user owns coding workspace
chown -R dev:dev "$WORKSPACE/data/coding/"

# ---------------------------------------------------------------
# 3. Defaults for optional env vars (needed by init scripts)
# ---------------------------------------------------------------

# Timezone
export TZ="${TZ:-UTC}"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

# Service enablement flags (default true for backward compat with full image)
export CONCLAVE_PUSHGATEWAY_ENABLED="${CONCLAVE_PUSHGATEWAY_ENABLED:-true}"
export CONCLAVE_CRON_ENABLED="${CONCLAVE_CRON_ENABLED:-true}"
export CONCLAVE_POSTGRES_ENABLED="${CONCLAVE_POSTGRES_ENABLED:-true}"
export CONCLAVE_SYNAPSE_ENABLED="${CONCLAVE_SYNAPSE_ENABLED:-true}"
export CONCLAVE_ELEMENT_WEB_ENABLED="${CONCLAVE_ELEMENT_WEB_ENABLED:-true}"
export CONCLAVE_PLANKA_ENABLED="${CONCLAVE_PLANKA_ENABLED:-true}"
export CONCLAVE_OLLAMA_ENABLED="${CONCLAVE_OLLAMA_ENABLED:-true}"

export CONCLAVE_AGENT_USER="${CONCLAVE_AGENT_USER:-agent}"
export MATRIX_SERVER_NAME="${MATRIX_SERVER_NAME:-conclave.local}"

# Runpod detection: auto-configure hostname
# N.eko WebRTC requires direct port access (matching internal/external ports).
# Runpod remaps all TCP ports dynamically, so N.eko streaming is not available.
# The browser is still usable via CDP (port 9222) for automation.
if [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_PUBLIC_IP:-}" ]; then
    export EXTERNAL_HOSTNAME="${EXTERNAL_HOSTNAME:-${RUNPOD_PUBLIC_IP}}"
    export CONCLAVE_NEKO_ENABLED="${CONCLAVE_NEKO_ENABLED:-false}"
else
    export EXTERNAL_HOSTNAME="${EXTERNAL_HOSTNAME:-localhost}"
fi
export CONCLAVE_NEKO_ENABLED="${CONCLAVE_NEKO_ENABLED:-true}"

export CONCLAVE_BASE_URL="${CONCLAVE_BASE_URL:-http://${EXTERNAL_HOSTNAME}:8888}"
export NGINX_USER="${NGINX_USER:-admin}"
export TTYD_USER="${TTYD_USER:-admin}"
export NEKO_TCPMUX_PORT="${NEKO_TCPMUX_PORT:-8081}"
NEKO_NAT1TO1="${NEKO_NAT1TO1:-${EXTERNAL_HOSTNAME}}"
# Neko requires an IPv4 address for NAT1TO1, resolve hostnames
if echo "$NEKO_NAT1TO1" | grep -qP '^[a-zA-Z]'; then
    _resolved=$(getent ahostsv4 "$NEKO_NAT1TO1" 2>/dev/null | awk '{print $1}' | head -1)
    if [ -n "$_resolved" ]; then
        NEKO_NAT1TO1="$_resolved"
    fi
fi
export NEKO_NAT1TO1
export PLANKA_ADMIN_EMAIL="${PLANKA_ADMIN_EMAIL:-admin@local}"
export DEFAULT_OLLAMA_MODEL="${DEFAULT_OLLAMA_MODEL:-qwen3-coder:30b-a3b-q8_0}"

# ---------------------------------------------------------------
# 4. First boot: generate secrets + init services
# ---------------------------------------------------------------
if [ ! -f "$WORKSPACE/.initialized" ]; then
    echo "=== First boot detected ==="

    # Generate secrets for anything not already in env
    # Export so child scripts (init-postgres.sh, init-synapse.sh) can use them
    export CONCLAVE_ADMIN_PASSWORD="${CONCLAVE_ADMIN_PASSWORD:-$(openssl rand -hex 16)}"
    export CONCLAVE_AGENT_PASSWORD="${CONCLAVE_AGENT_PASSWORD:-$(openssl rand -hex 16)}"
    export SYNAPSE_DB_PASSWORD="${SYNAPSE_DB_PASSWORD:-$(openssl rand -hex 32)}"
    export PLANKA_DB_PASSWORD="${PLANKA_DB_PASSWORD:-$(openssl rand -hex 32)}"
    export PLANKA_SECRET_KEY="${PLANKA_SECRET_KEY:-$(openssl rand -hex 32)}"
    export CHROMADB_TOKEN="${CHROMADB_TOKEN:-$(openssl rand -hex 32)}"
    export SYNAPSE_REGISTRATION_SHARED_SECRET="${SYNAPSE_REGISTRATION_SHARED_SECRET:-$(openssl rand -hex 32)}"
    export SYNAPSE_MACAROON_SECRET_KEY="${SYNAPSE_MACAROON_SECRET_KEY:-$(openssl rand -hex 32)}"
    export SYNAPSE_FORM_SECRET="${SYNAPSE_FORM_SECRET:-$(openssl rand -hex 32)}"
    export SYNAPSE_SIGNING_KEY="$(openssl rand -hex 32)"

    cat > "$SECRETS_FILE" <<SECRETS_EOF
CONCLAVE_ADMIN_PASSWORD=$CONCLAVE_ADMIN_PASSWORD
CONCLAVE_AGENT_PASSWORD=$CONCLAVE_AGENT_PASSWORD
SYNAPSE_DB_PASSWORD=$SYNAPSE_DB_PASSWORD
PLANKA_DB_PASSWORD=$PLANKA_DB_PASSWORD
PLANKA_SECRET_KEY=$PLANKA_SECRET_KEY
CHROMADB_TOKEN=$CHROMADB_TOKEN
SYNAPSE_REGISTRATION_SHARED_SECRET=$SYNAPSE_REGISTRATION_SHARED_SECRET
SYNAPSE_MACAROON_SECRET_KEY=$SYNAPSE_MACAROON_SECRET_KEY
SYNAPSE_FORM_SECRET=$SYNAPSE_FORM_SECRET
SECRETS_EOF
    chmod 600 "$SECRETS_FILE"

    # Initialize PostgreSQL (only if local postgres is enabled)
    if [ "$CONCLAVE_POSTGRES_ENABLED" = "true" ]; then
        /opt/conclave/scripts/init-postgres.sh
    fi

    # Initialize Synapse config (only if local synapse is enabled)
    if [ "$CONCLAVE_SYNAPSE_ENABLED" = "true" ]; then
        /opt/conclave/scripts/init-synapse.sh
    fi
fi

# ---------------------------------------------------------------
# 5. Every boot: render config templates + setup
# ---------------------------------------------------------------

# Re-source secrets (they exist now whether first boot or not)
set -a
# shellcheck source=/dev/null
source "$SECRETS_FILE"
set +a

# Update dev user password (falls back to admin password)
CONCLAVE_DEV_PASSWORD="${CONCLAVE_DEV_PASSWORD:-$CONCLAVE_ADMIN_PASSWORD}"
echo "dev:${CONCLAVE_DEV_PASSWORD}" | chpasswd

# Clean up stale Chromium profile lock files from previous container runs
rm -f "$WORKSPACE/data/neko/chromium-profile/SingletonLock" \
      "$WORKSPACE/data/neko/chromium-profile/SingletonSocket" \
      "$WORKSPACE/data/neko/chromium-profile/SingletonCookie"

# Copy nginx config (no envsubst — template only contains nginx $variables)
cp /opt/conclave/configs/nginx/nginx.conf.template "$WORKSPACE/config/nginx/nginx.conf"

# Generate htpasswd (use NGINX_PASSWORD override if set, otherwise admin password)
NGINX_PASSWORD="${NGINX_PASSWORD:-$CONCLAVE_ADMIN_PASSWORD}"
htpasswd -bc "$WORKSPACE/config/nginx/htpasswd" "$NGINX_USER" "$NGINX_PASSWORD" 2>/dev/null

# Render Element Web config and symlink into app directory
if [ "$CONCLAVE_ELEMENT_WEB_ENABLED" = "true" ]; then
    envsubst < /opt/conclave/configs/element-web/config.json.template > "$WORKSPACE/config/element-web/config.json"
    ln -sf "$WORKSPACE/config/element-web/config.json" /opt/element-web/config.json
fi

# Write Planka env and symlink into app directory (dotenv loads from cwd)
if [ "$CONCLAVE_PLANKA_ENABLED" = "true" ]; then
    cat > "$WORKSPACE/config/planka/.env" <<PLANKA_EOF
BASE_URL=http://${EXTERNAL_HOSTNAME}:1337,http://127.0.0.1:1337,${CONCLAVE_BASE_URL}/planka
DATABASE_URL=postgresql://planka:${PLANKA_DB_PASSWORD}@127.0.0.1:5432/planka
SECRET_KEY=${PLANKA_SECRET_KEY}
DEFAULT_ADMIN_EMAIL=${PLANKA_ADMIN_EMAIL}
DEFAULT_ADMIN_PASSWORD=${CONCLAVE_ADMIN_PASSWORD}
DEFAULT_ADMIN_NAME=Admin
DEFAULT_ADMIN_USERNAME=admin
TRUST_PROXY=true
PLANKA_EOF
    ln -sf "$WORKSPACE/config/planka/.env" /opt/planka/.env
fi

# Write ChromaDB env
cat > "$WORKSPACE/config/chromadb/.env" <<CHROMA_EOF
IS_PERSISTENT=TRUE
PERSIST_DIRECTORY=/workspace/data/chromadb
ANONYMIZED_TELEMETRY=FALSE
CHROMA_SERVER_AUTHN_CREDENTIALS=${CHROMADB_TOKEN}
CHROMA_SERVER_AUTHN_PROVIDER=chromadb.auth.token_authn.TokenAuthenticationServerProvider
CHROMA_EOF

# Write Neko env (viewer and admin both use admin password)
NEKO_PASSWORD="${NEKO_PASSWORD:-$CONCLAVE_ADMIN_PASSWORD}"
cat > "$WORKSPACE/config/neko/.env" <<NEKO_EOF
NEKO_SCREEN=1920x1080@30
NEKO_PASSWORD=${NEKO_PASSWORD}
NEKO_PASSWORD_ADMIN=${CONCLAVE_ADMIN_PASSWORD}
NEKO_BIND=0.0.0.0:8080
NEKO_TCPMUX=${NEKO_TCPMUX_PORT}
NEKO_ICELITE=true
NEKO_NAT1TO1=${NEKO_NAT1TO1}
NEKO_EOF

# Resolve service URLs (local or external)
if [ "$CONCLAVE_SYNAPSE_ENABLED" = "true" ]; then
    _MATRIX_HOMESERVER_URL="http://127.0.0.1:8008"
    _AGENT_MATRIX_URL="${CONCLAVE_BASE_URL}"
else
    _MATRIX_HOMESERVER_URL="${EXTERNAL_MATRIX_URL:-}"
    _AGENT_MATRIX_URL="${EXTERNAL_MATRIX_URL:-}"
fi
if [ "$CONCLAVE_PLANKA_ENABLED" = "true" ]; then
    _AGENT_PLANKA_URL="${CONCLAVE_BASE_URL}/planka"
else
    _AGENT_PLANKA_URL="${EXTERNAL_PLANKA_URL:-}"
fi
if [ "$CONCLAVE_OLLAMA_ENABLED" = "true" ]; then
    _AGENT_OLLAMA_URL="http://127.0.0.1:11434"
else
    _AGENT_OLLAMA_URL="${EXTERNAL_OLLAMA_URL:-}"
fi
if [ "$CONCLAVE_PUSHGATEWAY_ENABLED" = "true" ]; then
    _AGENT_PUSHGATEWAY_URL="http://127.0.0.1:9091"
else
    _AGENT_PUSHGATEWAY_URL="${EXTERNAL_PUSHGATEWAY_URL:-}"
fi

# Write agent credentials env file (for coding agents in tmux)
AGENT_ENV_FILE="$WORKSPACE/config/agent-env.sh"
cat > "$AGENT_ENV_FILE" <<AGENT_EOF
# Conclave agent credentials — sourced into tmux sessions
AGENT_MATRIX_USER=${CONCLAVE_AGENT_USER}
AGENT_MATRIX_PASSWORD=${CONCLAVE_AGENT_PASSWORD}
AGENT_MATRIX_URL=${_AGENT_MATRIX_URL}
AGENT_MATRIX_SERVER_NAME=${MATRIX_SERVER_NAME}
AGENT_PLANKA_USER=${CONCLAVE_AGENT_USER}
AGENT_PLANKA_EMAIL=${CONCLAVE_AGENT_USER}@local
AGENT_PLANKA_PASSWORD=${CONCLAVE_AGENT_PASSWORD}
AGENT_PLANKA_URL=${_AGENT_PLANKA_URL}
AGENT_NEKO_PASSWORD=${CONCLAVE_ADMIN_PASSWORD}
AGENT_CHROMADB_TOKEN=${CHROMADB_TOKEN}
AGENT_CHROMADB_URL=http://127.0.0.1:8000
AGENT_OLLAMA_URL=${_AGENT_OLLAMA_URL}
AGENT_PUSHGATEWAY_URL=${_AGENT_PUSHGATEWAY_URL}
MATRIX_HOMESERVER_URL=${_MATRIX_HOMESERVER_URL}
MATRIX_SERVER_NAME=${MATRIX_SERVER_NAME}
MATRIX_SKILL_PATH=/workspace/data/coding/.pi/agent/skills/matrix
AGENT_EOF
chmod 600 "$AGENT_ENV_FILE"
chown dev:dev "$AGENT_ENV_FILE"

# SSH authorized_keys for dev user
if [ -n "${SSH_AUTHORIZED_KEYS:-}" ]; then
    mkdir -p /workspace/data/coding/.ssh
    echo "$SSH_AUTHORIZED_KEYS" > /workspace/data/coding/.ssh/authorized_keys
    chmod 700 /workspace/data/coding/.ssh
    chmod 600 /workspace/data/coding/.ssh/authorized_keys
    chown -R dev:dev /workspace/data/coding/.ssh
fi

# Sync pi assets (don't overwrite user edits for prompts/themes)
rsync -a --ignore-existing /opt/conclave/pi/skills/ "$WORKSPACE/data/coding/.pi/agent/skills/" 2>/dev/null || true
rsync -a --ignore-existing /opt/conclave/pi/extensions/ "$WORKSPACE/data/coding/.pi/agent/extensions/" 2>/dev/null || true

# Share Pi skills and agents with Claude Code and Codex via symlinks.
# Pi is the canonical source. All three tools use the same SKILL.md format
# (Agent Skills standard), and Pi/Claude Code share the same agent .md format.
#   Skills:  Pi .pi/agent/skills/ → Claude Code .claude/skills/, Codex .agents/skills/
#   Agents:  Pi .pi/agent/agents/ → Claude Code .claude/agents/
CODING_HOME="$WORKSPACE/data/coding"
rm -rf "$CODING_HOME/.claude/skills" "$CODING_HOME/.claude/agents"
ln -sfn ../.pi/agent/skills "$CODING_HOME/.claude/skills"
ln -sfn ../.pi/agent/agents "$CODING_HOME/.claude/agents"
mkdir -p "$CODING_HOME/projects/.agents"
ln -sfn ../../.pi/agent/skills "$CODING_HOME/projects/.agents/skills"

# Copy pi-models.json and tmux.conf if not present (don't overwrite user edits)
cp -n /opt/conclave/configs/coding/pi-models.json "$WORKSPACE/data/coding/.pi/agent/models.json" 2>/dev/null || true
cp -n /opt/conclave/configs/coding/pi-settings.json "$WORKSPACE/data/coding/.pi/settings.json" 2>/dev/null || true
cp -n /opt/conclave/configs/coding/tmux.conf "$WORKSPACE/data/coding/.tmux.conf" 2>/dev/null || true

# Also place pi settings and cron.tab in the projects directory (pi's launch cwd)
# so extensions find them regardless of whether pi walks up to discover .pi/
mkdir -p "$WORKSPACE/data/coding/projects/.pi"
cp -n /opt/conclave/configs/coding/pi-settings.json "$WORKSPACE/data/coding/projects/.pi/settings.json" 2>/dev/null || true
cp -n /opt/conclave/configs/coding/cron.tab "$WORKSPACE/data/coding/.pi/cron.tab" 2>/dev/null || true
cp -n /opt/conclave/configs/coding/cron.tab "$WORKSPACE/data/coding/projects/.pi/cron.tab" 2>/dev/null || true

# Re-chown coding dir after syncing assets (rsync/cp run as root)
chown -R dev:dev "$WORKSPACE/data/coding/"

# Install user crontab from persistent volume if present
if [ "$CONCLAVE_CRON_ENABLED" = "true" ] && [ -f "$WORKSPACE/config/cron/crontab" ]; then
    crontab -u dev "$WORKSPACE/config/cron/crontab"
fi

# Generate dashboard env.json
cat > /opt/dashboard/env.json <<ENV_EOF
{
    "MATRIX_SERVER_NAME": "${MATRIX_SERVER_NAME}",
    "EXTERNAL_HOSTNAME": "${EXTERNAL_HOSTNAME}",
    "services": {
        "synapse": ${CONCLAVE_SYNAPSE_ENABLED},
        "element_web": ${CONCLAVE_ELEMENT_WEB_ENABLED},
        "postgres": ${CONCLAVE_POSTGRES_ENABLED},
        "planka": ${CONCLAVE_PLANKA_ENABLED},
        "chromadb": true,
        "ollama": ${CONCLAVE_OLLAMA_ENABLED},
        "pushgateway": ${CONCLAVE_PUSHGATEWAY_ENABLED},
        "neko": ${CONCLAVE_NEKO_ENABLED},
        "ttyd": true,
        "ssh": true
    }
}
ENV_EOF

# ---------------------------------------------------------------
# 6. Mark initialized
# ---------------------------------------------------------------
touch "$WORKSPACE/.initialized"

# ---------------------------------------------------------------
# 7. Export env vars needed by supervisord programs
# ---------------------------------------------------------------
TTYD_PASSWORD="${TTYD_PASSWORD:-$CONCLAVE_ADMIN_PASSWORD}"
export TTYD_USER TTYD_PASSWORD
export NEKO_PASSWORD NEKO_TCPMUX_PORT NEKO_NAT1TO1
export CONCLAVE_AGENT_USER

# Assemble optional supervisord service configs
SUPERVISOR_SERVICES_DIR="/etc/supervisor/conf.d/services"
mkdir -p "$SUPERVISOR_SERVICES_DIR"
rm -f "$SUPERVISOR_SERVICES_DIR"/*.conf

SUPERVISOR_OPTIONAL_DIR="/opt/conclave/configs/supervisor.d"
[ "$CONCLAVE_POSTGRES_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/postgres.conf" "$SUPERVISOR_SERVICES_DIR/"
[ "$CONCLAVE_SYNAPSE_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/synapse.conf" "$SUPERVISOR_SERVICES_DIR/"
[ "$CONCLAVE_PLANKA_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/planka.conf" "$SUPERVISOR_SERVICES_DIR/"
[ "$CONCLAVE_OLLAMA_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/ollama.conf" "$SUPERVISOR_SERVICES_DIR/"
[ "$CONCLAVE_PUSHGATEWAY_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/pushgateway.conf" "$SUPERVISOR_SERVICES_DIR/"
[ "$CONCLAVE_CRON_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/cron.conf" "$SUPERVISOR_SERVICES_DIR/"
[ "$CONCLAVE_NEKO_ENABLED" = "true" ] && cp "$SUPERVISOR_OPTIONAL_DIR/neko.conf" "$SUPERVISOR_SERVICES_DIR/"
if [ "$CONCLAVE_SYNAPSE_ENABLED" = "true" ] || [ "$CONCLAVE_PLANKA_ENABLED" = "true" ]; then
    cp "$SUPERVISOR_OPTIONAL_DIR/create-users.conf" "$SUPERVISOR_SERVICES_DIR/"
fi

# Source Neko and ChromaDB envs for supervisord
set -a
source "$WORKSPACE/config/neko/.env"
source "$WORKSPACE/config/chromadb/.env"
set +a

# ---------------------------------------------------------------
# 8. Launch supervisord as PID 1
# ---------------------------------------------------------------
if [ "${CONCLAVE_SETUP_ONLY:-}" = "1" ]; then
    echo "=== Setup complete (CONCLAVE_SETUP_ONLY=1, skipping supervisord) ==="
    exit 0
fi

# Ensure runtime directories exist (tmpfs clears /var/run on container start)
mkdir -p /var/run/dbus

# ---------------------------------------------------------------
# 9. Run user startup scripts from /workspace/config/startup.d/
# ---------------------------------------------------------------
STARTUP_TIMEOUT="${CONCLAVE_STARTUP_TIMEOUT:-60}"
if [ -d "$WORKSPACE/config/startup.d" ]; then
    for script in "$WORKSPACE/config/startup.d"/*.sh; do
        [ -f "$script" ] || continue
        echo "=== Running user script: $script ==="
        timeout "$STARTUP_TIMEOUT" bash "$script" &
        SCRIPT_PID=$!
        if wait "$SCRIPT_PID" 2>/dev/null; then
            echo "=== OK: $script ==="
        else
            EXIT_CODE=$?
            if [ "$EXIT_CODE" -eq 124 ]; then
                echo "WARN: $script timed out after ${STARTUP_TIMEOUT}s (killed)"
            else
                echo "WARN: $script exited with status $EXIT_CODE"
            fi
        fi
    done
fi

echo "=== Starting supervisord ==="
exec supervisord -n -c /etc/supervisor/conf.d/conclave.conf
