# Conclave — Implementation Specification

**Project:** Conclave
**Tagline:** A self-hosted AI workspace in a single container
**Version:** 1.1 — Draft
**Date:** 2026-02-20

---

## 1. Overview

### 1.1 What Is Conclave?

A **conclave** is a private gathering — a closed meeting of chosen participants who come together for a shared purpose. In its original sense, it describes a room that can be locked from the inside: a space that is sealed, self-contained, and deliberately composed.

Conclave is exactly that: a private, self-contained workspace where you and your AI agents convene. It is a single Docker container that houses everything needed for an AI-augmented development environment — chat, project management, coding agents, LLM inference, a knowledge base, and a browsable internet session — all deployed as one unit onto a GPU pod. Your human collaborators join via Matrix. Your AI agents work alongside you through pi and Claude Code. Your tools are organized behind a single entry point. The conclave is in session.

### 1.2 Why Conclave Exists

GPU pod platforms like Runpod provide powerful hardware but impose a constraint: no nested Docker. You get one container. Conclave makes that one container count by running all services as supervised native processes with a shared persistent volume, using Ansible playbooks run inside the container during `docker build` to install and configure each service.

### 1.3 Services at a Glance

| Service | Role |
|---|---|
| Matrix Synapse + Element Web | Chat homeserver and web client |
| Planka | Kanban-style project management |
| PostgreSQL 16 | Shared relational database (Synapse + Planka) |
| ChromaDB + Admin UI | Vector database and editor for RAG workloads |
| Ollama | LLM inference server (OpenAI-compatible API) |
| N.eko | Interactive WebRTC browser session with CDP access |
| pi + Claude Code | AI coding agents in a persistent tmux workspace |
| ttyd | Web-based terminal access to the workspace |
| nginx | Unified reverse proxy with basic auth |

### 1.4 Design Principles

- **Single container, no nested Docker.** All services run as native processes managed by supervisord.
- **Persistent volume at `/workspace`.** All application state, databases, models, and configuration survive pod restarts.
- **Ansible-driven build.** An Ansible playbook with per-service roles runs inside the container during `docker build`, installing packages, building from source where needed, and deploying configs.
- **First boot vs. subsequent boot.** A startup script initializes data directories and config files on first run, then starts services on all subsequent runs.
- **Env vars override config defaults.** Secrets are passed as environment variables at pod start; the startup script writes them into persistent config files.

---

## 2. Target Environment

| Parameter | Value |
|---|---|
| Platform | Runpod GPU Pod |
| GPU | A100 80GB or H100 80GB |
| Base image | `nvidia/cuda:12.4.1-runtime-ubuntu22.04` |
| Persistent volume | 500GB–1TB mounted at `/workspace` |
| Process manager | supervisord |
| Reverse proxy | nginx (inside the container) |

---

## 3. Service Inventory

### 3.1 Matrix Synapse (Homeserver)

Synapse is the reference Matrix homeserver — the most mature and well-documented implementation with the broadest ecosystem support for bridges, bots, and appservices. It requires PostgreSQL, which Conclave already runs for Planka, so there is no additional infrastructure overhead.

| Property | Value |
|---|---|
| Source image | `matrixdotorg/synapse:latest` |
| Internal port | 8008 |
| Data directory | `/workspace/data/synapse/` |
| Database | PostgreSQL 16 (shared instance, `synapse` database) |
| Config file | `/workspace/config/synapse/homeserver.yaml` |
| Nginx path | `/_matrix/` → `http://127.0.0.1:8008` |
| Direct port | 8008 |

**Key configuration:**

```yaml
server_name: "${MATRIX_SERVER_NAME}"
public_baseurl: "https://${EXTERNAL_HOSTNAME}/"
database:
  name: psycopg2
  args:
    host: /var/run/postgresql
    database: synapse
    user: synapse
    cp_min: 5
    cp_max: 10
media_store_path: "/workspace/data/synapse/media_store"
enable_registration: false
listeners:
  - port: 8008
    type: http
    resources:
      - names: [client, federation]
```

**First-boot initialization:**

```bash
python -m synapse.app.homeserver \
    --server-name="${MATRIX_SERVER_NAME}" \
    --config-path=/workspace/config/synapse/homeserver.yaml \
    --generate-config \
    --report-stats=no
# Then patch the generated config with Conclave-specific overrides
```

### 3.2 Element Web (Matrix Client)

A static web build of the Element Matrix client, served by nginx directly. No runtime process required.

| Property | Value |
|---|---|
| Source image | `vectorim/element-web:latest` |
| Asset path | `/opt/element-web/` |
| Internal port | None (static files via nginx) |
| Config | `/workspace/config/element-web/config.json` |
| Nginx path | `/element/` → static files |

**Configuration (`config.json`):**

```json
{
    "default_server_config": {
        "m.homeserver": {
            "base_url": "https://${EXTERNAL_HOSTNAME}",
            "server_name": "${MATRIX_SERVER_NAME}"
        }
    },
    "brand": "Element",
    "disable_guests": true
}
```

