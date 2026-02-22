---
name: prometheus
description: >-
  Push metrics to Prometheus Pushgateway for Grafana dashboards. Use when recording operational metrics, pushing gauge values to Prometheus, or updating Grafana dashboard data points.
---

# Prometheus Metrics

Push metrics to the Prometheus Pushgateway via curl. No script required.

## Environment

- `AGENT_PUSHGATEWAY_URL` — Pushgateway base URL (set automatically by Conclave when the local Pushgateway is enabled)

## Push a Single Metric

```bash
cat <<EOF | curl -sf --data-binary @- "${AGENT_PUSHGATEWAY_URL}/metrics/job/agent/instance/$(hostname)"
# TYPE tasks_completed_total gauge
tasks_completed_total{category="bugs"} 12
EOF
```

## Push Multiple Metrics

```bash
cat <<EOF | curl -sf --data-binary @- "${AGENT_PUSHGATEWAY_URL}/metrics/job/agent/instance/$(hostname)"
# TYPE tasks_completed_total gauge
tasks_completed_total{category="bugs"} 12
tasks_completed_total{category="features"} 5
# TYPE queue_depth gauge
queue_depth{queue="builds"} 3
queue_depth{queue="deploys"} 0
EOF
```

## Delete Metrics for a Job

```bash
curl -sf -X DELETE "${AGENT_PUSHGATEWAY_URL}/metrics/job/agent/instance/$(hostname)"
```

## List Existing Jobs

```bash
curl -sf "${AGENT_PUSHGATEWAY_URL}/api/v1/metrics" | python3 -m json.tool
```

## Metric Naming Conventions

Use descriptive names with a consistent prefix. Examples:

- `myapp_tasks_total` — Task counts (label: `category`)
- `myapp_queue_depth` — Queue depth (label: `queue`)
- `myapp_requests_total` — Request counts (label: `endpoint`)
- `myapp_errors_total` — Error counts (label: `service`)
- `myapp_duration_seconds` — Duration metrics (label: `operation`)

## Format Rules

- Prometheus text format: `metric_name{label="value"} number`
- Use `# TYPE metric_name gauge` before each metric group
- One metric per line, no trailing whitespace
- Labels are `key="value"` pairs, comma-separated inside `{}`
