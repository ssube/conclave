---
name: sqlite
description: >-
  Execute SQL queries against a SQLite database with formatted output.
  Use when querying data, inspecting schemas, running ad-hoc SQL, or
  performing pre-defined write operations.
---

# SQLite Query Skill

Execute SQL queries against a SQLite database with formatted output.

## Usage

### Execute a query

```bash
bash {baseDir}/query.sh query "SELECT * FROM items LIMIT 5" [--format table|json|csv]
```

Output formats:
- `table` (default): Formatted table with headers
- `json`: JSON array of objects
- `csv`: CSV with header row

### List all tables

```bash
bash {baseDir}/query.sh tables
```

### Describe table schema

```bash
bash {baseDir}/query.sh schema <table>
```

## Environment Variables

- `SQLITE_DB_PATH`: Path to the SQLite database file (required)

## Security

- Only SELECT queries are allowed via the `query` command
- INSERT, UPDATE, DELETE, DROP, CREATE, ALTER are rejected
- Queries are validated before execution

## Examples

```bash
# Inspect the database
bash {baseDir}/query.sh tables
bash {baseDir}/query.sh schema items

# Query with different formats
bash {baseDir}/query.sh query "SELECT name, status FROM items ORDER BY name" --format table
bash {baseDir}/query.sh query "SELECT * FROM logs WHERE date > '2025-01-01'" --format json
bash {baseDir}/query.sh query "SELECT * FROM metrics" --format csv > export.csv
```

## Troubleshooting

### "no such table" error
Run `bash {baseDir}/query.sh tables` to list available tables.

### Database locked
Another process is writing. SQLite handles this automatically — wait and retry.

### Database not found
Check that `SQLITE_DB_PATH` is set to a valid file path.
