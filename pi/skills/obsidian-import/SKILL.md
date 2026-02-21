---
name: obsidian-import
description: >-
  Import an Obsidian vault into ChromaDB for semantic search.
  Parses markdown files, extracts frontmatter, headings, tags,
  and content sections. Chunks intelligently by heading hierarchy.
  Use when indexing a knowledge base, importing notes for semantic
  recall, or syncing an Obsidian vault to a vector database.
---

# Obsidian Import Skill

Import an Obsidian vault into ChromaDB for semantic search. Parses markdown
structure (frontmatter, headings, tags, links, tables) and chunks content
by heading hierarchy so each vector represents a coherent topic.

## Requirements

```bash
pip install chromadb pyyaml
```

## Quick Start

```bash
# Scan a vault (dry run — no writes)
python3 {baseDir}/obsidian_import.py scan --vault ~/my-vault

# Import everything into ChromaDB
python3 {baseDir}/obsidian_import.py import --vault ~/my-vault

# Import only files in a specific folder
python3 {baseDir}/obsidian_import.py import --vault ~/my-vault --folder "Projects/Active"

# Import only files with a specific tag
python3 {baseDir}/obsidian_import.py import --vault ~/my-vault --tag "important"

# Incremental import (skip unchanged files)
python3 {baseDir}/obsidian_import.py import --vault ~/my-vault --incremental
```

## Commands

### `scan` — Preview what would be imported

```bash
python3 {baseDir}/obsidian_import.py scan --vault ./my-vault [--folder PATH] [--tag TAG] [--glob PATTERN]
```

Shows file count, section count, total chunks, and per-file breakdown.
No writes — safe to run anytime.

### `import` — Import vault content into ChromaDB

```bash
python3 {baseDir}/obsidian_import.py import --vault ./my-vault \
  [--collection vault] \
  [--folder PATH] \
  [--tag TAG] \
  [--glob PATTERN] \
  [--incremental] \
  [--chunk-size 1500] \
  [--chunk-overlap 150]
```

Parses every matching `.md` file, splits by heading sections, chunks long
sections, and upserts into ChromaDB with rich metadata.

### `clear` — Remove all items from a collection

```bash
python3 {baseDir}/obsidian_import.py clear --collection vault
```

Deletes the collection entirely. Use before a full re-import if needed.

### `stats` — Show collection statistics

```bash
python3 {baseDir}/obsidian_import.py stats [--collection vault]
```

## How It Works

### 1. File Discovery

Recursively finds all `.md` files in the vault, excluding:
- `.obsidian/` (config directory)
- `.trash/` (Obsidian trash)
- Files matching `--glob` exclusion patterns
- Dot-prefixed directories

Optionally filters by `--folder` (subfolder path) or `--tag` (frontmatter or inline tag).

### 2. Parsing

Each file is parsed into structured sections:

- **Frontmatter**: YAML between `---` fences → stored as metadata on every chunk from that file
- **Inline tags**: `#tag` patterns in body text → collected into metadata
- **Obsidian links**: `[[Page Name]]` and `[[Page Name|Alias]]` → stored as metadata
- **Headings**: H1–H6 define section boundaries for chunking
- **Tables**: Preserved as-is within their parent section
- **Content**: Everything between headings becomes a chunk candidate

### 3. Chunking

Content is split by heading hierarchy:

```
# Top Level          → Section: "Top Level"
Some paragraph.

## Sub Section       → Section: "Top Level > Sub Section"
More text here.

### Deep Section     → Section: "Top Level > Sub Section > Deep Section"
Details.
```

Each heading section becomes one chunk. If a section exceeds `--chunk-size`
(default: 1500 chars), it's split at paragraph boundaries with overlap.

Short sections (under 50 chars with no meaningful content) are merged into
the next section rather than creating tiny standalone chunks.

### 4. Metadata

Every chunk is stored with metadata for filtering and context:

