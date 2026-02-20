#!/bin/bash
set -e

MODEL="${DEFAULT_OLLAMA_MODEL:-qwen3-coder:30b-a3b-q8_0}"

echo "Waiting for Ollama API..."
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        break
    fi
    sleep 2
done

if ! curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo "ERROR: Ollama API not available after 120s"
    exit 1
fi

if ollama list 2>/dev/null | grep -q "$MODEL"; then
    echo "$MODEL already cached."
else
    echo "Pulling $MODEL..."
    ollama pull "$MODEL"
fi
