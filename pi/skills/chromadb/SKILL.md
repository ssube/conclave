---
name: chromadb
description: >-
  Semantic search for model descriptions and content using ChromaDB vector database. Use when searching for similar models, finding related content, querying vector collections, or looking up models by description or semantic similarity.
---

# ChromaDB Skill

Semantic search and vector storage using ChromaDB for finding similar content across collections.

## Requirements

```bash
pip install chromadb
```

## Usage

### Query for similar items

```bash
python3 {baseDir}/query.py query "gothic fantasy creature" --collection models [--limit 5]
```

### Find similar to existing item

```bash
python3 {baseDir}/query.py similar <id> --collection models [--limit 5]
```

### Add or update content (upsert)

```bash
python3 {baseDir}/query.py add --collection models --id <id> --text "..." [--metadata '{"key": "value"}']
```

This command performs an upsert: if the ID already exists, it updates the content; otherwise, it creates a new entry.

### List collections

```bash
python3 {baseDir}/query.py collections
```

### Create a new collection

```bash
python3 {baseDir}/query.py create-collection <name>
```

### Delete an item

```bash
python3 {baseDir}/query.py delete <id> --collection models
```

## Collections

Pre-defined collections for different use cases:

| Collection | Purpose |
|------------|---------|
| `models` | LoRA model descriptions (name, category, style notes) |
| `memories` | Bot memories and learned context |
| `notes` | User notes and reference material |
| `posts` | Posted content for semantic similarity checking |

## Environment Variables

All variables are optional with sensible defaults:

- `CHROMADB_HOST`: ChromaDB server hostname (default: `localhost`)
- `CHROMADB_PORT`: ChromaDB server port (default: `8000`)
- `CHROMADB_PATH`: Path for persistent storage (optional, uses server if not set)

**Default Mode**: The skill connects to the ChromaDB server at `localhost:8000` by default. To use persistent local storage instead, set `CHROMADB_PATH=/path/to/storage`.

## Metadata

Each item can have metadata for filtering:

```bash
python3 {baseDir}/query.py add \
    --collection models \
    --id creature_v2 \
    --text "A LoRA for generating fantasy creatures with detailed scales and claws" \
    --metadata '{"category": "creatures", "base_model": "flux", "quality": 5}'
```

Query with metadata filter:

```bash
python3 {baseDir}/query.py query "dragon" --collection models --where '{"category": "creatures"}'
```

## Examples

```bash
# Find models similar to a concept
python3 {baseDir}/query.py query "cyberpunk android with neon lights" --collection models

# Find posts similar to a new draft (avoid duplicates)
python3 {baseDir}/query.py query "Check out this new model release!" --collection posts

# Store a memory
python3 {baseDir}/query.py add \
    --collection memories \
    --id "mem_20250207_001" \
    --text "User prefers dark fantasy aesthetics with blue and purple color schemes"

# Find related memories
python3 {baseDir}/query.py query "color preferences" --collection memories
```

## Server vs Persistent Mode

The skill supports two modes:

1. **Server mode** (default): Connects to a ChromaDB server at `localhost:8000`
   - No configuration needed if server is running locally
   - Set `CHROMADB_HOST` and `CHROMADB_PORT` for remote servers
   - Better for multi-agent access and concurrent operations

2. **Persistent mode**: Uses local file storage
   - Set `CHROMADB_PATH=/path/to/storage` to enable
   - Suitable for offline or single-agent setups

## Troubleshooting

### Connection refused
ChromaDB server not running at the configured host:port. Start it or check `CHROMADB_HOST`/`CHROMADB_PORT`.

### Collection not found
The collection may not exist yet. Use `python3 {baseDir}/query.py create-collection <name>` to create it.

### Empty results
- Lower your search threshold — semantic search can be sensitive to phrasing
- Try different query terms or shorter queries
- Verify the collection has data: `python3 {baseDir}/query.py collections`