| Field | Description |
|-------|-------------|
| `source_file` | Relative path within the vault |
| `heading_path` | Full heading hierarchy (e.g., `"Projects > API Design > Auth"`) |
| `heading_level` | Deepest heading level (1–6, or 0 for content before first heading) |
| `tags` | Comma-separated tags from frontmatter + inline |
| `links` | Comma-separated Obsidian `[[links]]` found in this section |
| `chunk_index` | Index within the section (0 if not chunked) |
| `total_chunks` | Total chunks for this section |
| `char_count` | Character count of this chunk |
| `has_table` | `true` if the chunk contains a markdown table |
| `has_code` | `true` if the chunk contains a fenced code block |
| `imported_at` | ISO timestamp of import |

Frontmatter fields are also included as metadata. String, number, and boolean
values are stored directly. Lists are joined with commas. Nested objects are
skipped (ChromaDB only supports flat metadata).

### 5. ID Generation

Chunk IDs are deterministic and stable across re-imports:

```
{slugified-filepath}::{slugified-heading-path}[::chunk-N]
```

Examples:
- `projects/api-design::authentication::oauth-flow`
- `daily-notes/2025-01-15::meetings::standup::chunk-0`
- `readme::` (file with no headings)

This means re-importing the same vault updates existing chunks in place.

## Filtering

### By folder

```bash
# Only import from Projects/Active and its subfolders
python3 {baseDir}/obsidian_import.py import --vault ~/vault --folder "Projects/Active"
```

### By tag

```bash
# Only import files tagged #reference (frontmatter or inline)
python3 {baseDir}/obsidian_import.py import --vault ~/vault --tag reference
```

### By glob pattern

```bash
# Only import files matching a pattern
python3 {baseDir}/obsidian_import.py import --vault ~/vault --glob "**/*meeting*.md"
```

### Combining filters

Filters are AND-combined. A file must match ALL specified filters.

## Incremental Import

```bash
python3 {baseDir}/obsidian_import.py import --vault ~/vault --incremental
```

Tracks file modification times in a `.obsidian-import-state.json` file
alongside the vault. On subsequent runs, only re-imports files whose
`mtime` has changed. Use `--force` to override and re-import everything.

## Environment Variables

- `CHROMADB_HOST`: ChromaDB server hostname (default: `localhost`)
- `CHROMADB_PORT`: ChromaDB server port (default: `8000`)
- `CHROMADB_PATH`: Path for persistent local storage (optional; uses server mode by default)

## Examples

```bash
# Full import of a project knowledge base
python3 {baseDir}/obsidian_import.py import --vault ~/work-vault --collection work

# Import just meeting notes
python3 {baseDir}/obsidian_import.py import --vault ~/vault --folder "Meetings" --collection meetings

# Preview what a tag filter would capture
python3 {baseDir}/obsidian_import.py scan --vault ~/vault --tag architecture

# Re-import after edits (incremental)
python3 {baseDir}/obsidian_import.py import --vault ~/vault --incremental

# Full re-import (clear and reimport)
python3 {baseDir}/obsidian_import.py clear --collection vault
python3 {baseDir}/obsidian_import.py import --vault ~/vault

# Check what's in the collection
python3 {baseDir}/obsidian_import.py stats --collection vault
```

## Querying Imported Content

Once imported, use the **chromadb** skill to search:

```bash
# Semantic search across your vault
python3 chromadb/query.py query "authentication design patterns" --collection vault

# Filter by source file
python3 chromadb/query.py query "error handling" --collection vault --where '{"source_file": "projects/api-design.md"}'

# Filter by tag
python3 chromadb/query.py query "deployment" --collection vault --where '{"tags": {"$contains": "devops"}}'
```

## Troubleshooting

### "No .md files found"
Check that `--vault` points to the vault root (the directory containing `.obsidian/`).

### ChromaDB connection refused
Start the ChromaDB server or set `CHROMADB_PATH` for local persistent mode.

### Large vaults are slow
Use `--folder` or `--tag` filters to import selectively. Use `--incremental`
for subsequent runs. Consider increasing `--chunk-size` to reduce chunk count.

### Duplicate content after re-import
IDs are deterministic — re-importing the same file overwrites existing chunks.
If you renamed headings, old chunks under the previous heading ID will remain.
Use `clear` + full `import` to reset.
