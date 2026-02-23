#!/bin/bash
# Setup script for conclave-minimal Kubernetes deployment.
# Prompts for environment variables and creates/updates the Secret.
# Existing values are shown as defaults — press Enter to keep them.
set -euo pipefail

NAMESPACE="${1:-default}"
SECRET_NAME="conclave-minimal-env"

echo "Conclave Minimal — Secret Setup (namespace: $NAMESPACE)"
echo ""

# Load existing secret values as defaults (if the secret exists)
get_existing() {
    kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" -o jsonpath="{.data.$1}" 2>/dev/null | base64 -d 2>/dev/null || true
}

_EXTERNAL_HOSTNAME=$(get_existing EXTERNAL_HOSTNAME)
_EXTERNAL_MATRIX_URL=$(get_existing EXTERNAL_MATRIX_URL)
_EXTERNAL_PLANKA_URL=$(get_existing EXTERNAL_PLANKA_URL)
_EXTERNAL_OLLAMA_URL=$(get_existing EXTERNAL_OLLAMA_URL)
_TZ=$(get_existing TZ)
_TZ="${_TZ:-UTC}"
_NEKO_NAT1TO1=$(get_existing NEKO_NAT1TO1)
_NEKO_TCPMUX_PORT=$(get_existing NEKO_TCPMUX_PORT)
_CONCLAVE_ADMIN_PASSWORD=$(get_existing CONCLAVE_ADMIN_PASSWORD)
_SSH_AUTHORIZED_KEYS=$(get_existing SSH_AUTHORIZED_KEYS)

prompt() {
    local var="$1" default="$2" prompt_text="$3"
    if [ -n "$default" ]; then
        read -rp "$prompt_text [$default]: " value
        eval "$var=\"\${value:-\$default}\""
    else
        read -rp "$prompt_text: " value
        eval "$var=\"\$value\""
    fi
}

prompt EXTERNAL_HOSTNAME "$_EXTERNAL_HOSTNAME" "EXTERNAL_HOSTNAME"
prompt EXTERNAL_MATRIX_URL "$_EXTERNAL_MATRIX_URL" "EXTERNAL_MATRIX_URL"
prompt EXTERNAL_PLANKA_URL "$_EXTERNAL_PLANKA_URL" "EXTERNAL_PLANKA_URL"
prompt EXTERNAL_OLLAMA_URL "$_EXTERNAL_OLLAMA_URL" "EXTERNAL_OLLAMA_URL"
prompt TZ "$_TZ" "TZ"
prompt NEKO_NAT1TO1 "$_NEKO_NAT1TO1" "NEKO_NAT1TO1 (node IP for WebRTC)"
prompt NEKO_TCPMUX_PORT "$_NEKO_TCPMUX_PORT" "NEKO_TCPMUX_PORT (must match NodePort)"

if [ -n "$_CONCLAVE_ADMIN_PASSWORD" ]; then
    read -rsp "CONCLAVE_ADMIN_PASSWORD [keep existing]: " CONCLAVE_ADMIN_PASSWORD
    echo ""
    CONCLAVE_ADMIN_PASSWORD="${CONCLAVE_ADMIN_PASSWORD:-$_CONCLAVE_ADMIN_PASSWORD}"
else
    read -rsp "CONCLAVE_ADMIN_PASSWORD: " CONCLAVE_ADMIN_PASSWORD
    echo ""
fi

if [ -n "$_SSH_AUTHORIZED_KEYS" ]; then
    echo "SSH_AUTHORIZED_KEYS [Enter to keep existing, or paste new key]:"
    read -r SSH_AUTHORIZED_KEYS
    SSH_AUTHORIZED_KEYS="${SSH_AUTHORIZED_KEYS:-$_SSH_AUTHORIZED_KEYS}"
else
    echo "SSH_AUTHORIZED_KEYS (paste key, then press Enter):"
    read -r SSH_AUTHORIZED_KEYS
fi

echo ""
echo "Creating secret $SECRET_NAME in namespace $NAMESPACE..."

SECRET_ARGS=(
  --from-literal="EXTERNAL_HOSTNAME=${EXTERNAL_HOSTNAME}"
  --from-literal="EXTERNAL_MATRIX_URL=${EXTERNAL_MATRIX_URL}"
  --from-literal="EXTERNAL_PLANKA_URL=${EXTERNAL_PLANKA_URL}"
  --from-literal="EXTERNAL_OLLAMA_URL=${EXTERNAL_OLLAMA_URL}"
  --from-literal="TZ=${TZ}"
  --from-literal="CONCLAVE_ADMIN_PASSWORD=${CONCLAVE_ADMIN_PASSWORD}"
  --from-literal="SSH_AUTHORIZED_KEYS=${SSH_AUTHORIZED_KEYS}"
)
[ -n "$NEKO_NAT1TO1" ] && SECRET_ARGS+=(--from-literal="NEKO_NAT1TO1=${NEKO_NAT1TO1}")
[ -n "$NEKO_TCPMUX_PORT" ] && SECRET_ARGS+=(--from-literal="NEKO_TCPMUX_PORT=${NEKO_TCPMUX_PORT}")

kubectl -n "$NAMESPACE" create secret generic "$SECRET_NAME" \
  "${SECRET_ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Done."