### 3.3 PostgreSQL 16

Shared relational database. Synapse and Planka each get their own database and user for isolation. Available for any future service that needs SQL.

| Property | Value |
|---|---|
| Installation | `apt` (PostgreSQL APT repository) |
| Internal port | 5432 (localhost + unix socket) |
| Data directory | `/workspace/data/postgres/` |
| Unix socket | `/var/run/postgresql/` |
| Databases | `synapse`, `planka` |
| Direct port | Not exposed externally |

**First-boot initialization:**

```bash
pg_createcluster 16 main --datadir=/workspace/data/postgres
pg_ctlcluster 16 main start

sudo -u postgres createuser synapse
sudo -u postgres createdb --owner=synapse --encoding=UTF8 --locale=C synapse
sudo -u postgres createuser planka
sudo -u postgres createdb --owner=planka planka

sudo -u postgres psql -c "ALTER USER synapse PASSWORD '${SYNAPSE_DB_PASSWORD}';"
sudo -u postgres psql -c "ALTER USER planka PASSWORD '${PLANKA_DB_PASSWORD}';"
```

### 3.4 Planka (Kanban Board)

Planka is a Trello-like kanban board built with React and Sails.js. Requires PostgreSQL.

| Property | Value |
|---|---|
| Source image | `ghcr.io/plankanban/planka:latest` |
| Runtime | Node.js (Sails.js) |
| Internal port | 1337 |
| Data directory | `/workspace/data/planka/` |
| Database | PostgreSQL 16 (shared instance, `planka` database) |
| Nginx path | `/planka/` → `http://127.0.0.1:1337` |
| Direct port | 1337 |

**Environment:**

```bash
BASE_URL=https://${EXTERNAL_HOSTNAME}/planka
DATABASE_URL=postgresql://planka:${PLANKA_DB_PASSWORD}@127.0.0.1:5432/planka
SECRET_KEY=${PLANKA_SECRET_KEY}
DEFAULT_ADMIN_EMAIL=${PLANKA_ADMIN_EMAIL}
DEFAULT_ADMIN_PASSWORD=${PLANKA_ADMIN_PASSWORD}
DEFAULT_ADMIN_NAME=Admin
DEFAULT_ADMIN_USERNAME=admin
TRUST_PROXY=true
```

### 3.5 ChromaDB (Vector Database)

ChromaDB stores embeddings from Matrix conversations, documents, and code for RAG workloads. Uses embedded SQLite + hnswlib — no external database needed.

| Property | Value |
|---|---|
| Source image | `chromadb/chroma:latest` |
| Internal port | 8000 |
| Data directory | `/workspace/data/chromadb/` |
| Database | SQLite + hnswlib (embedded) |
| Auth | Token-based |
| Nginx path | `/chromadb/` → `http://127.0.0.1:8000` |
| Direct port | 8000 |

**Environment:**

```bash
IS_PERSISTENT=TRUE
PERSIST_DIRECTORY=/workspace/data/chromadb
ANONYMIZED_TELEMETRY=FALSE
CHROMA_SERVER_AUTHN_CREDENTIALS=${CHROMADB_TOKEN}
CHROMA_SERVER_AUTHN_PROVIDER=chromadb.auth.token_authn.TokenAuthenticationServerProvider
```

### 3.6 ChromaDB Admin UI

An existing open-source GUI for browsing and editing ChromaDB collections.

| Property | Value |
|---|---|
| Package | TBD — evaluate at build time |
| Internal port | 3100 |
| Nginx path | `/chromadb-admin/` → `http://127.0.0.1:3100` |
| Direct port | 3100 |
| Auth | nginx basic auth |

*Fallback: ChromaDB's built-in Swagger/OpenAPI explorer or the `chroma` CLI.*

### 3.7 Ollama (LLM Inference Server)

Ollama provides an OpenAI-compatible API for LLM inference on the GPU.

| Property | Value |
|---|---|
| Source image | `ollama/ollama:latest` |
| Binary path | `/usr/bin/ollama` |
| Internal port | 11434 |
| Model cache | `/workspace/data/ollama/models/` |
| Nginx path | `/ollama/` → `http://127.0.0.1:11434` |
| Direct port | 11434 |

**Environment:**

```bash
OLLAMA_HOST=0.0.0.0:11434
OLLAMA_MODELS=/workspace/data/ollama/models
OLLAMA_KEEP_ALIVE=24h
```

**Model pre-pull (background oneshot task):**

```bash
#!/bin/bash
# ollama-pull.sh
set -e
MODEL="${DEFAULT_OLLAMA_MODEL:-llama3.1:8b}"

for i in $(seq 1 60); do
    curl -sf http://127.0.0.1:11434/api/tags > /dev/null && break
    sleep 2
done

if ! ollama list | grep -q "$MODEL"; then
    echo "Pulling $MODEL..."
    ollama pull "$MODEL"
else
    echo "$MODEL already cached."
fi
```

