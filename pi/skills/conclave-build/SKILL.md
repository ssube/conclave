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

### End-to-End Tests (`scripts/test-e2e.mjs`)

```bash
bash scripts/dev.sh test                             # auto-detects image type
node scripts/test-e2e.mjs                            # full image (47 tests)
node scripts/test-e2e.mjs --minimal                  # minimal image (22 tests, 25 skipped)
node scripts/test-e2e.mjs --test-ollama              # opt-in: Ollama generation test
node scripts/test-e2e.mjs --json                     # write JSON results to /tmp/conclave-test-results.json
```

Requires Playwright with Chromium installed locally:

```bash
npm install --no-save playwright && npx playwright install chromium
```

Tests combine Playwright browser automation, HTTP API calls, and in-container
skill execution via `scripts/e2e-skill-test.sh`. The `--minimal` flag skips tests
for services disabled in the minimal image (`fullOnly` tests).

#### Test Groups

| Group | Tests | What's covered |
|-------|------:|----------------|
| dashboard | 1 | Page loads, `<h1>Conclave</h1>` present |
| nginx | 2 | Rejects unauthenticated requests, accepts basic auth |
| matrix | 7 | API versions, login, room resolve, send/read messages, skill send/read, Element Web UI |
| chromadb | 6 | Heartbeat, create collection, add document, query, skill add/query, cleanup |
| planka | 9 | Browser login (localhost + 127.0.0.1), API login, get board, create/read card, skill create/list, web verify card, cleanup |
| ollama | 2–3 | API tags, API version, API generate (opt-in with `--test-ollama`) |
| neko | 7 | WebRTC login, WebRTC CDP verify, CDP version, open/list/close/verify-closed tabs |
| terminal | 3 | Load ttyd UI, exec write command, exec read output |
| pushgateway | 5 | Push metric, read metric, skill push, skill verify, cleanup |
| ssh | 1 | TCP connect to port 2222 |
| healthcheck | 1 | Run `agent-healthcheck.sh`, exit code 0 |

Full image: **47 tests** (48 with `--test-ollama`). Minimal image: **22 tests**, 25 skipped.

#### Minimal Mode

Tests tagged `{ fullOnly: true }` are skipped when `--minimal` is passed. These
cover services disabled in the minimal image: Matrix (Synapse + Element Web),
Planka, Ollama, and Pushgateway. All other tests (dashboard, nginx, chromadb,
neko, terminal, ssh, healthcheck) run against both images.

#### Skill Tests

Several groups include skill tests that run the actual skill scripts inside the
container. These use `skillExec()` which calls `scripts/e2e-skill-test.sh` — a
helper that sources `agent-env.sh`, `cd`s into the skill directory, and execs the
command. This validates that skills work end-to-end with real credentials.

Skills tested: `matrix` (send/read), `chromadb` (add/query), `planka`
(create/list), `prometheus` (push).

### Healthcheck (inside container)

```bash
# Human-readable
bash /opt/conclave/scripts/agent-healthcheck.sh

# JSON output
bash /opt/conclave/scripts/agent-healthcheck.sh --json
```

Checks up to 11 services: postgres, nginx, synapse, chromadb, ollama, planka,
ttyd, neko, pushgateway, chromium-cdp, disk. Reads `CONCLAVE_*_ENABLED` flags to
skip disabled services (so it passes on both full and minimal images). Exit codes:
0 = all healthy, 1 = warnings, 2 = critical.

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
| `scripts/test-e2e.mjs` | End-to-end tests (Playwright + HTTP + skills) |
| `configs/coding/pi-settings.json` | Default pi extension settings (cron, heartbeat) |
| `configs/coding/cron.tab` | Default cron jobs (midnight housekeeping) |

## Typical Iteration Cycle

1. Edit files in the repo (configs, scripts, skills, ansible roles)
2. `bash scripts/dev.sh clean` — remove old container and volume
3. `bash scripts/dev.sh build` — rebuild image (~3-4 min with cache)
4. `bash scripts/dev.sh run` — start container, wait for first-boot, run e2e tests
5. Check test output (47 tests for full image, 22 for minimal)
6. Verify specific changes: `sudo nerdctl exec conclave-dev <command>`

### Testing Both Images

When making changes that affect service enablement or the healthcheck, test both:

```bash
# Full image
docker build -t conclave:latest .
# start container, then:
node scripts/test-e2e.mjs

# Minimal image
docker build -f Dockerfile.minimal -t conclave-minimal:latest .
# start container, then:
node scripts/test-e2e.mjs --minimal
```

## Troubleshooting

- **Build fails with snapshot error**: Run `sudo nerdctl system prune -f` and rebuild
- **Service not starting**: Check logs with `sudo nerdctl exec conclave-dev cat /workspace/logs/<service>/stderr.log`
- **Browser tests fail**: Playwright auto-installs Chromium on first run (~170MB download)
- **Secrets/passwords**: `bash scripts/dev.sh creds` or check `/workspace/config/generated-secrets.env`
- **Container runtime**: Supports docker, podman, nerdctl. Override with `CONTAINER_RUNTIME=podman`
