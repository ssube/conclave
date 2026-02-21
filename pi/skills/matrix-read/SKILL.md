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
python3 {baseDir}/matrix_read.py --room general
```

### Filter to messages from a specific user

```bash
python3 {baseDir}/matrix_read.py --room content-drafts --from ssube
```

### Check messages from the last N minutes

```bash
python3 {baseDir}/matrix_read.py --room general --since 60
```

### Check for reactions on a specific message

```bash
python3 {baseDir}/matrix_read.py --room content-drafts --reactions-for '$eventId'
```

### Check all rooms for unread messages from humans

```bash
python3 {baseDir}/matrix_read.py --all --humans-only
```

### Output as JSON for programmatic use

```bash
python3 {baseDir}/matrix_read.py --room general --json
```

## Room Aliases

Use short names instead of full room IDs with `matrix_read.py`.

When using the **`send` tool** (built-in Matrix messaging), you must use the **full room ID** — aliases and short names won't work.

| Alias | Full Room ID | Purpose |
|-------|-------------|---------|
| `general` | `!EOujKPtUOJPbbyBnHr:matrix.home.holdmyran.ch` | Main coordination channel with Sean |
| `drafts` | `!DTwKgcNMAqKTqCCbyY:matrix.home.holdmyran.ch` | HITL draft review and approval |
| `published` | `!HRUMcHLpGmtWRPMjpz:matrix.home.holdmyran.ch` | Published content log |
| `data` | `!AXdouVagECaWEfWlqF:matrix.home.holdmyran.ch` | Nox data queries (#thalis-ask-data) |
| `image` | `!oGVcqxQeeZWtYNqWIk:matrix.home.holdmyran.ch` | Stella image generation (#thalis-conjure-image) |
| `calendar` | `!xJqiFXNHCVTkaeoIfl:matrix.home.holdmyran.ch` | Content scheduling |

### Quick Copy for send tool

```
General:   !EOujKPtUOJPbbyBnHr:matrix.home.holdmyran.ch
Drafts:    !DTwKgcNMAqKTqCCbyY:matrix.home.holdmyran.ch
Published: !HRUMcHLpGmtWRPMjpz:matrix.home.holdmyran.ch
Data:      !AXdouVagECaWEfWlqF:matrix.home.holdmyran.ch
Image:     !oGVcqxQeeZWtYNqWIk:matrix.home.holdmyran.ch
Calendar:  !xJqiFXNHCVTkaeoIfl:matrix.home.holdmyran.ch
```

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

- `MATRIX_HOMESERVER_URL`: Matrix server URL
- `MATRIX_ACCESS_TOKEN`: Bot access token

## Integration with Overnight Loop

The overnight prompt can use this to check for instructions:

```bash
# Check if Sean has said anything in the last hour
python3 matrix_read.py --all --humans-only --since 60

# Check for reactions on draft posts (approvals/rejections)
python3 matrix_read.py --room drafts --since 120
```

## Reaction Meanings (HITL Protocol)

When checking content-drafts for approval reactions:

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