### 3.8 N.eko (Interactive Browser)

N.eko provides a WebRTC-streamed browser session accessible via web UI, with support for programmatic control via Playwright/CDP for AI agent automation.

| Property | Value |
|---|---|
| Source | Built from source (`github.com/m1k1o/neko`) |
| Internal port | 8080 (HTTP/WebSocket) |
| WebRTC ports | 52000–52100 (UDP) |
| CDP port | 9222 (Chromium remote debugging) |
| Data directory | `/workspace/data/neko/` |
| Nginx path | `/neko/` → `http://127.0.0.1:8080` |
| Direct port | 8080 |

**Environment:**

```bash
NEKO_SCREEN=1920x1080@30
NEKO_PASSWORD=${NEKO_PASSWORD}
NEKO_PASSWORD_ADMIN=${NEKO_ADMIN_PASSWORD}
NEKO_BIND=0.0.0.0:8080
NEKO_EPR=52000-52100
NEKO_ICELITE=true
```

**Integration:** N.eko is built from source and its display stack runs as separate supervised processes:

1. **dbus-daemon** — system bus (priority 14)
2. **Xvfb** — virtual framebuffer on DISPLAY `:99` (priority 15)
3. **PulseAudio** — audio server in daemonless mode (priority 15)
4. **openbox** — lightweight window manager (priority 16)
5. **Chromium** — Playwright Chromium with CDP enabled on port 9222, run as a separate supervised process (priority 17)
6. **neko serve** — the WebRTC streaming server (priority 50)

**Programmatic access:** Playwright Chromium is installed via `playwright install --with-deps chromium` and symlinked to `/usr/local/bin/chromium-pw`. It runs with `--remote-debugging-port=9222` for CDP-based automation by AI agents (pi, Claude Code).

### 3.9 Coding Agents: pi + Claude Code

The developer workspace runs two complementary AI coding agents in a persistent tmux session, accessible via both a web terminal (ttyd) and SSH.

**pi** is the primary coding agent — a minimal, extensible terminal coding harness from the pi-mono toolkit. It supports skills, prompt templates, extensions, and multi-provider LLM access (Anthropic, OpenAI, Google, Ollama, and others). It can use the local Ollama instance for inference or external APIs.

**Claude Code** is Anthropic's official coding agent. It and pi cooperate well in the same workspace, and both can be used depending on the task.

| Property | Value |
|---|---|
| pi package | `@mariozechner/pi-coding-agent` (npm) |
| Claude Code package | `@anthropic-ai/claude-code` (npm) |
| Terminal server | ttyd (web-based terminal over WebSocket) |
| Session manager | tmux |
| Internal port | 7681 (ttyd web UI) |
| SSH port | 22 |
| Data directory | `/workspace/data/coding/` |
| Nginx path | `/terminal/` → `http://127.0.0.1:7681` |
| Direct port | 7681 (ttyd), 22 (SSH) |

**Persistent configuration on the volume:**

```
/workspace/data/coding/
├── .pi/                        # pi global config
│   └── agent/
│       ├── SYSTEM.md           # Custom system prompt
│       ├── AGENTS.md           # Global agent instructions
│       ├── skills/             # Installed skills
│       ├── prompts/            # Prompt templates
│       ├── extensions/         # pi extensions
│       ├── themes/             # TUI themes
│       └── models.json         # Custom model definitions (e.g., local Ollama)
├── .claude/                    # Claude Code config
│   ├── settings.json
│   └── skills/                 # Claude Code skills
├── .tmux.conf                  # tmux configuration
└── projects/                   # Working directory for code projects
```

**pi local Ollama integration (`models.json`):**

```json
[
    {
        "id": "llama3.1:8b",
        "name": "Llama 3.1 8B (Local)",
        "api": "openai-completions",
        "provider": "ollama",
        "baseUrl": "http://127.0.0.1:11434/v1",
        "reasoning": false,
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 128000,
        "maxTokens": 32000
    }
]
```

**ttyd configuration:**

```bash
ttyd \
    --port 7681 \
    --writable \
    --credential "${TTYD_USER}:${TTYD_PASSWORD}" \
    /opt/conclave/scripts/tmux-workspace.sh
```

The `tmux-workspace.sh` script sources `/workspace/config/agent-env.sh` (agent credentials) into the environment, then creates a tmux session with three windows: `dev` (bash shell), `pi` (pi coding agent), and `claude` (Claude Code).

**SSH setup:** OpenSSH server with key-based auth only. Authorized keys stored at `/workspace/data/coding/.ssh/authorized_keys` (dev user home, on persistent volume).

---

## 4. Directory Layout

All persistent state lives under `/workspace`. The container filesystem is ephemeral.

