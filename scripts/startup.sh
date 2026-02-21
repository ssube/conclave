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
mkdir -p "$WORKSPACE"/config/{nginx,synapse,element-web,planka,chromadb,neko,ssh}
mkdir -p "$WORKSPACE"/data/{synapse/media_store,postgres,planka,chromadb,ollama/models,neko/chromium-profile,coding/.pi/agent/{skills,prompts,extensions,themes},coding/.claude/skills,coding/projects}
mkdir -p "$WORKSPACE"/logs/{nginx,synapse,postgres,planka,chromadb,ollama,neko,ttyd}

# Ensure dev user owns coding workspace
chown -R dev:dev "$WORKSPACE/data/coding/"

# ---------------------------------------------------------------
# 3. Defaults for optional env vars (needed by init scripts)
# ---------------------------------------------------------------
export CONCLAVE_AGENT_USER="${CONCLAVE_AGENT_USER:-pi}"
export MATRIX_SERVER_NAME="${MATRIX_SERVER_NAME:-conclave.local}"
export EXTERNAL_HOSTNAME="${EXTERNAL_HOSTNAME:-localhost}"
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

    # Initialize PostgreSQL
    /opt/conclave/scripts/init-postgres.sh

    # Initialize Synapse config
    /opt/conclave/scripts/init-synapse.sh
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
envsubst < /opt/conclave/configs/element-web/config.json.template > "$WORKSPACE/config/element-web/config.json"
ln -sf "$WORKSPACE/config/element-web/config.json" /opt/element-web/config.json

# Write Planka env and symlink into app directory (dotenv loads from cwd)
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

# Write agent credentials env file (for coding agents in tmux)
AGENT_ENV_FILE="$WORKSPACE/config/agent-env.sh"
cat > "$AGENT_ENV_FILE" <<AGENT_EOF
# Conclave agent credentials — sourced into tmux sessions
AGENT_MATRIX_USER=${CONCLAVE_AGENT_USER}
AGENT_MATRIX_PASSWORD=${CONCLAVE_AGENT_PASSWORD}
AGENT_MATRIX_URL=${CONCLAVE_BASE_URL}
AGENT_MATRIX_SERVER_NAME=${MATRIX_SERVER_NAME}
AGENT_PLANKA_USER=${CONCLAVE_AGENT_USER}
AGENT_PLANKA_EMAIL=${CONCLAVE_AGENT_USER}@local
AGENT_PLANKA_PASSWORD=${CONCLAVE_AGENT_PASSWORD}
AGENT_PLANKA_URL=${CONCLAVE_BASE_URL}/planka
AGENT_NEKO_PASSWORD=${CONCLAVE_ADMIN_PASSWORD}
AGENT_CHROMADB_TOKEN=${CHROMADB_TOKEN}
AGENT_CHROMADB_URL=http://127.0.0.1:8000
AGENT_OLLAMA_URL=http://127.0.0.1:11434
MATRIX_HOMESERVER_URL=http://127.0.0.1:8008
MATRIX_SERVER_NAME=${MATRIX_SERVER_NAME}
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

# Sync Claude Code skills
rsync -a /opt/conclave/pi/skills/launch-conclave/ "$WORKSPACE/data/coding/.claude/skills/launch-conclave/" 2>/dev/null || true

# Copy pi-models.json and tmux.conf if not present (don't overwrite user edits)
cp -n /opt/conclave/configs/coding/pi-models.json "$WORKSPACE/data/coding/.pi/agent/models.json" 2>/dev/null || true
cp -n /opt/conclave/configs/coding/pi-settings.json "$WORKSPACE/data/coding/.pi/settings.json" 2>/dev/null || true
cp -n /opt/conclave/configs/coding/tmux.conf "$WORKSPACE/data/coding/.tmux.conf" 2>/dev/null || true

# Re-chown coding dir after syncing assets (rsync/cp run as root)
chown -R dev:dev "$WORKSPACE/data/coding/"

# Generate dashboard env.json
cat > /opt/dashboard/env.json <<ENV_EOF
{
    "MATRIX_SERVER_NAME": "${MATRIX_SERVER_NAME}",
    "EXTERNAL_HOSTNAME": "${EXTERNAL_HOSTNAME}",
    "services": {
        "synapse": true,
        "element_web": true,
        "postgres": true,
        "planka": true,
        "chromadb": true,
        "ollama": true,
        "neko": true,
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

echo "=== Starting supervisord ==="
exec supervisord -n -c /etc/supervisor/conf.d/conclave.conf
