#!/bin/bash
set -euo pipefail

# Launch a Conclave pod on Runpod via GraphQL API
#
# Usage: launch-runpod.sh [options]
#   --gpu-type TYPE         GPU type (default: NVIDIA A100 80GB PCIe)
#   --image IMAGE           Docker image (default: your-registry/conclave:latest)
#   --volume-size GB        Volume size in GB (default: 500)
#   --name NAME             Pod name (default: conclave)
#   --env KEY=VALUE         Pass environment variable (repeatable)

: "${RUNPOD_API_KEY:?RUNPOD_API_KEY must be set}"

GPU_TYPE="NVIDIA A100 80GB PCIe"
IMAGE="your-registry/conclave:latest"
VOLUME_SIZE=500
POD_NAME="conclave"
ENV_VARS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu-type) GPU_TYPE="$2"; shift 2 ;;
        --image) IMAGE="$2"; shift 2 ;;
        --volume-size) VOLUME_SIZE="$2"; shift 2 ;;
        --name) POD_NAME="$2"; shift 2 ;;
        --env) ENV_VARS+=("$2"); shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Build env var JSON array
ENV_JSON="["
for ev in "${ENV_VARS[@]+"${ENV_VARS[@]}"}"; do
    KEY="${ev%%=*}"
    VALUE="${ev#*=}"
    ENV_JSON+="{\"key\":\"$KEY\",\"value\":\"$VALUE\"},"
done
ENV_JSON="${ENV_JSON%,}]"

# Create pod via GraphQL
RESPONSE=$(curl -sf "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{
        \"query\": \"mutation { podFindAndDeployOnDemand(input: { name: \\\"${POD_NAME}\\\", imageName: \\\"${IMAGE}\\\", gpuTypeId: \\\"${GPU_TYPE}\\\", volumeInGb: ${VOLUME_SIZE}, containerDiskInGb: 20, ports: \\\"8888/http,22/tcp,52000-52100/udp\\\", env: ${ENV_JSON} }) { id machineId } }\"
    }")

POD_ID=$(echo "$RESPONSE" | jq -r '.data.podFindAndDeployOnDemand.id // empty')

if [ -z "$POD_ID" ]; then
    echo "ERROR: Failed to create pod"
    echo "$RESPONSE" | jq .
    exit 1
fi

echo "Pod created: $POD_ID"
echo "Waiting for pod to be ready..."

# Poll for ready state
for i in $(seq 1 60); do
    STATUS=$(curl -sf "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"query { pod(input: { podId: \\\"${POD_ID}\\\" }) { desiredStatus runtime { uptimeInSeconds ports { ip isIpPublic privatePort publicPort type } } } }\"}" \
        | jq -r '.data.pod.desiredStatus // empty')

    if [ "$STATUS" = "RUNNING" ]; then
        echo ""
        echo "=== Pod is RUNNING ==="
        echo "Dashboard: https://${POD_ID}-8888.proxy.runpod.net/"
        echo "SSH:       ssh root@${POD_ID}-22.proxy.runpod.net"
        echo "Pod ID:    $POD_ID"
        exit 0
    fi

    printf "."
    sleep 5
done

echo ""
echo "WARNING: Pod did not reach RUNNING state within 5 minutes"
echo "Pod ID: $POD_ID"
echo "Check status at: https://www.runpod.io/console/pods"
