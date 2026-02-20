#!/bin/bash
set -euo pipefail

SECRETS_FILE="/workspace/config/generated-secrets.env"

# Source secrets (contains SYNAPSE_REGISTRATION_SHARED_SECRET, passwords, etc.)
if [ -f "$SECRETS_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_FILE"
    set +a
fi

CONCLAVE_AGENT_USER="${CONCLAVE_AGENT_USER:-pi}"
MATRIX_SERVER_NAME="${MATRIX_SERVER_NAME:-conclave.local}"

# ---------------------------------------------------------------
# Wait for Synapse
# ---------------------------------------------------------------
echo "Waiting for Synapse..."
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8008/_matrix/client/versions > /dev/null 2>&1; then
        echo "Synapse is ready."
        break
    fi
    sleep 2
done

if ! curl -sf http://127.0.0.1:8008/_matrix/client/versions > /dev/null 2>&1; then
    echo "ERROR: Synapse not available after 120s"
    exit 1
fi

# ---------------------------------------------------------------
# Create Matrix admin user (idempotent)
# ---------------------------------------------------------------
echo "Creating Matrix admin user..."
register_new_matrix_user \
    -u admin \
    -p "${ADMIN_MATRIX_PASSWORD}" \
    --admin \
    -c /workspace/config/synapse/homeserver.yaml \
    http://127.0.0.1:8008 2>&1 || echo "Matrix admin user may already exist (this is OK)."

# ---------------------------------------------------------------
# Create Matrix agent user (idempotent)
# ---------------------------------------------------------------
echo "Creating Matrix agent user (${CONCLAVE_AGENT_USER})..."
register_new_matrix_user \
    -u "${CONCLAVE_AGENT_USER}" \
    -p "${AGENT_MATRIX_PASSWORD}" \
    --no-admin \
    -c /workspace/config/synapse/homeserver.yaml \
    http://127.0.0.1:8008 2>&1 || echo "Matrix agent user may already exist (this is OK)."

# ---------------------------------------------------------------
# Wait for Planka
# ---------------------------------------------------------------
echo "Waiting for Planka..."
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:1337/api/access-tokens > /dev/null 2>&1; then
        echo "Planka is ready."
        break
    fi
    sleep 2
done

if ! curl -sf http://127.0.0.1:1337/api/access-tokens > /dev/null 2>&1; then
    echo "WARNING: Planka not available after 120s, skipping Planka agent user creation."
    exit 0
fi

# ---------------------------------------------------------------
# Create Planka agent user (idempotent via knex)
# ---------------------------------------------------------------
echo "Creating Planka agent user (${CONCLAVE_AGENT_USER})..."

# Source Planka env for DATABASE_URL
if [ -f /workspace/config/planka/.env ]; then
    set -a
    # shellcheck source=/dev/null
    source /workspace/config/planka/.env
    set +a
fi

cd /opt/planka
node -e "
const bcrypt = require('bcrypt');
const knex = require('knex')({
  client: 'pg',
  connection: process.env.DATABASE_URL,
});

async function createAgentUser() {
  const email = '${CONCLAVE_AGENT_USER}@local';
  const existing = await knex('user_account').where({ email }).first();
  if (existing) {
    console.log('Planka agent user already exists.');
    process.exit(0);
  }
  const passwordHash = await bcrypt.hash('${AGENT_PLANKA_PASSWORD}', 10);
  await knex('user_account').insert({
    email: email,
    password: passwordHash,
    is_admin: false,
    name: '${CONCLAVE_AGENT_USER}',
    username: '${CONCLAVE_AGENT_USER}',
    created_at: new Date(),
    updated_at: new Date(),
  });
  console.log('Planka agent user created.');
  process.exit(0);
}

createAgentUser().catch(err => {
  console.error('Error creating Planka agent user:', err.message);
  process.exit(1);
});
" 2>&1 || echo "Planka agent user creation failed (may already exist)."

echo "=== User creation complete ==="
