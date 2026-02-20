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
# 3. First boot: generate secrets + init services
# ---------------------------------------------------------------
if [ ! -f "$WORKSPACE/.initialized" ]; then
    echo "=== First boot detected ==="

    # Generate secrets for anything not already in env
    SYNAPSE_DB_PASSWORD="${SYNAPSE_DB_PASSWORD:-$(openssl rand -hex 32)}"
    PLANKA_DB_PASSWORD="${PLANKA_DB_PASSWORD:-$(openssl rand -hex 32)}"
    PLANKA_SECRET_KEY="${PLANKA_SECRET_KEY:-$(openssl rand -hex 32)}"
    CHROMADB_TOKEN="${CHROMADB_TOKEN:-$(openssl rand -hex 32)}"
    SYNAPSE_REGISTRATION_SHARED_SECRET="${SYNAPSE_REGISTRATION_SHARED_SECRET:-$(openssl rand -hex 32)}"
    SYNAPSE_MACAROON_SECRET_KEY="${SYNAPSE_MACAROON_SECRET_KEY:-$(openssl rand -hex 32)}"
    SYNAPSE_FORM_SECRET="${SYNAPSE_FORM_SECRET:-$(openssl rand -hex 32)}"
    SYNAPSE_SIGNING_KEY="$(openssl rand -hex 32)"
    ADMIN_MATRIX_PASSWORD="${ADMIN_MATRIX_PASSWORD:-$(openssl rand -hex 16)}"
    AGENT_MATRIX_PASSWORD="${AGENT_MATRIX_PASSWORD:-$(openssl rand -hex 16)}"
    AGENT_PLANKA_PASSWORD="${AGENT_PLANKA_PASSWORD:-$(openssl rand -hex 16)}"

    cat > "$SECRETS_FILE" <<SECRETS_EOF
SYNAPSE_DB_PASSWORD=$SYNAPSE_DB_PASSWORD
PLANKA_DB_PASSWORD=$PLANKA_DB_PASSWORD
PLANKA_SECRET_KEY=$PLANKA_SECRET_KEY
CHROMADB_TOKEN=$CHROMADB_TOKEN
SYNAPSE_REGISTRATION_SHARED_SECRET=$SYNAPSE_REGISTRATION_SHARED_SECRET
SYNAPSE_MACAROON_SECRET_KEY=$SYNAPSE_MACAROON_SECRET_KEY
SYNAPSE_FORM_SECRET=$SYNAPSE_FORM_SECRET
ADMIN_MATRIX_PASSWORD=$ADMIN_MATRIX_PASSWORD
AGENT_MATRIX_PASSWORD=$AGENT_MATRIX_PASSWORD
AGENT_PLANKA_PASSWORD=$AGENT_PLANKA_PASSWORD
SECRETS_EOF
    chmod 600 "$SECRETS_FILE"

    # Initialize PostgreSQL
    /opt/conclave/scripts/init-postgres.sh

    # Initialize Synapse config
    /opt/conclave/scripts/init-synapse.sh
fi

# ---------------------------------------------------------------
# 4. Every boot: render config templates + setup
# ---------------------------------------------------------------

# Defaults for optional env vars
export CONCLAVE_AGENT_USER="${CONCLAVE_AGENT_USER:-pi}"
export MATRIX_SERVER_NAME="${MATRIX_SERVER_NAME:-conclave.local}"
export EXTERNAL_HOSTNAME="${EXTERNAL_HOSTNAME:-localhost}"
export NGINX_USER="${NGINX_USER:-admin}"
export NGINX_PASSWORD="${NGINX_PASSWORD:?NGINX_PASSWORD must be set}"
export TTYD_USER="${TTYD_USER:-admin}"
export TTYD_PASSWORD="${TTYD_PASSWORD:-$NGINX_PASSWORD}"
export NEKO_PASSWORD="${NEKO_PASSWORD:-neko}"
export NEKO_ADMIN_PASSWORD="${NEKO_ADMIN_PASSWORD:-admin}"
export PLANKA_ADMIN_EMAIL="${PLANKA_ADMIN_EMAIL:-admin@local}"
export PLANKA_ADMIN_PASSWORD="${PLANKA_ADMIN_PASSWORD:-changeme}"
export DEFAULT_OLLAMA_MODEL="${DEFAULT_OLLAMA_MODEL:-qwen3-coder:30b-a3b-q8_0}"

# Update dev user password if provided
if [ -n "${CONCLAVE_DEV_PASSWORD:-}" ]; then
    echo "dev:${CONCLAVE_DEV_PASSWORD}" | chpasswd
fi

# Re-source secrets (they exist now whether first boot or not)
set -a
# shellcheck source=/dev/null
source "$SECRETS_FILE"
set +a

# Render nginx config
envsubst < /opt/conclave/configs/nginx/nginx.conf.template > "$WORKSPACE/config/nginx/nginx.conf"

