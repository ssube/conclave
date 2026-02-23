---
name: matrix
description: >-
  Send messages, read channel history, upload files, manage reactions, and list
  rooms on Matrix. Use for Matrix communication — posting messages, sharing
  files, reading conversations, checking reactions, or monitoring rooms.
---

# Matrix Skill

Unified Matrix communication tool with structured error handling, rate-limit awareness, and room alias resolution.

## Actions

| Action | Description |
|--------|-------------|
| `send` | Send a text message to a room |
| `read` | Read recent messages from a room (chronological, with filters) |
| `rooms` | List all joined rooms |
| `attach` | Upload and send a file (auto-detects image/video/audio) |
| `react` | Send a reaction to an event |
| `reactions` | Query reactions on a specific event (with fallback scan) |
| `batch` | Send multiple files with pacing to avoid rate limits |

## Usage

```bash
python3 {baseDir}/matrix.py <command> [options]
```

### Send a message

```bash
# Send to default room
python3 {baseDir}/matrix.py send "Hello from the agent"

# Send to a specific room by alias
python3 {baseDir}/matrix.py send "Status update" --room home

# Send to a room by full alias
python3 {baseDir}/matrix.py send "Hello" --room '#general:example.com'

# Send to a room by ID
python3 {baseDir}/matrix.py send "Hello" --room '!abc123:example.com'
```

### Read messages

```bash
# Read last 2 hours from default room
python3 {baseDir}/matrix.py read --room home

# Read last 30 minutes, compact format
python3 {baseDir}/matrix.py read --room home --since 30 --compact

# Filter to a specific user, humans only
python3 {baseDir}/matrix.py read --room home --from ssube --humans-only

# Check all joined rooms
python3 {baseDir}/matrix.py read --all --humans-only

# Output as JSON
python3 {baseDir}/matrix.py read --room home --json
```

### List rooms

```bash
python3 {baseDir}/matrix.py rooms
```

### Send a file

```bash
# Upload and send an image (auto-detected)
python3 {baseDir}/matrix.py attach --file /path/to/image.png --room home

# Upload with a caption (sent as separate text message before the file)
python3 {baseDir}/matrix.py attach --file /path/to/video.mp4 --caption "Check this out" --room home
```

### React to a message

```bash
python3 {baseDir}/matrix.py react '$eventId' --emoji "👍" --room home
```

### Check reactions

```bash
# Human-readable output
python3 {baseDir}/matrix.py reactions '$eventId' --room home

# JSON output
python3 {baseDir}/matrix.py reactions '$eventId' --room home --json
```

### Batch send files

```bash
# Send multiple files with 3-second pacing
python3 {baseDir}/matrix.py batch --room home --delay 3 /path/to/img1.png /path/to/img2.png /path/to/video.mp4
```

## Environment Variables

Required:
- `MATRIX_HOMESERVER_URL`: Matrix homeserver base URL (e.g. `https://matrix.example.com`)
- `MATRIX_ACCESS_TOKEN`: Bearer token for authentication (or use auto-login below)

Auto-login (alternative to access token):
- `MATRIX_USER`: Username for password login
- `MATRIX_PASSWORD`: Password for login

Optional:
- `MATRIX_SERVER_NAME`: Server name for alias construction (needed for bare room names)
- `MATRIX_DEFAULT_ROOM`: Default room when `--room` is not specified
- `MATRIX_ROOM_ALIASES`: JSON dict of shortname to alias local part (e.g. `{"home": "home", "dev": "dev"}`)
- `MATRIX_BOT_USERS`: JSON array of bot user IDs for `--humans-only` filtering
- `MATRIX_MAX_RETRIES`: Max retry attempts for rate-limited requests (default: 5)

## Output Format

### Compact mode (`read --compact`)

```
2026-02-22 14:30 | text user | Hello everyone
2026-02-22 14:31 | image user | screenshot.png
```

### Verbose mode (default `read`)

```
  text 2026-02-22 14:30 -- user
    $eventId
    Hello everyone

  image 2026-02-22 14:31 -- user
    $eventId
    screenshot.png
```

## Reaction Meanings (HITL Protocol)

When checking rooms for approval reactions:

| Reaction | Meaning |
|----------|---------|
| thumbsup or checkmark | Approved -- post it |
| thumbsdown or X | Rejected -- do not post |
| pencil | Needs edits -- check for reply with details |
| arrows | Regenerate -- try again with different approach |
| clock | Schedule for later |

## Notes

- **Rate limiting**: Automatically handles Matrix 429 responses by reading `retry_after_ms` and sleeping before retrying.
- **Room resolution**: Supports room IDs (`!id:server`), full aliases (`#room:server`), configured shortnames (via `MATRIX_ROOM_ALIASES`), and bare names (via `MATRIX_SERVER_NAME`).
- **Auto-login**: If `MATRIX_ACCESS_TOKEN` is not set, falls back to password login using `MATRIX_USER`/`MATRIX_PASSWORD`.
- **File uploads**: The `attach` command uploads to the media repo first, then sends the event. MIME type and Matrix msgtype are auto-detected from file extension.
- **Batch mode**: Sends files sequentially with configurable pacing delay to avoid rate limits.
- **Retry logic**: 5xx errors retry with exponential backoff. Rate limits retry after the server-specified delay.
- **Message ordering**: Matrix returns newest-first; `read` reverses to chronological order.
- **Reactions fallback**: The `reactions` command tries the relations API first, then falls back to scanning recent messages.
