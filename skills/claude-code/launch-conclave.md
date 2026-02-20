---
name: launch-conclave
description: >-
  Launch a Conclave workspace on Runpod. Use when the user wants to start a new
  GPU pod with the full Conclave environment (Matrix, Planka, Ollama, browser,
  coding agents, etc).
---

# Launch Conclave on Runpod

Deploy a Conclave workspace pod on Runpod using the GraphQL API.

## Prerequisites

- `RUNPOD_API_KEY` environment variable set
- Conclave Docker image pushed to a registry

## Usage

```bash
# Basic launch with defaults (A100 80GB, 500GB volume)
bash /opt/conclave/scripts/launch-runpod.sh \
  --env NGINX_PASSWORD=your-password \
  --env MATRIX_SERVER_NAME=conclave.local \
  --env EXTERNAL_HOSTNAME=pod-id-8888.proxy.runpod.net

# Custom GPU and image
bash /opt/conclave/scripts/launch-runpod.sh \
  --gpu-type "NVIDIA H100 80GB HBM3" \
  --image your-registry/conclave:latest \
  --volume-size 1000 \
  --env NGINX_PASSWORD=your-password \
  --env ANTHROPIC_API_KEY=sk-ant-...

# With SSH keys
bash /opt/conclave/scripts/launch-runpod.sh \
  --env NGINX_PASSWORD=your-password \
  --env SSH_AUTHORIZED_KEYS="ssh-ed25519 AAAA..."
```

## Required Environment Variables

Pass via `--env` flags:
- `NGINX_PASSWORD` (required) — basic auth password for dashboard/ollama/chromadb-admin
- `MATRIX_SERVER_NAME` — Matrix server domain (default: conclave.local)
- `EXTERNAL_HOSTNAME` — Pod external hostname for config templates

## Optional Environment Variables

- `ANTHROPIC_API_KEY` — for Claude Code and pi
- `OPENAI_API_KEY` — for pi (OpenAI provider)
- `SSH_AUTHORIZED_KEYS` — SSH public keys (newline-separated)
- `DEFAULT_OLLAMA_MODEL` — model to pre-pull (default: llama3.1:8b)

## After Launch

1. The script prints the dashboard URL and SSH connection string
2. Access the dashboard at `https://{pod-id}-8888.proxy.runpod.net/`
3. Follow the quick-start guide on the dashboard
