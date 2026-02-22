#!/bin/bash
# Setup script for conclave-minimal Kubernetes deployment.
# Prompts for environment variables and creates/updates the Secret.
set -euo pipefail

NAMESPACE="${1:-default}"
SECRET_NAME="conclave-minimal-env"

echo "Conclave Minimal — Secret Setup (namespace: $NAMESPACE)"
echo ""

read -rp "EXTERNAL_HOSTNAME: " EXTERNAL_HOSTNAME
read -rp "EXTERNAL_MATRIX_URL: " EXTERNAL_MATRIX_URL
read -rp "EXTERNAL_PLANKA_URL: " EXTERNAL_PLANKA_URL
read -rp "EXTERNAL_OLLAMA_URL: " EXTERNAL_OLLAMA_URL
read -rp "TZ [UTC]: " TZ
TZ="${TZ:-UTC}"
read -rsp "CONCLAVE_ADMIN_PASSWORD: " CONCLAVE_ADMIN_PASSWORD
echo ""
echo "SSH_AUTHORIZED_KEYS (paste key, then press Enter):"
read -r SSH_AUTHORIZED_KEYS

echo ""
echo "Creating secret $SECRET_NAME in namespace $NAMESPACE..."

kubectl -n "$NAMESPACE" create secret generic "$SECRET_NAME" \
  --from-literal="EXTERNAL_HOSTNAME=${EXTERNAL_HOSTNAME}" \
  --from-literal="EXTERNAL_MATRIX_URL=${EXTERNAL_MATRIX_URL}" \
  --from-literal="EXTERNAL_PLANKA_URL=${EXTERNAL_PLANKA_URL}" \
  --from-literal="EXTERNAL_OLLAMA_URL=${EXTERNAL_OLLAMA_URL}" \
  --from-literal="TZ=${TZ}" \
  --from-literal="CONCLAVE_ADMIN_PASSWORD=${CONCLAVE_ADMIN_PASSWORD}" \
  --from-literal="SSH_AUTHORIZED_KEYS=${SSH_AUTHORIZED_KEYS}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Done."
