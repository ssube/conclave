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
    -p "${CONCLAVE_ADMIN_PASSWORD}" \
    --admin \
    -c /workspace/config/synapse/homeserver.yaml \
    http://127.0.0.1:8008 2>&1 || echo "Matrix admin user may already exist (this is OK)."

# ---------------------------------------------------------------
# Create Matrix agent user (idempotent)
# ---------------------------------------------------------------
echo "Creating Matrix agent user (${CONCLAVE_AGENT_USER})..."
register_new_matrix_user \
    -u "${CONCLAVE_AGENT_USER}" \
    -p "${CONCLAVE_AGENT_PASSWORD}" \
    --no-admin \
    -c /workspace/config/synapse/homeserver.yaml \
    http://127.0.0.1:8008 2>&1 || echo "Matrix agent user may already exist (this is OK)."

# ---------------------------------------------------------------
# Get Matrix agent access token and append to agent-env.sh
# ---------------------------------------------------------------
AGENT_ENV_FILE="/workspace/config/agent-env.sh"
if ! grep -q MATRIX_ACCESS_TOKEN "$AGENT_ENV_FILE" 2>/dev/null; then
    echo "Obtaining Matrix access token for agent..."
    MATRIX_ACCESS_TOKEN=$(curl -s http://127.0.0.1:8008/_matrix/client/v3/login \
        -X POST -H 'Content-Type: application/json' \
        -d "{\"type\":\"m.login.password\",\"user\":\"${CONCLAVE_AGENT_USER}\",\"password\":\"${CONCLAVE_AGENT_PASSWORD}\"}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
    if [ -n "$MATRIX_ACCESS_TOKEN" ]; then
        echo "MATRIX_ACCESS_TOKEN=${MATRIX_ACCESS_TOKEN}" >> "$AGENT_ENV_FILE"
        echo "Matrix agent access token saved."
    else
        echo "WARNING: Could not obtain Matrix agent access token."
    fi
fi

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

# Source Planka env for DATABASE_URL
if [ -f /workspace/config/planka/.env ]; then
    set -a
    # shellcheck source=/dev/null
    source /workspace/config/planka/.env
    set +a
fi

# Run Planka database migrations (idempotent)
echo "Running Planka database migrations..."
cd /opt/planka
node db/init.js 2>&1 || echo "WARNING: Planka migrations may have failed."

# Wait for user_account table to exist (migrations may take time)
echo "Waiting for Planka database schema..."
for i in $(seq 1 30); do
    if node -e "
const knex = require('knex')({ client: 'pg', connection: process.env.DATABASE_URL });
knex.schema.hasTable('user_account').then(exists => { knex.destroy(); process.exit(exists ? 0 : 1); }).catch(() => { knex.destroy(); process.exit(1); });
" 2>/dev/null; then
        echo "Planka schema is ready."
        break
    fi
    echo "Planka schema not ready, retrying in 10s... ($((i * 10))/300s)"
    sleep 10
done

# ---------------------------------------------------------------
# Create Planka agent user (idempotent via knex)
# ---------------------------------------------------------------
echo "Creating Planka agent user (${CONCLAVE_AGENT_USER})..."

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
  const passwordHash = await bcrypt.hash('${CONCLAVE_AGENT_PASSWORD}', 10);
  await knex('user_account').insert({
    email: email,
    password: passwordHash,
    role: 'normal',
    name: '${CONCLAVE_AGENT_USER}',
    username: '${CONCLAVE_AGENT_USER}',
    subscribe_to_own_cards: false,
    subscribe_to_card_when_commenting: true,
    turn_off_recent_card_highlighting: false,
    enable_favorites_by_default: true,
    default_editor_mode: 'wysiwyg',
    default_home_view: 'groupedProjects',
    default_projects_order: 'byDefault',
    is_sso_user: false,
    is_deactivated: false,
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

# ---------------------------------------------------------------
# Create Matrix "home" room (idempotent)
# ---------------------------------------------------------------
echo "Creating Matrix 'home' room..."
ADMIN_TOKEN=$(curl -s http://127.0.0.1:8008/_matrix/client/v3/login \
    -X POST -H 'Content-Type: application/json' \
    -d "{\"type\":\"m.login.password\",\"user\":\"admin\",\"password\":\"${CONCLAVE_ADMIN_PASSWORD}\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)

if [ -n "$ADMIN_TOKEN" ]; then
    # Check if #home room already exists
    HOME_ROOM=$(curl -s "http://127.0.0.1:8008/_matrix/client/v3/directory/room/%23home%3A${MATRIX_SERVER_NAME}" \
        -H "Authorization: Bearer $ADMIN_TOKEN" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('room_id',''))" 2>/dev/null || true)

    if [ -n "$HOME_ROOM" ]; then
        echo "Matrix 'home' room already exists: $HOME_ROOM"
    else
        HOME_ROOM=$(curl -s http://127.0.0.1:8008/_matrix/client/v3/createRoom \
            -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
            -d "{\"room_alias_name\":\"home\",\"name\":\"Home\",\"topic\":\"General discussion\",\"visibility\":\"private\",\"preset\":\"private_chat\",\"invite\":[\"@${CONCLAVE_AGENT_USER}:${MATRIX_SERVER_NAME}\"]}" \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('room_id',''))" 2>/dev/null || true)
        if [ -n "$HOME_ROOM" ]; then
            echo "Matrix 'home' room created: $HOME_ROOM"
        else
            echo "WARNING: Failed to create Matrix 'home' room."
        fi

        # Auto-join the agent user
        AGENT_TOKEN=$(curl -s http://127.0.0.1:8008/_matrix/client/v3/login \
            -X POST -H 'Content-Type: application/json' \
            -d "{\"type\":\"m.login.password\",\"user\":\"${CONCLAVE_AGENT_USER}\",\"password\":\"${CONCLAVE_AGENT_PASSWORD}\"}" \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
        if [ -n "$AGENT_TOKEN" ] && [ -n "$HOME_ROOM" ]; then
            curl -s "http://127.0.0.1:8008/_matrix/client/v3/join/${HOME_ROOM}" \
                -X POST -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
                -d '{}' > /dev/null 2>&1 || true
            echo "Agent user joined 'home' room."
        fi
    fi
else
    echo "WARNING: Could not get Matrix admin token, skipping room creation."
fi

# ---------------------------------------------------------------
# Create Planka "Work" project with board and lists (idempotent)
# ---------------------------------------------------------------
echo "Creating Planka 'Work' project..."

cd /opt/planka
node -e "
const knex = require('knex')({
  client: 'pg',
  connection: process.env.DATABASE_URL,
});

async function createWorkProject() {
  // Get admin user
  const admin = await knex('user_account').where({ username: 'admin' }).first();
  if (!admin) { console.log('Admin user not found.'); process.exit(0); }

  // Check if project exists
  const existing = await knex('project').where({ name: 'Work' }).first();
  if (existing) { console.log('Work project already exists.'); process.exit(0); }

  // Create project
  const [project] = await knex('project').insert({
    name: 'Work',
    is_hidden: false,
    created_at: new Date(),
    updated_at: new Date(),
  }).returning('*');

  // Add admin as project manager (and set as owner)
  const [pm] = await knex('project_manager').insert({
    project_id: project.id,
    user_id: admin.id,
    created_at: new Date(),
    updated_at: new Date(),
  }).returning('*');

  await knex('project').where({ id: project.id }).update({ owner_project_manager_id: pm.id });

  // Add agent user as project manager
  const agent = await knex('user_account').where({ username: '${CONCLAVE_AGENT_USER}' }).first();
  if (agent) {
    await knex('project_manager').insert({
      project_id: project.id,
      user_id: agent.id,
      created_at: new Date(),
      updated_at: new Date(),
    });
  }

  // Create board
  const [board] = await knex('board').insert({
    project_id: project.id,
    position: 1,
    name: 'Tasks',
    default_view: 'kanban',
    default_card_type: 'project',
    limit_card_types_to_default_one: false,
    always_display_card_creator: false,
    expand_task_lists_by_default: false,
    created_at: new Date(),
    updated_at: new Date(),
  }).returning('*');

  // Add board memberships
  await knex('board_membership').insert({
    project_id: project.id,
    board_id: board.id,
    user_id: admin.id,
    role: 'editor',
    can_comment: true,
    created_at: new Date(),
    updated_at: new Date(),
  });
  if (agent) {
    await knex('board_membership').insert({
      project_id: project.id,
      board_id: board.id,
      user_id: agent.id,
      role: 'editor',
      can_comment: true,
      created_at: new Date(),
      updated_at: new Date(),
    });
  }

  // Create default lists
  const lists = ['To Do', 'In Progress', 'Done'];
  for (let i = 0; i < lists.length; i++) {
    await knex('list').insert({
      board_id: board.id,
      type: 'active',
      position: (i + 1) * 65536,
      name: lists[i],
      created_at: new Date(),
      updated_at: new Date(),
    });
  }

  // Create labels
  const labels = [
    { name: 'human', color: 'lagoon', position: 1 },
    { name: 'agent', color: 'bright-moss', position: 2 },
  ];
  for (const label of labels) {
    await knex('label').insert({
      board_id: board.id,
      name: label.name,
      color: label.color,
      position: label.position * 65536,
      created_at: new Date(),
      updated_at: new Date(),
    });
  }

  console.log('Work project created with Tasks board, 3 lists, and 2 labels.');
  process.exit(0);
}

createWorkProject().catch(err => {
  console.error('Error creating Work project:', err.message);
  process.exit(1);
});
" 2>&1 || echo "Work project creation failed (may already exist)."

echo "=== User and resource creation complete ==="
