#!/usr/bin/env bash
set -euo pipefail

# Web Search — Quick web search via Claude Code's WebSearch/WebFetch tools
#
# Usage:
#   search.sh "query"                          # Quick search (concise summary)
#   search.sh --detailed "query"               # Detailed multi-source analysis  
#   search.sh --fetch "url" "question"         # Fetch specific URL and analyze
#   search.sh --budget 1.00 "query"            # Override budget cap

DETAILED=false
FETCH_MODE=false
FETCH_URL=""
BUDGET="0.50"
MODEL="sonnet"
QUERY_PARTS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --detailed|-d)
            DETAILED=true
            BUDGET="1.00"
            shift
            ;;
        --fetch|-f)
            FETCH_MODE=true
            FETCH_URL="$2"
            shift 2
            ;;
        --budget|-b)
            BUDGET="$2"
            shift 2
            ;;
        --model|-m)
            MODEL="$2"
            shift 2
            ;;
        *)
            QUERY_PARTS+=("$1")
            shift
            ;;
    esac
done

QUERY="${QUERY_PARTS[*]}"

if [[ -z "$QUERY" && "$FETCH_MODE" == "false" ]]; then
    echo "Usage: search.sh [--detailed] [--fetch URL] [--budget N] \"query\"" >&2
    exit 1
fi

# Build the system prompt
if [[ "$DETAILED" == "true" ]]; then
    SYSTEM="You are a thorough research assistant. Search the web using the WebSearch tool, analyze multiple sources, and provide a detailed report with citations and source URLs."
elif [[ "$FETCH_MODE" == "true" ]]; then
    SYSTEM="You are a web content analyst. Fetch the given URL using the WebFetch tool and answer the user's question based on the content. Include relevant quotes and details."
else
    SYSTEM="You are a concise research assistant. Search the web using the WebSearch tool and provide a focused summary in 3-8 sentences with source URLs at the end."
fi

# Build the prompt
if [[ "$FETCH_MODE" == "true" ]]; then
    PROMPT="Fetch this URL and analyze it: ${FETCH_URL}

Question: ${QUERY}"
else
    PROMPT="$QUERY"
fi

# Run Claude with web tools
# Note: requires WebSearch/WebFetch in ~/.claude/settings.json permissions.allow
exec claude -p \
    --model "$MODEL" \
    --tools "WebSearch,WebFetch" \
    --system-prompt "$SYSTEM" \
    --max-budget-usd "$BUDGET" \
    "$PROMPT"
