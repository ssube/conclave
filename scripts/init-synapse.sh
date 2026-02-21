#!/bin/bash
set -euo pipefail

SYNAPSE_CONFIG="/workspace/config/synapse/homeserver.yaml"
OVERRIDE="/opt/conclave/configs/synapse/homeserver.override.yaml"

echo "=== Initializing Synapse ==="

# Generate base config if not exists
if [ ! -f "$SYNAPSE_CONFIG" ]; then
    python3 -m synapse.app.homeserver \
        --server-name="${MATRIX_SERVER_NAME}" \
        --config-path="$SYNAPSE_CONFIG" \
        --generate-config \
        --report-stats=no \
        --data-directory=/workspace/data/synapse

    # Apply overrides using python to merge YAML
    python3 <<PYEOF
import yaml

with open("$SYNAPSE_CONFIG") as f:
    config = yaml.safe_load(f)

with open("$OVERRIDE") as f:
    overrides = yaml.safe_load(f)

# Deep merge overrides into config
def merge(base, override):
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            merge(base[key], value)
        else:
            base[key] = value

merge(config, overrides)

# Set secrets from env vars
config['registration_shared_secret'] = '${SYNAPSE_REGISTRATION_SHARED_SECRET}'
config['macaroon_secret_key'] = '${SYNAPSE_MACAROON_SECRET_KEY}'
config['form_secret'] = '${SYNAPSE_FORM_SECRET}'
config['database']['args']['password'] = '${SYNAPSE_DB_PASSWORD}'

with open("$SYNAPSE_CONFIG", 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
PYEOF
fi

echo "=== Synapse initialized ==="
