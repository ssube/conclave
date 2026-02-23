---
name: conclave-build
description: >-
  Build, test, and iterate on the Conclave container. Use when making changes to
  Conclave services, configs, scripts, skills, or extensions and need to rebuild
  the container image and verify everything works.
---

# Conclave Build

Build and test the Conclave all-in-one container locally using `scripts/dev.sh`.

## Quick Reference

```bash
# Full cycle: build image + start container + run tests
bash scripts/dev.sh

# Individual steps
bash scripts/dev.sh build        # build the image only
bash scripts/dev.sh run          # start container (runs tests automatically)
bash scripts/dev.sh test         # run browser tests against running container
bash scripts/dev.sh stop         # stop and remove container
bash scripts/dev.sh clean        # stop container AND delete the workspace volume
bash scripts/dev.sh logs         # tail container logs
bash scripts/dev.sh creds        # print admin and agent passwords
```

## Build Process

The Dockerfile builds in this order:

1. **Base image**: `nvidia/cuda:12.4.1-runtime-ubuntu22.04`
2. **Copy into image**: `ansible/`, `configs/`, `dashboard/`, `pi/`
3. **Run Ansible playbook**: installs all services (postgres, nginx, synapse, chromadb,
   ollama, planka, neko, ttyd, chromium, coding agents)
4. **Copy scripts**: `scripts/` copied to `/opt/conclave/scripts/`
5. **Entrypoint**: `scripts/startup.sh`

## Container Runtime

All services run under **supervisord** (`configs/supervisord.conf`). Key programs:

| Priority | Service | Port |
|----------|---------|------|
| 10 | postgres, nginx, sshd, cron | 5432, 8888, 22, — |
| 14-17 | dbus, xvfb, pulseaudio, openbox, chromium | 9222 (internal) |
| 30 | synapse, chromadb, ollama, ttyd, pushgateway | 8008, 8000, 11434, 7681, 9091 |
| 40 | planka | 1337 |
| 50 | neko | 8080, 8081 (TCPMUX) |
| 99 | tmux-session, ollama-pull, create-users | oneshot |

## First Boot Flow

`startup.sh` runs on every container start:

1. Generate secrets (passwords, tokens) if first boot
2. Render config templates (nginx, element-web, planka, chromadb, neko)
3. Write `agent-env.sh` with credentials for coding agents
4. Sync pi skills/extensions to `/workspace/data/coding/.pi/agent/`
5. Copy default `pi-settings.json` and `cron.tab`
6. Launch supervisord

`create-users.sh` runs as a oneshot after services start:

1. Create Matrix admin + agent users
2. Login agent to Matrix, save access token to `agent-env.sh`
3. Create Matrix `#home` room, invite and join agent
4. Create Planka agent user, Work project, Tasks board, lists, and labels

## Testing

### Browser Tests (9 tests)

```bash
bash scripts/dev.sh test
```

Tests use Playwright with locally-installed Chromium. Tests cover:

1. **Dashboard** — loads, has `<h1>Conclave</h1>`
2. **Element Web** — loads, title contains "Element"
3. **Matrix API** — `/_matrix/client/versions` returns versions
4. **ChromaDB API** — `/chromadb/api/v2/heartbeat` responds
5. **Ollama API** — `/ollama/api/tags` returns models
6. **Terminal (ttyd)** — loads, has HTML content
7. **Planka login (localhost:1337)** — full login flow with terms acceptance
8. **Planka login (127.0.0.1:1337)** — same flow, different origin
9. **Neko WebRTC** — login and WebRTC connection established

### Healthcheck (inside container)

```bash
# Human-readable
bash /opt/conclave/scripts/agent-healthcheck.sh

# JSON output
bash /opt/conclave/scripts/agent-healthcheck.sh --json
```

Checks 11 services: postgres, nginx, synapse, chromadb, ollama, planka, ttyd,
neko, pushgateway, chromium-cdp, disk. Uses credentials from `generated-secrets.env`.

## Key Directories

| Path (in container) | Purpose |
|---------------------|---------|
| `/opt/conclave/configs/` | Config templates (baked into image) |
| `/opt/conclave/scripts/` | Startup, healthcheck, user creation scripts |
| `/opt/conclave/pi/` | Pi skills and extensions (image source) |
| `/workspace/config/` | Generated configs, secrets, agent-env.sh |
| `/workspace/data/coding/.pi/agent/` | Runtime skills/extensions (editable, persistent) |
| `/workspace/data/coding/projects/` | Agent working directory |
| `/workspace/logs/` | Service log files |

## Key Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Image build definition |
| `configs/supervisord.conf` | Process manager config |
| `scripts/startup.sh` | Container entrypoint, config rendering |
| `scripts/create-users.sh` | First-boot user and resource creation |
| `scripts/agent-healthcheck.sh` | Service health checker |
| `scripts/dev.sh` | Local dev build/run/test script |
| `scripts/test-browser-final.mjs` | Playwright end-to-end browser tests |
| `configs/coding/pi-settings.json` | Default pi extension settings (cron, heartbeat) |
| `configs/coding/cron.tab` | Default cron jobs (midnight housekeeping) |

## Typical Iteration Cycle

1. Edit files in the repo (configs, scripts, skills, ansible roles)
2. `bash scripts/dev.sh clean` — remove old container and volume
3. `bash scripts/dev.sh build` — rebuild image (~3-4 min with cache)
4. `bash scripts/dev.sh run` — start container, wait for first-boot, run tests
5. Check test output (9 browser tests should pass)
6. Verify specific changes: `sudo nerdctl exec conclave-dev <command>`

## Troubleshooting

- **Build fails with snapshot error**: Run `sudo nerdctl system prune -f` and rebuild
- **Service not starting**: Check logs with `sudo nerdctl exec conclave-dev cat /workspace/logs/<service>/stderr.log`
- **Browser tests fail**: Playwright auto-installs Chromium on first run (~170MB download)
- **Secrets/passwords**: `bash scripts/dev.sh creds` or check `/workspace/config/generated-secrets.env`
- **Container runtime**: Supports docker, podman, nerdctl. Override with `CONTAINER_RUNTIME=podman`
