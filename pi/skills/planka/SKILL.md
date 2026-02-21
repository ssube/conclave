---
name: planka
description: >-
  Manage tasks and projects in Planka kanban board — create cards, move between
  columns, track progress. Use when creating tasks, updating card status, checking
  project boards, managing the kanban workflow, or organizing work items.
---

# Planka Skill

Manage tasks and projects using the Planka kanban board.

## Actions

| Action | Description |
|--------|-------------|
| `create` | Create a new card in a list |
| `list` | List cards, optionally filtered by list or label |
| `get` | Get details for a specific card (includes comments and tasks) |
| `move` | Move a card to a different list |
| `complete` | Move a card to the done list |
| `update` | Update card title, description, or labels |
| `comment` | Add a comment to a card |
| `delete` | Delete a card |
| `boards` | List available boards |
| `labels` | List available labels |

## Usage

```bash
python3 {baseDir}/planka.py [--board <name>] <command> [options]
```

### Create a new card

```bash
python3 {baseDir}/planka.py create \
  --title "Review image prompts" \
  --description "Check prompt quality and consistency" \
  --list "next up" \
  --labels "priority,content"
```

### List cards

```bash
# List all cards on the default board
python3 {baseDir}/planka.py list

# Filter by column
python3 {baseDir}/planka.py list --list "next up"

# Filter by label
python3 {baseDir}/planka.py list --label "priority"

# Different board
python3 {baseDir}/planka.py --board dev list
```

### Get card details

```bash
python3 {baseDir}/planka.py get <card-id>
```

### Move a card

```bash
# Board is auto-detected from the card — no --board needed
python3 {baseDir}/planka.py move <card-id> --list "next up"
```

### Mark card complete

```bash
python3 {baseDir}/planka.py complete <card-id>
```

### Add a comment

```bash
python3 {baseDir}/planka.py comment <card-id> --text "Progress update: completed initial review"
```

### List boards / labels

```bash
python3 {baseDir}/planka.py boards
python3 {baseDir}/planka.py labels
```

## Environment Variables

Required:
- `PLANKA_API_URL`: Base URL of Planka instance
- `PLANKA_API_TOKEN`: API authentication token

Optional:
- `PLANKA_USERNAME`: Login username (for auto-refresh when token expires)
- `PLANKA_PASSWORD`: Login password (for auto-refresh)
- `PLANKA_BOARD`: Default board name (default: first configured board)

## Board Configuration

Boards are configured as a JSON dict in the `PLANKA_BOARDS` environment variable,
or directly in `planka.py`. Each entry maps a short name to a Planka board ID.

```bash
# Example: set via environment
export PLANKA_BOARDS='{"main": "123456789", "dev": "987654321"}'
```

Or edit the `BOARD_IDS` dict in `planka.py`:

```python
BOARD_IDS = {
    "main": "123456789",
    "dev": "987654321",
}
```

### Typical Board Columns

1. `Backlog` — Future tasks
2. `Next Up` — Ready to work on
3. `Progress` — Currently being worked on
4. `Blocked` — Waiting on external dependency
5. `Done` — Completed

## Notes

- List names are matched **case-insensitively**
- `move` and `complete` auto-detect the board from the card ID
- The script includes automatic retry (3 attempts with backoff) and token refresh
- `--board` flag goes **before** the subcommand: `planka.py --board dev list`
