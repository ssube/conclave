#!/bin/bash

# Prometheus Metrics Skill
# Push metrics to Prometheus Pushgateway

set -e

# Configuration from environment
PUSHGATEWAY_URL="${AGENT_PUSHGATEWAY_URL:-}"
JOB_NAME="${PROMETHEUS_JOB_NAME:-agent}"
INSTANCE="${PROMETHEUS_INSTANCE:-$(hostname)}"

usage() {
    echo "Usage: prometheus.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  push      Push a single metric"
    echo "  batch     Push multiple metrics from JSON"
    echo "  delete    Delete a metric"
    echo "  jobs      List job groups on pushgateway"
    echo ""
    echo "Options:"
    echo "  --metric <name>     Metric name (e.g., myapp_tasks_total)"
    echo "  --value <number>    Metric value"
    echo "  --labels <json>     Labels as JSON object"
    echo "  --file <path>       JSON file with metrics array"
    echo "  --stdin             Read metrics from stdin"
    echo ""
    echo "Environment:"
    echo "  AGENT_PUSHGATEWAY_URL       Pushgateway URL (required)"
    echo "  PROMETHEUS_JOB_NAME         Job name (default: agent)"
    echo "  PROMETHEUS_INSTANCE         Instance label (default: hostname)"
}

check_config() {
    if [[ -z "$PUSHGATEWAY_URL" ]]; then
        echo "Error: AGENT_PUSHGATEWAY_URL environment variable not set" >&2
        exit 1
    fi
}

# Build the push URL with labels
build_url() {
    local labels_json="$1"
    local url="${PUSHGATEWAY_URL}/metrics/job/${JOB_NAME}/instance/${INSTANCE}"

    if [[ -n "$labels_json" ]] && [[ "$labels_json" != "{}" ]]; then
        # Parse JSON labels and add to URL path
        local label_path=$(printf '%s' "$labels_json" | jq -r 'to_entries | map("/" + .key + "/" + (.value | tostring | @uri)) | join("")')
        url="${url}${label_path}"
    fi

    echo "$url"
}

# Format a metric in Prometheus text format
format_metric() {
    local name="$1"
    local value="$2"
    local labels_json="$3"
    if [[ -z "$labels_json" ]]; then
        labels_json='{}'
    fi

    # Build label string for metric line
    local labels_str=""
    if [[ -n "$labels_json" ]] && [[ "$labels_json" != "{}" ]]; then
        labels_str=$(printf '%s' "$labels_json" | jq -r 'to_entries | map(.key + "=\"" + (.value | tostring) + "\"") | join(",")')
        labels_str="{${labels_str}}"
    fi

    echo "${name}${labels_str} ${value}"
}

# Push a single metric
cmd_push() {
    check_config

    local metric=""
    local value=""
    local labels="{}"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --metric) metric="$2"; shift 2 ;;
            --value) value="$2"; shift 2 ;;
            --labels) labels="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$metric" ]] || [[ -z "$value" ]]; then
        echo "Error: --metric and --value are required" >&2
        exit 1
    fi

    local url=$(build_url "$labels")
    # Pushgateway expects labels in the URL path, not in the metric line
    local data="${metric} ${value}"

    local response=$(printf '%s\n' "$data" | curl -s -w "\n%{http_code}" -X POST -H "Content-Type: text/plain" --data-binary @- "$url")
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | head -n -1)

    if [[ "$http_code" == "200" ]] || [[ "$http_code" == "202" ]]; then
        echo "Metric pushed: $metric = $value"
        if [[ "$labels" != "{}" ]]; then
            echo "  Labels: $labels"
        fi
    else
        echo "Error pushing metric (HTTP $http_code):" >&2
        echo "$body" >&2
        exit 1
    fi
}

# Push multiple metrics from JSON
cmd_batch() {
    check_config

    local file=""
    local from_stdin=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            --file) file="$2"; shift 2 ;;
            --stdin) from_stdin=true; shift ;;
            *) shift ;;
        esac
    done

    local json_data
    if [[ "$from_stdin" == "true" ]]; then
        json_data=$(cat)
    elif [[ -n "$file" ]]; then
        if [[ ! -f "$file" ]]; then
            echo "Error: File not found: $file" >&2
            exit 1
        fi
        json_data=$(cat "$file")
    else
        echo "Error: --file or --stdin required" >&2
        exit 1
    fi

    # Group metrics by labels for efficient pushing
    local metrics_text=""
    local count=0

    while IFS= read -r line; do
        local metric=$(printf '%s' "$line" | jq -r '.metric')
        local value=$(printf '%s' "$line" | jq -r '.value')
        local labels=$(printf '%s' "$line" | jq -c '.labels // {}')

        local formatted=$(format_metric "$metric" "$value" "$labels")
        metrics_text="${metrics_text}${formatted}\n"
        count=$((count + 1))
    done < <(printf '%s' "$json_data" | jq -c '.[]')

    # Push all metrics at once
    local url="${PUSHGATEWAY_URL}/metrics/job/${JOB_NAME}/instance/${INSTANCE}"
    local response=$(printf '%b' "$metrics_text" | curl -s -w "\n%{http_code}" -X POST -H "Content-Type: text/plain" --data-binary @- "$url")
    local http_code=$(echo "$response" | tail -n1)

    if [[ "$http_code" == "200" ]] || [[ "$http_code" == "202" ]]; then
        echo "Batch pushed: $count metrics"
    else
        echo "Error pushing batch (HTTP $http_code)" >&2
        exit 1
    fi
}

# Delete a metric
cmd_delete() {
    check_config

    local metric=""
    local labels="{}"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --metric) metric="$2"; shift 2 ;;
            --labels) labels="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    local url=$(build_url "$labels")

    local response=$(curl -s -w "\n%{http_code}" -X DELETE "$url")
    local http_code=$(echo "$response" | tail -n1)

    if [[ "$http_code" == "200" ]] || [[ "$http_code" == "202" ]]; then
        echo "Metric group deleted"
    else
        echo "Error deleting metric (HTTP $http_code)" >&2
        exit 1
    fi
}

# List job groups
cmd_jobs() {
    check_config

    local response=$(curl -s "${PUSHGATEWAY_URL}/api/v1/metrics")

    echo "=== Pushgateway Job Groups ==="
    echo ""

    echo "$response" | jq -r '
        .data
        | group_by(.labels.job)
        | map({job: .[0].labels.job, count: length})
        | .[]
        | "  \(.job): \(.count) metric(s)"
    ' 2>/dev/null || echo "  No metrics found or unable to parse response"
}

# Main command handling
case "$1" in
    push)
        shift
        cmd_push "$@"
        ;;
    batch)
        shift
        cmd_batch "$@"
        ;;
    delete)
        shift
        cmd_delete "$@"
        ;;
    jobs)
        cmd_jobs
        ;;
    *)
        usage
        ;;
esac
