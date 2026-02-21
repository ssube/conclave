---
name: web-search
description: >-
  Search the web for current information — documentation, troubleshooting, news, platform changes. Use when you need up-to-date information beyond training knowledge, current API docs, error message solutions, platform policy changes, or any factual query where recency matters.
---

# Web Search Skill

Search the web using Claude Code's built-in WebSearch and WebFetch tools. Returns concise summaries with source URLs.

## Usage

### Quick search (concise summary)

```bash
bash {baseDir}/search.sh "ComfyUI ControlNet union pro setup 2026"
```

### Detailed search (multi-source analysis)

```bash
bash {baseDir}/search.sh --detailed "SDXL vs Flux LoRA training comparison"
```

### Fetch a specific URL

```bash
bash {baseDir}/search.sh --fetch "https://docs.example.com/api" "What endpoints are available?"
```

## When to Search vs When Not To

**Search when:**
- Dates/versions matter (API changes, platform updates)
- Error messages need current solutions
- Platform policies may have shifted
- You need documentation for a specific library version
- Current events or news

**Don't search when:**
- General programming patterns (you know these)
- Information already in MEMORY.md or ChromaDB
- Brand/creative decisions (those are internal)
- Well-established tools with stable APIs

## Cost

- Quick search: ~$0.10-0.30 (Sonnet)
- Detailed search: ~$0.30-1.00 (Sonnet)
- URL fetch: ~$0.05-0.15 (Sonnet)

Uses Claude Sonnet by default for cost efficiency.

## Environment

Requires `claude` CLI to be installed and authenticated.