```
/workspace/
├── config/                       # Configuration files (generated on first boot)
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── htpasswd
│   │   └── conf.d/
│   │       └── services.conf
│   ├── synapse/
│   │   └── homeserver.yaml
│   ├── element-web/
│   │   └── config.json
│   ├── planka/
│   │   └── .env
│   ├── chromadb/
│   │   └── .env
│   ├── neko/
│   │   └── .env
│   ├── agent-env.sh              # Agent credentials (sourced into tmux)
│   └── generated-secrets.env     # Auto-generated secrets (first boot)
│
├── data/                         # Application runtime data
│   ├── synapse/                  # Synapse media, signing keys
│   ├── postgres/                 # PostgreSQL data directory
│   ├── planka/                   # Attachments, avatars, images
│   ├── chromadb/                 # Vector DB persistence
│   ├── ollama/
│   │   └── models/               # Cached model weights
│   ├── neko/                     # Browser profiles, downloads
│   └── coding/                   # dev user home — pi + Claude Code config, skills, projects
│       ├── .pi/
│       ├── .claude/
│       ├── .ssh/
│       │   └── authorized_keys   # SSH public keys (dev user)
│       └── projects/
│
└── logs/                         # Centralized logs
    ├── nginx/
    ├── synapse/
    ├── postgres/
    ├── planka/
    ├── chromadb/
    ├── ollama/
    ├── neko/
    └── ttyd/
```

---

## 5. Nginx Reverse Proxy

Nginx listens on port **8888** (the primary unified entry point) and routes requests by path prefix. Each service also exposes its own direct port as a fallback.

### 5.1 Path Routing Map

| Path | Backend | WebSocket | Auth |
|---|---|---|---|
| `/_matrix/` | `127.0.0.1:8008` | Yes (sync) | Synapse built-in |
| `/_synapse/` | `127.0.0.1:8008` | No | Synapse built-in |
| `/element/` | Static files | No | None (Matrix login) |
| `/planka/` | `127.0.0.1:1337` | Yes (real-time) | Planka built-in |
| `/chromadb/` | `127.0.0.1:8000` | No | Token auth |
| `/chromadb-admin/` | `127.0.0.1:3100` | No | nginx basic auth |
| `/ollama/` | `127.0.0.1:11434` | No | nginx basic auth |
| `/neko/` | `127.0.0.1:8080` | Yes (WebRTC signaling) | N.eko built-in |
| `/terminal/` | `127.0.0.1:7681` | Yes (ttyd) | ttyd basic auth |
| `/` | Dashboard (static HTML) | No | nginx basic auth |

### 5.2 Core Nginx Config

