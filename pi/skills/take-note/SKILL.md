---
name: take-note
description: >-
  Capture notes, learnings, and context into ChromaDB for long-term memory. Use when saving something to remember, recording a discovery or decision, storing context for future sessions, or building the knowledge base.
---

# Take Note Skill

Quickly capture notes, learnings, observations, and context. Builds a searchable knowledge base over time.

## Requirements

```bash
pip install chromadb
```

## Usage

### Capture a quick note

```bash
python3 {baseDir}/note.py "Learned that Flux models respond better to natural language prompts"
```

Auto-generates ID with timestamp: `note-2026-02-10-213045-abc123`

### Add note with category/tags

```bash
python3 {baseDir}/note.py "User prefers dark fantasy aesthetics with purple and green color schemes" \
  --category user-preferences \
  --tags "color,style,fantasy"
```

### Add note with custom ID

```bash
python3 {baseDir}/note.py "Important discovery about training parameters" \
  --id important-training-discovery
```

### Search notes

```bash
python3 {baseDir}/note.py --search "training parameters" --limit 5
```

### List recent notes

```bash
python3 {baseDir}/note.py --list [--limit 10]
```

## What Gets Stored

Each note includes:

- **Content**: Your note text (embedded for semantic search)
- **ID**: Auto-generated `note-YYYY-MM-DD-HHMMSS-hash` or custom
- **Timestamp**: ISO 8601 timestamp
- **Category**: Optional category for filtering (default: "general")
- **Tags**: Comma-separated tags for filtering
- **Source**: "agent" to distinguish from imported notes

## Categories

Suggested categories (use what makes sense):

- `learning` — Technical discoveries, how-tos
- `user-preferences` — User likes/dislikes, style preferences
- `context` — Background info, project context
- `decision` — Decisions made and why
- `idea` — Ideas for future exploration
- `observation` — Patterns noticed over time
- `general` — Default for uncategorized notes

## Environment Variables

- `CHROMADB_HOST`: ChromaDB server host (default: `localhost`)
- `CHROMADB_PORT`: ChromaDB server port (default: `8000`)

## Examples

```bash
# Quick learning capture
python3 {baseDir}/note.py "The scratching LoRA works best at weight 0.8-1.0 for sketch effects"

# User preference with tags
python3 {baseDir}/note.py "User avoids overly bright colors, prefers muted/dark palettes" \
  --category user-preferences \
  --tags "color,palette,style"

# Technical decision with category
python3 {baseDir}/note.py "Switched to cosine scheduler for all future training - smoother results" \
  --category decision \
  --tags "training,scheduler"

# Search for relevant context
python3 {baseDir}/note.py --search "user color preferences"

# List recent notes
python3 {baseDir}/note.py --list --limit 5
```

## Integration with Other Skills

- Notes are stored in ChromaDB `notes` collection alongside any imported data
- Use `chromadb` skill for advanced semantic search
- Notes can inform image generation, content creation, and decision-making over time