# Generate htpasswd
htpasswd -bc "$WORKSPACE/config/nginx/htpasswd" "$NGINX_USER" "$NGINX_PASSWORD" 2>/dev/null

# Render Element Web config
envsubst < /opt/conclave/configs/element-web/config.json.template > "$WORKSPACE/config/element-web/config.json"

# Write Planka env
cat > "$WORKSPACE/config/planka/.env" <<PLANKA_EOF
BASE_URL=https://${EXTERNAL_HOSTNAME}/planka
DATABASE_URL=postgresql://planka:${PLANKA_DB_PASSWORD}@127.0.0.1:5432/planka
SECRET_KEY=${PLANKA_SECRET_KEY}
DEFAULT_ADMIN_EMAIL=${PLANKA_ADMIN_EMAIL}
DEFAULT_ADMIN_PASSWORD=${PLANKA_ADMIN_PASSWORD}
DEFAULT_ADMIN_NAME=Admin
DEFAULT_ADMIN_USERNAME=admin
TRUST_PROXY=true
PLANKA_EOF

# Write ChromaDB env
cat > "$WORKSPACE/config/chromadb/.env" <<CHROMA_EOF
IS_PERSISTENT=TRUE
PERSIST_DIRECTORY=/workspace/data/chromadb
ANONYMIZED_TELEMETRY=FALSE
CHROMA_SERVER_AUTHN_CREDENTIALS=${CHROMADB_TOKEN}
CHROMA_SERVER_AUTHN_PROVIDER=chromadb.auth.token_authn.TokenAuthenticationServerProvider
CHROMA_EOF

# Write Neko env
cat > "$WORKSPACE/config/neko/.env" <<NEKO_EOF
NEKO_SCREEN=1920x1080@30
NEKO_PASSWORD=${NEKO_PASSWORD}
NEKO_PASSWORD_ADMIN=${NEKO_ADMIN_PASSWORD}
NEKO_BIND=0.0.0.0:8080
NEKO_EPR=52000-52100
NEKO_ICELITE=true
NEKO_EOF

# Write agent credentials env file (for coding agents in tmux)
AGENT_ENV_FILE="$WORKSPACE/config/agent-env.sh"
cat > "$AGENT_ENV_FILE" <<AGENT_EOF
# Conclave agent credentials — sourced into tmux sessions
AGENT_MATRIX_USER=${CONCLAVE_AGENT_USER}
AGENT_MATRIX_PASSWORD=${AGENT_MATRIX_PASSWORD}
AGENT_MATRIX_URL=https://${EXTERNAL_HOSTNAME}
AGENT_MATRIX_SERVER_NAME=${MATRIX_SERVER_NAME}
AGENT_PLANKA_USER=${CONCLAVE_AGENT_USER}
AGENT_PLANKA_EMAIL=${CONCLAVE_AGENT_USER}@local
AGENT_PLANKA_PASSWORD=${AGENT_PLANKA_PASSWORD}
AGENT_PLANKA_URL=https://${EXTERNAL_HOSTNAME}/planka
AGENT_NEKO_PASSWORD=${NEKO_ADMIN_PASSWORD}
AGENT_CHROMADB_TOKEN=${CHROMADB_TOKEN}
AGENT_CHROMADB_URL=http://127.0.0.1:8000
AGENT_OLLAMA_URL=http://127.0.0.1:11434
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
rsync -a /opt/conclave/skills/claude-code/ "$WORKSPACE/data/coding/.claude/skills/" 2>/dev/null || true

# Copy pi-models.json and tmux.conf if not present (don't overwrite user edits)
cp -n /opt/conclave/configs/coding/pi-models.json "$WORKSPACE/data/coding/.pi/agent/models.json" 2>/dev/null || true
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
# 5. Mark initialized
# ---------------------------------------------------------------
touch "$WORKSPACE/.initialized"

# ---------------------------------------------------------------
# 6. Export env vars needed by supervisord programs
# ---------------------------------------------------------------
export TTYD_USER TTYD_PASSWORD
export NEKO_PASSWORD NEKO_ADMIN_PASSWORD
export CONCLAVE_AGENT_USER

# Source Neko and ChromaDB envs for supervisord
set -a
source "$WORKSPACE/config/neko/.env"
source "$WORKSPACE/config/chromadb/.env"
set +a

# ---------------------------------------------------------------
# 7. Launch supervisord as PID 1
# ---------------------------------------------------------------
if [ "${CONCLAVE_SETUP_ONLY:-}" = "1" ]; then
    echo "=== Setup complete (CONCLAVE_SETUP_ONLY=1, skipping supervisord) ==="
    exit 0
fi

echo "=== Starting supervisord ==="
exec supervisord -n -c /etc/supervisor/conf.d/conclave.conf
