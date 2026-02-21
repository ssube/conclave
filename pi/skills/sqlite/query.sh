#!/bin/bash

# SQLite Query Skill
# Execute read-only SQL queries with formatted output

set -e

# Determine script directory for relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../" && pwd)"

# Database path from environment
DB_PATH="${SQLITE_DB_PATH:-}"

usage() {
    echo "Usage: query.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  query <sql>           Execute a read-only SQL query"
    echo "  tables                List all tables"
    echo "  schema <table>        Describe table schema"
    echo ""
    echo "Options:"
    echo "  --format <type>       Output format: table, json, csv (default: table)"
    echo ""
    echo "Environment:"
    echo "  SQLITE_DB_PATH        Path to SQLite database file (required)"
}

check_db() {
    if [[ -z "$DB_PATH" ]]; then
        echo "Error: SQLITE_DB_PATH environment variable not set" >&2
        exit 1
    fi
    if [[ ! -f "$DB_PATH" ]]; then
        echo "Error: Database file not found: $DB_PATH" >&2
        exit 1
    fi
}

# Validate query is read-only
validate_query() {
    local query="$1"
    local upper_query=$(echo "$query" | tr '[:lower:]' '[:upper:]')

    if [[ "$upper_query" =~ (INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|ATTACH|DETACH) ]]; then
        echo "Error: Write operations are not allowed. Only SELECT queries permitted." >&2
        exit 1
    fi
}

# Execute query with format
execute_query() {
    local query="$1"
    local format="${2:-table}"

    check_db
    validate_query "$query"

    case "$format" in
        table)
            sqlite3 -header -column "$DB_PATH" "$query"
            ;;
        json)
            sqlite3 -json "$DB_PATH" "$query"
            ;;
        csv)
            sqlite3 -header -csv "$DB_PATH" "$query"
            ;;
        *)
            echo "Error: Unknown format: $format" >&2
            echo "Valid formats: table, json, csv" >&2
            exit 1
            ;;
    esac
}

# List all tables
list_tables() {
    check_db
    echo "=== Database Tables ==="
    echo ""
    sqlite3 "$DB_PATH" ".tables"
}

# Describe table schema
describe_schema() {
    local table="$1"
    check_db

    if [[ -z "$table" ]]; then
        echo "Error: Table name required" >&2
        exit 1
    fi

    echo "=== Schema: $table ==="
    echo ""
    sqlite3 -header -column "$DB_PATH" "PRAGMA table_info($table);"
}

# Parse main command
case "$1" in
    query)
        shift
        query="$1"
        shift
        format="table"
        while [[ $# -gt 0 ]]; do
            case $1 in
                --format) format="$2"; shift 2 ;;
                *) shift ;;
            esac
        done
        execute_query "$query" "$format"
        ;;
    tables)
        list_tables
        ;;
    schema)
        describe_schema "$2"
        ;;
    *)
        usage
        ;;
esac
