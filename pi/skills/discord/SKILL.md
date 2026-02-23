---
name: discord
description: >-
  Send messages, read channel history, upload files, create polls, add reactions,
  and list guilds on Discord. Use for Discord communication — posting messages,
  sharing files, running polls, checking conversations, monitoring channels, or
  listing servers.
---

# Discord Skill

Unified Discord communication tool with structured error handling, rate-limit awareness, and channel name resolution.

## Actions

| Action | Description |
|--------|-------------|
| `send` | Send a text message to a channel |
| `read` | Read recent messages from a channel (chronological, with filters) |
| `channels` | List all channels in a guild (grouped by category) |
| `guilds` | List guilds the bot belongs to |
| `attach` | Upload a file to a channel with an optional caption |
| `poll` | Create a poll with multiple choice answers |
| `react` | Add an emoji reaction to a message |

## Usage

```bash
python3 {baseDir}/discord.py <command> [options]
```

### Send a message

```bash
# Send to default channel
python3 {baseDir}/discord.py send "Hello from the agent"

# Send to a specific channel by ID
python3 {baseDir}/discord.py send "Status update: deploy complete" --channel 1234567890

# Send to a channel by name (requires DISCORD_GUILD_ID)
python3 {baseDir}/discord.py send "Build finished" --channel general
```

### Read messages

```bash
# Read last 2 hours from default channel
python3 {baseDir}/discord.py read

# Read last 30 minutes, compact format
python3 {baseDir}/discord.py read --channel general --since 30 --compact

# Filter to a specific user, humans only
python3 {baseDir}/discord.py read --channel 1234567890 --from username --humans-only

# Read with higher limit
python3 {baseDir}/discord.py read --channel general --limit 100 --since 60
```

### List channels

```bash
# List channels in the default guild
python3 {baseDir}/discord.py channels

# List channels in a specific guild
python3 {baseDir}/discord.py channels --guild 9876543210
```

### List guilds

```bash
python3 {baseDir}/discord.py guilds
```

### Send a file attachment

```bash
# Upload a file to the default channel
python3 {baseDir}/discord.py attach --file /tmp/report.pdf

# Upload with a caption to a specific channel
python3 {baseDir}/discord.py attach --file /tmp/photo.jpg --caption "Check this out" --channel media

# Upload by channel name
python3 {baseDir}/discord.py attach --file ./screenshot.png --caption "Bug screenshot" --channel bugs
```

### Create a poll

```bash
# Simple poll in the default channel (24h duration)
python3 {baseDir}/discord.py poll --question "What for dinner?" --answers "Pizza, Tacos, Sushi"

# Multi-select poll with custom duration
python3 {baseDir}/discord.py poll --question "Pick features to build" --answers "Dark mode, Notifications, Export" --multi --duration 48 --channel feedback
```

### Add a reaction

```bash
# React with a unicode emoji
python3 {baseDir}/discord.py react 1234567890123456789 --emoji "👍" --channel general

# React with a different emoji
python3 {baseDir}/discord.py react 1234567890123456789 --emoji "🔥" --channel 9876543210
```

## Environment Variables

Required:
- `DISCORD_BOT_TOKEN`: Bot authentication token

Optional:
- `DISCORD_GUILD_ID`: Default guild ID for channel name resolution and `channels` command
- `DISCORD_DEFAULT_CHANNEL`: Default channel ID when `--channel` is not specified

## Output Format

### Compact mode (`read --compact`)

```
2026-02-22 14:30 | user | Hello everyone [files] [embeds] [fire x3, thumbsup x2]
```

### Verbose mode (default `read`)

```
  2026-02-22 14:30 -- user
    ID: 1234567890123456789
    Hello everyone
    attachment.png (23456 bytes)
    Embed Title
    [fire x3, thumbsup x2]
```

Reactions are displayed as `[emoji x count, ...]` when present on a message.

## Notes

- **Rate limiting**: Automatically handles Discord 429 responses by reading `retry_after` and sleeping before retrying.
- **Channel name resolution**: Non-numeric `--channel` values are resolved via the guild channels API (case-insensitive). Requires `DISCORD_GUILD_ID`.
- **Bot token prefix**: Uses `Authorization: Bot {token}` as required by Discord.
- **File uploads**: The `attach` command builds multipart/form-data manually using stdlib only (no external dependencies). MIME type is auto-detected.
- **Polls**: Uses the Discord poll API. Duration is in hours. Answers are comma-separated.
- **Reactions**: URL-encodes the emoji for the reactions endpoint. Works with standard unicode emoji.
- **Snowflake filtering**: `--since` converts minutes to a Discord snowflake for efficient server-side filtering.
- **Retry logic**: 5xx errors retry up to 3 times with exponential backoff. Rate limits retry after the server-specified delay.
- **Message ordering**: Discord returns newest-first; `read` reverses to chronological order.
