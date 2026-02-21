---
name: matrix-read
description: >-
  Read messages, reactions, and replies from Matrix rooms. Use when reading Matrix channel history, checking for reactions on messages, reviewing room conversations, or monitoring Matrix channels for responses.
---

# Matrix Read Skill

Fetch recent messages from Matrix rooms. Enables async communication — check for responses, reactions, approvals, and instructions without being in a live conversation.

## Usage

### Check recent messages in a room

```bash
python3 {baseDir}/matrix_read.py --room home
```

### Filter to messages from a specific user

```bash
python3 {baseDir}/matrix_read.py --room home --from ssube
```

### Check messages from the last N minutes

```bash
python3 {baseDir}/matrix_read.py --room home --since 60
```

### Check for reactions on a specific message

```bash
python3 {baseDir}/matrix_read.py --room home --reactions-for '$eventId'
```

### Check all rooms for unread messages from humans

```bash
python3 {baseDir}/matrix_read.py --all --humans-only
```

### Output as JSON for programmatic use

```bash
python3 {baseDir}/matrix_read.py --room home --json
```

## Room Aliases

Use short names instead of full room IDs. Room aliases are resolved via the Matrix directory API.

| Alias | Resolved As |
|-------|-------------|
| `home` | `#home:<MATRIX_SERVER_NAME>` |

Any room alias (`#room:server`) or internal room ID (`!id:server`) can also be used directly.

## Parameters

| Flag | Description | Default |
|------|-------------|---------|
| `--room ALIAS` | Room to check (alias or full ID) | required (unless `--all`) |
| `--all` | Check all joined rooms | false |
| `--since MINUTES` | Only messages from last N minutes | 120 |
| `--limit N` | Max messages to fetch | 50 |
| `--from USER` | Filter to messages from this sender | all |
| `--humans-only` | Exclude bot/agent messages | false |
| `--reactions-for ID` | Show reactions on a specific event | none |
| `--json` | Output as JSON | false |
| `--compact` | One-line-per-message format | false |

## Environment Variables

- `MATRIX_HOMESERVER_URL`: Matrix server URL (falls back to `AGENT_MATRIX_URL`, default `http://127.0.0.1:8008`)
- `MATRIX_ACCESS_TOKEN`: Bot access token
- `MATRIX_SERVER_NAME`: Matrix server name for alias resolution (falls back to `AGENT_MATRIX_SERVER_NAME`)

## Reaction Meanings (HITL Protocol)

When checking rooms for approval reactions:

| Reaction | Meaning |
|----------|---------|
| ✅ or 👍 | Approved — post it |
| ❌ or 👎 | Rejected — do not post |
| ✏️ | Needs edits — check for reply with details |
| 🔄 | Regenerate — try again with different approach |
| ⏰ | Schedule for later |

## Troubleshooting

### 401 Unauthorized
`MATRIX_ACCESS_TOKEN` is invalid or expired. Generate a new token.

### Room not found
- Check the room alias or ID is correct
- The bot account may not be a member of the room — invite it first

### Empty response
The room may have no messages in the requested time range. Try increasing `--limit`.