```nginx
worker_processes auto;
error_log /workspace/logs/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    keepalive_timeout 65;

    access_log /workspace/logs/nginx/access.log;

    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
    }

    server {
        listen 8888;
        server_name _;

        # --- Dashboard ---
        location = / {
            auth_basic "Conclave";
            auth_basic_user_file /workspace/config/nginx/htpasswd;
            root /opt/dashboard;
            index index.html;
        }

        # --- Matrix Synapse ---
        location /_matrix/ {
            proxy_pass http://127.0.0.1:8008;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 600s;
            client_max_body_size 100M;
        }
        location /_synapse/ {
            proxy_pass http://127.0.0.1:8008;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # --- Matrix well-known ---
        location /.well-known/matrix/server {
            return 200 '{"m.server": "$host:443"}';
            add_header Content-Type application/json;
        }
        location /.well-known/matrix/client {
            return 200 '{"m.homeserver": {"base_url": "https://$host"}}';
            add_header Content-Type application/json;
            add_header Access-Control-Allow-Origin *;
        }

        # --- Element Web ---
        location /element/ {
            alias /opt/element-web/;
            try_files $uri $uri/ /element/index.html;
        }

        # --- Planka ---
        location /planka/ {
            proxy_pass http://127.0.0.1:1337/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # --- ChromaDB API ---
        location /chromadb/ {
            proxy_pass http://127.0.0.1:8000/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # --- ChromaDB Admin ---
        location /chromadb-admin/ {
            auth_basic "ChromaDB Admin";
            auth_basic_user_file /workspace/config/nginx/htpasswd;
            proxy_pass http://127.0.0.1:3100/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # --- Ollama ---
        location /ollama/ {
            auth_basic "Ollama API";
            auth_basic_user_file /workspace/config/nginx/htpasswd;
            proxy_pass http://127.0.0.1:11434/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 600s;
        }

        # --- N.eko ---
        location /neko/ {
            proxy_pass http://127.0.0.1:8080/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # --- ttyd Terminal ---
        location /terminal/ {
            proxy_pass http://127.0.0.1:7681/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

### 5.3 Port Summary

| Port | Service | Exposure |
|---|---|---|
| 8888 | nginx (unified entry) | Primary — expose via Runpod |
| 22 | SSH | Expose via Runpod |
| 8008 | Synapse | Fallback direct access |
| 1337 | Planka | Fallback direct access |
| 5432 | PostgreSQL | Internal only |
| 8000 | ChromaDB | Fallback direct access |
| 3100 | ChromaDB Admin | Fallback direct access |
| 11434 | Ollama | Fallback direct access |
| 8080 | N.eko | Fallback direct access |
| 7681 | ttyd | Fallback direct access |
| 9222 | Chromium CDP | Internal only |
| 52000–52100/udp | N.eko WebRTC | Expose via Runpod |

---

## 6. Dockerfile Strategy

The build uses a single-stage Dockerfile with Ansible playbooks to install and configure all services. Ansible is installed temporarily, runs the playbook, and is then removed to keep the final image clean.

### 6.1 Dockerfile

```dockerfile
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip software-properties-common && \
    pip3 install ansible passlib && \
    rm -rf /var/lib/apt/lists/*

COPY ansible/ /tmp/ansible/
COPY configs/ /opt/conclave/configs/
COPY scripts/ /opt/conclave/scripts/
COPY dashboard/ /opt/dashboard/
COPY skills/ /opt/conclave/skills-src/

RUN cd /tmp/ansible && ansible-playbook -i inventory.yml playbook.yml

# Clean up Ansible
RUN pip3 uninstall -y ansible ansible-core passlib && \
    rm -rf /tmp/ansible /root/.ansible && \
    apt-get purge -y software-properties-common && \
    apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN chmod +x /opt/conclave/scripts/*.sh

EXPOSE 8888 22 8008 1337 8000 3100 11434 8080 7681
EXPOSE 52000-52100/udp

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD /opt/conclave/scripts/healthcheck.sh

ENTRYPOINT ["/opt/conclave/scripts/startup.sh"]
```

**Build-time notes:**

- Ansible and its dependencies are removed after the playbook runs to reduce image size.
- Each service is installed by its own Ansible role (see `ansible/roles/`), gated by a `conclave_*_enabled` toggle in `ansible/group_vars/all.yml`.
- N.eko is built from source (Go build of `github.com/m1k1o/neko`), along with `libclipboard`.
- Playwright installs Chromium with system dependencies via `playwright install --with-deps chromium`.
- Service versions are pinned in `ansible/group_vars/all.yml`.

---

## 7. Startup Script (`startup.sh`)

The entrypoint handles first-boot initialization, config generation, and supervisor launch.

### 7.1 Flow

```
startup.sh
│
├── 1. Detect first boot (check /workspace/.initialized)
├── 2. Create directory structure under /workspace/{config,data,logs}/
├── 3. Generate secrets for any not provided via env vars
│      └── Write to /workspace/config/generated-secrets.env
├── 4. Generate configs from env vars + templates
│      ├── synapse/homeserver.yaml
│      ├── element-web/config.json
│      ├── planka/.env
│      ├── nginx/nginx.conf + htpasswd
│      ├── chromadb/.env
│      ├── neko/.env
│      ├── coding agent configs (.pi/, .claude/)
│      └── agent-env.sh (agent credentials for tmux sessions)
├── 5. Initialize PostgreSQL (first boot only)
│      ├── pg_createcluster
│      ├── Create synapse + planka databases and users
│      └── Run Synapse DB migrations
├── 6. Set up SSH authorized_keys
├── 7. Symlink configs to expected paths
├── 8. Touch /workspace/.initialized
└── 9. exec supervisord -n (foreground, takes over PID 1)
```

### 7.2 Required Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MATRIX_SERVER_NAME` | No | `conclave.local` | Matrix server domain name |
| `EXTERNAL_HOSTNAME` | No | `localhost` | Pod's external hostname (Runpod proxy URL) |
| `NGINX_USER` | No | `admin` | nginx basic auth username |
| `NGINX_PASSWORD` | Yes | — | nginx basic auth password |
| `SYNAPSE_DB_PASSWORD` | No | (generated) | PostgreSQL password for Synapse |
| `PLANKA_DB_PASSWORD` | No | (generated) | PostgreSQL password for Planka |
| `PLANKA_SECRET_KEY` | No | (generated) | Planka session secret |
| `PLANKA_ADMIN_EMAIL` | No | `admin@local` | Planka default admin email |
| `PLANKA_ADMIN_PASSWORD` | No | `changeme` | Planka default admin password |
| `CHROMADB_TOKEN` | No | (generated) | ChromaDB API auth token |
| `NEKO_PASSWORD` | No | `neko` | N.eko viewer password |
| `NEKO_ADMIN_PASSWORD` | No | `admin` | N.eko admin password |
| `TTYD_USER` | No | `admin` | Web terminal username |
| `TTYD_PASSWORD` | No | `$NGINX_PASSWORD` | Web terminal password (falls back to NGINX_PASSWORD) |
| `ANTHROPIC_API_KEY` | No | — | API key for Claude Code and pi (Anthropic provider) |
| `OPENAI_API_KEY` | No | — | API key for pi (OpenAI provider) |
| `DEFAULT_OLLAMA_MODEL` | No | `llama3.1:8b` | Model to pre-pull on first boot |
| `SSH_AUTHORIZED_KEYS` | No | — | Public keys (newline-separated) |
| `CONCLAVE_SETUP_ONLY` | No | — | Set to `1` to run setup and exit without starting supervisord (for testing) |
| `CONCLAVE_DEV_PASSWORD` | No | `changeme` | Password for the `dev` user (set at build time via Ansible, updated on each boot by startup.sh if provided) |
| `CONCLAVE_AGENT_USER` | No | `agent` | Username for the agent user in Matrix and Planka |

Secrets not provided via env vars are auto-generated on first boot and written to `/workspace/config/generated-secrets.env` for reference. This includes `ADMIN_MATRIX_PASSWORD`, `AGENT_MATRIX_PASSWORD`, and `AGENT_PLANKA_PASSWORD` for the automatically created admin and agent users.

---

## 8. Supervisord Configuration

The actual supervisord config is at `configs/supervisord.conf` and is deployed to `/etc/supervisor/conf.d/conclave.conf` by the base Ansible role.

```ini
[supervisord]
nodaemon=true
logfile=/workspace/logs/supervisord.log
pidfile=/var/run/supervisord.pid

[unix_http_server]
file=/var/run/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpc_interface_factory = supervisor.rpc.interface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///var/run/supervisor.sock

; ===========================================================
; Core Infrastructure (priority 10)
; ===========================================================

[program:postgres]
command=/usr/lib/postgresql/16/bin/postgres -D /workspace/data/postgres
user=postgres
autostart=true
autorestart=true
priority=10
stdout_logfile=/workspace/logs/postgres/stdout.log
stderr_logfile=/workspace/logs/postgres/stderr.log

[program:nginx]
command=nginx -g "daemon off;" -c /workspace/config/nginx/nginx.conf
autostart=true
autorestart=true
priority=10
stdout_logfile=/workspace/logs/nginx/stdout.log
stderr_logfile=/workspace/logs/nginx/stderr.log

[program:sshd]
command=/usr/sbin/sshd -D
autostart=true
autorestart=true
priority=10

; ===========================================================
; N.eko Display Stack (priority 14-17)
; ===========================================================

[program:dbus]
command=dbus-daemon --system --nofork
autostart=true
autorestart=true
priority=14

[program:xvfb]
command=Xvfb :99 -screen 0 1920x1080x24
autostart=true
autorestart=true
priority=15

[program:pulseaudio]
command=pulseaudio --daemonize=no --exit-idle-time=-1
autostart=true
autorestart=true
priority=15

[program:openbox]
command=openbox
environment=DISPLAY=":99"
autostart=true
autorestart=true
priority=16

[program:chromium]
command=/usr/local/bin/chromium-pw --user-data-dir=/workspace/data/neko/chromium-profile --no-first-run --start-maximized --force-dark-mode --no-sandbox --disable-dev-shm-usage --disable-crash-reporter --disable-blink-features=AutomationControlled --use-gl=angle --use-angle=swiftshader --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=*
environment=DISPLAY=":99"
autostart=true
autorestart=true
priority=17
stdout_logfile=/workspace/logs/neko/chromium-stdout.log
stderr_logfile=/workspace/logs/neko/chromium-stderr.log

; ===========================================================
; Application Services (priority 30-50)
; ===========================================================

[program:synapse]
command=python3 -m synapse.app.homeserver --config-path=/workspace/config/synapse/homeserver.yaml
autostart=true
autorestart=true
priority=30
stdout_logfile=/workspace/logs/synapse/stdout.log
stderr_logfile=/workspace/logs/synapse/stderr.log

[program:chromadb]
command=chroma run --host 0.0.0.0 --port 8000 --path /workspace/data/chromadb
autostart=true
autorestart=true
priority=30
stdout_logfile=/workspace/logs/chromadb/stdout.log
stderr_logfile=/workspace/logs/chromadb/stderr.log

[program:ollama]
command=/usr/bin/ollama serve
environment=OLLAMA_HOST="0.0.0.0:11434",OLLAMA_MODELS="/workspace/data/ollama/models",OLLAMA_KEEP_ALIVE="24h"
autostart=true
autorestart=true
priority=30
stdout_logfile=/workspace/logs/ollama/stdout.log
stderr_logfile=/workspace/logs/ollama/stderr.log

[program:ttyd]
command=ttyd --port 7681 --writable --credential %(ENV_TTYD_USER)s:%(ENV_TTYD_PASSWORD)s /opt/conclave/scripts/tmux-workspace.sh
user=dev
directory=/workspace/data/coding/projects
environment=HOME="/workspace/data/coding"
autostart=true
autorestart=true
priority=30
stdout_logfile=/workspace/logs/ttyd/stdout.log
stderr_logfile=/workspace/logs/ttyd/stderr.log

[program:planka]
command=node /opt/planka/app.js
directory=/opt/planka
environment=NODE_ENV="production",PORT="1337"
autostart=true
autorestart=true
priority=40
stdout_logfile=/workspace/logs/planka/stdout.log
stderr_logfile=/workspace/logs/planka/stderr.log

[program:neko]
command=/usr/local/bin/neko serve
environment=DISPLAY=":99",NEKO_BIND="0.0.0.0:8080",NEKO_SCREEN="1920x1080@30",NEKO_EPR="52000-52100",NEKO_ICELITE="true"
autostart=true
autorestart=true
priority=50
stdout_logfile=/workspace/logs/neko/stdout.log
stderr_logfile=/workspace/logs/neko/stderr.log

; ===========================================================
; Post-Start Tasks (priority 99, oneshot)
; ===========================================================

[program:ollama-pull]
command=/opt/conclave/scripts/ollama-pull.sh
autostart=true
autorestart=false
startsecs=0
exitcodes=0
priority=99
stdout_logfile=/workspace/logs/ollama/pull.log
stderr_logfile=/workspace/logs/ollama/pull-error.log

[program:create-users]
command=/opt/conclave/scripts/create-users.sh
autostart=true
autorestart=false
startsecs=0
exitcodes=0
priority=99
stdout_logfile=/workspace/logs/create-users.log
stderr_logfile=/workspace/logs/create-users-error.log
```

---

## 9. Authentication Summary

| Service | Built-in Auth | nginx Basic Auth | Notes |
|---|---|---|---|
| Synapse | Matrix user auth | No | Registration disabled by default |
| Element Web | Matrix login | No | Delegates to Synapse |
| Planka | Username/password | No | Has own user management |
| ChromaDB API | Token auth | No | Token in request header |
| ChromaDB Admin | No | **Yes** | Unprotected service |
| Ollama | No | **Yes** | Unprotected API |
| N.eko | Password-based | No | Viewer + admin passwords |
| ttyd | Basic auth (built-in) | No | Via ttyd `-c` flag |
| SSH | Key-based | N/A | No password auth allowed |
| Dashboard | No | **Yes** | Static page |

All nginx basic auth shares `/workspace/config/nginx/htpasswd`.

---

## 10. Dashboard

A simple static HTML page served at `/` providing links to all services and live status indicators.

Features:
- Service links with descriptions
- JavaScript-based health checks (fetch to each endpoint, green/red indicators)
- Port reference table
- Quick-start guide for first-time setup

Built into the image at `/opt/dashboard/`. No persistence required.

---

## 11. Security Hardening

### 11.1 SSH Hardening

The `ssh` Ansible role applies the following `sshd_config` settings:

| Setting | Value |
|---|---|
| `PermitRootLogin` | `no` |
| `PasswordAuthentication` | `no` |
| `PubkeyAuthentication` | `yes` |
| `X11Forwarding` | `no` |
| `AllowAgentForwarding` | `no` |
| `MaxAuthTries` | `3` |
| `LoginGraceTime` | `30` |

SSH keys are installed from the `SSH_AUTHORIZED_KEYS` environment variable into `/workspace/data/coding/.ssh/authorized_keys` at each boot by `startup.sh`. Users connect as the `dev` user.

### 11.2 fail2ban

The `fail2ban` Ansible role configures two jails:

| Jail | Port | Max Retries | Ban Time | Log Path |
|---|---|---|---|---|
| `sshd` | `ssh` | 5 | 3600s (1 hour) | (default) |
| `nginx-http-auth` | `http,https` | 5 | 3600s (1 hour) | `/workspace/logs/nginx/stderr.log` |

### 11.3 Dev User

An unprivileged `dev` user is created by the `base` Ansible role:

- **Home directory:** `/workspace/data/coding` (on persistent volume)
- **Groups:** `sudo`
- **Shell:** `/bin/bash`
- **Password:** Set via `CONCLAVE_DEV_PASSWORD` (default `changeme`), hashed with SHA-512 at build time. If `CONCLAVE_DEV_PASSWORD` is set as an environment variable at runtime, `startup.sh` updates the password on each boot.

The `dev` user has `sudo` access with password for administrative tasks. Interactive sessions (ttyd/tmux) run as `dev`, not root.

### 11.4 Validation

The `scripts/test-security.sh` script validates all hardening settings:
- Runs the Ansible playbook and `startup.sh` in setup-only mode
- Verifies dev user existence, groups, home directory, and shell
- Checks all `sshd_config` settings
- Confirms fail2ban jails are configured
- Validates directory ownership and permissions

---

## 12. Known Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| N.eko source build | Medium | N.eko is built from source with Go and requires libclipboard and GStreamer. Version pinned in `group_vars/all.yml`. |
| Planka path-prefix support | Medium | Planka may not natively support `/planka/` subpath. Test with `BASE_URL` set to the full prefixed URL. **Fallback:** direct port access only. |
| Memory pressure | Medium | System RAM on A100/H100 pods is typically 128–256GB — ample for all services. Ollama with a loaded model is the heaviest consumer. Set `OLLAMA_KEEP_ALIVE` appropriately; unload models when idle. |
| ChromaDB admin UI maturity | Low | The ecosystem of ChromaDB GUIs is young. **Fallback:** Swagger UI or `chroma` CLI. |
| WebRTC UDP on Runpod | Medium | Runpod may not expose arbitrary UDP ranges. **Mitigation:** `NEKO_ICELITE=true`; test with TURN relay if direct UDP fails. |
| Synapse resource usage | Medium | Synapse can be memory-hungry in large federated rooms. Mitigated by disabling federation by default and keeping the deployment private. |

---

## 13. Build and Deployment

### 13.1 Building

```bash
docker build -t conclave:latest .
docker tag conclave:latest your-registry/conclave:latest
docker push your-registry/conclave:latest
```

### 13.2 Runpod Template

| Field | Value |
|---|---|
| Container image | `your-registry/conclave:latest` |
| Docker command | (empty — uses ENTRYPOINT) |
| Volume mount | `/workspace` |
| Exposed HTTP ports | `8888, 8008, 1337, 8000, 3100, 11434, 8080, 7681` |
| Exposed TCP ports | `22` |
| Exposed UDP ports | `52000-52100` |
| Environment variables | See Section 7.2 |

### 13.3 First Boot Checklist

1. Pod starts → `startup.sh` detects no `/workspace/.initialized`
2. Directory structure created under `/workspace/`
3. Secrets generated, configs written from templates
4. PostgreSQL initialized, `synapse` and `planka` databases created
5. Synapse config generated and patched
6. Supervisord launched — all services start
7. Ollama pulls default model in background
8. Admin and agent users created in Matrix and Planka (background oneshot)
9. Access dashboard at `https://{pod-id}-8888.proxy.runpod.net/`
10. Log into Element and Planka with admin or agent credentials
11. Agent credentials are available in the tmux terminal via `agent-env.sh`

---

## 14. File Manifest

```
conclave/
├── Dockerfile                       # Ansible-based single-stage build
├── CLAUDE.md                        # LLM behavioral guidelines
├── spec.md                          # This specification
├── README.md                        # Getting-started guide
├── .gitignore
├── ansible/
│   ├── playbook.yml                 # Master playbook (12 roles)
│   ├── inventory.yml                # Localhost inventory
│   ├── group_vars/
│   │   └── all.yml                  # Service toggles, versions, ports
│   └── roles/
│       ├── base/tasks/main.yml      # System packages, dev user, Node.js
│       ├── postgres/tasks/main.yml
│       ├── synapse/tasks/main.yml
│       ├── element_web/tasks/main.yml
│       ├── planka/tasks/main.yml
│       ├── chromadb/tasks/main.yml
│       ├── ollama/tasks/main.yml
│       ├── neko/tasks/main.yml      # Build from source + Playwright Chromium
│       ├── coding_agents/tasks/main.yml
│       ├── ttyd/tasks/main.yml
│       ├── nginx/tasks/main.yml
│       ├── ssh/tasks/main.yml       # SSH hardening
│       └── fail2ban/tasks/main.yml  # Intrusion prevention
├── scripts/
│   ├── startup.sh                   # Entrypoint — first-boot init + supervisor launch
│   ├── ollama-pull.sh               # Background model pre-pull
│   ├── create-users.sh             # Post-start user creation (oneshot)
│   ├── tmux-workspace.sh           # tmux session launcher (sourced by ttyd)
│   ├── init-postgres.sh             # PostgreSQL first-boot setup
│   ├── init-synapse.sh              # Synapse config generation
│   ├── healthcheck.sh               # Container health check
│   ├── dev.sh                       # Local build + run helper
│   ├── launch-runpod.sh             # Runpod pod deployment via API
│   └── test-security.sh             # Security hardening validation
├── configs/
│   ├── supervisord.conf             # Supervisord process definitions
│   ├── nginx/
│   │   └── nginx.conf.template
│   ├── synapse/
│   │   └── homeserver.override.yaml
│   ├── element-web/
│   │   └── config.json.template
│   └── coding/
│       ├── pi-models.json           # Default Ollama model definition for pi
│       └── tmux.conf                # Default tmux configuration
├── skills/
│   ├── claude-code/
│   │   └── launch-conclave.md
│   └── matrix/
│       ├── SKILL.md
│       └── matrix.py
└── dashboard/
    └── index.html
```

---

## 15. Future Enhancements

- **Matrix bridges:** Discord, IRC, or Slack bridges as additional supervised processes.
- **Monitoring:** Prometheus node_exporter + Grafana for resource visibility.
- **Backup automation:** Scheduled backup of `/workspace/data/` to S3-compatible storage.
- **Auto-SSL:** Certbot for Let's Encrypt if a custom domain is configured.
- **Podman fallback:** Install Podman for services that resist native integration.
- **pi extensions:** Custom extensions for Matrix integration, Planka task management, and ChromaDB-powered RAG within the coding agent.
- **Multi-agent coordination:** pi instances spawned via tmux for parallel task execution, coordinated through Matrix channels.
