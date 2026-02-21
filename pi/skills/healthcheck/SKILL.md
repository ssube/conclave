---
name: healthcheck
description: >-
  Check the health of all Conclave services. Use when monitoring infrastructure,
  diagnosing issues, verifying services are running, or during periodic
  housekeeping checks. Returns structured status for each service.
---

# Healthcheck Skill

Deterministic health check for all Conclave services. No LLM in the loop —
runs curl and supervisor checks with structured output.

## Usage

### Human-readable output

```bash
bash {baseDir}/healthcheck.sh
```

### JSON output (for programmatic use)

```bash
bash {baseDir}/healthcheck.sh --json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All services healthy |
| 1 | Warnings — degraded but functional |
| 2 | Critical — needs immediate attention |

## Services Checked

| Service | Check | URL/Method |
|---------|-------|------------|
| postgres | supervisor + `pg_isready` | — |
| nginx | supervisor + HTTP | `http://127.0.0.1:8888/` |
| synapse | supervisor + HTTP | `http://127.0.0.1:8008/_matrix/client/versions` |
| chromadb | supervisor + HTTP | `http://127.0.0.1:8000/api/v2/heartbeat` |
| ollama | supervisor + HTTP | `http://127.0.0.1:11434/api/tags` |
| planka | supervisor + HTTP | `http://127.0.0.1:1337/` |
| ttyd | supervisor + HTTP | `http://127.0.0.1:7681/` |
| neko | supervisor + HTTP | `http://127.0.0.1:8080/` |
| chromium-cdp | supervisor + HTTP | `http://127.0.0.1:9222/json/version` |
| disk | `df` | `/workspace` filesystem |

## Status Levels

| Status | Meaning |
|--------|---------|
| `ok` | Service is running and responding |
| `warn` | Degraded — process running but HTTP failing, or disk >80% |
| `critical` | Process not running, or disk >90% |
| `down` | Unreachable (HTTP 000) |

## Example Output

```
=== Health Check — 2026-02-21T12:00:00Z ===
  OK    postgres        running, accepting connections
  OK    nginx           HTTP 200
  OK    synapse         HTTP 200
  OK    chromadb        HTTP 200
  OK    ollama          HTTP 200
  OK    planka          HTTP 200
  OK    ttyd            HTTP 200
  OK    neko            HTTP 200
  OK    chromium-cdp    HTTP 200
  OK    disk            42% used (58G free)

All clear.
```

## JSON Output

```json
{
  "timestamp": "2026-02-21T12:00:00Z",
  "max_severity": 0,
  "checks": {
    "postgres": {"status": "ok", "detail": "running, accepting connections"},
    "nginx": {"status": "ok", "detail": "HTTP 200"},
    "disk": {"status": "ok", "detail": "42% used (58G free)"}
  }
}
```

## Integration

The heartbeat extension calls this script automatically during pulse checks.
You can also run it manually to diagnose issues or verify after restarting services.
