#!/usr/bin/env python3
"""
Take Note Skill
Capture notes, learnings, and context into ChromaDB for long-term memory.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

try:
    import chromadb
except ImportError:
    print("Error: chromadb package not installed", file=sys.stderr)
    print("Install with: pip install chromadb", file=sys.stderr)
    sys.exit(1)


# Configuration
CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = os.environ.get("CHROMADB_PORT", "8000")
COLLECTION_NAME = "notes"


def get_client() -> chromadb.Client:
    """Get ChromaDB client (connects to server)."""
    return chromadb.HttpClient(host=CHROMADB_HOST, port=int(CHROMADB_PORT))


def get_collection(client: chromadb.Client):
    """Get or create notes collection."""
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )


def generate_note_id(text: str) -> str:
    """Generate a unique note ID with timestamp and content hash."""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:6]
    return f"note-{timestamp}-{content_hash}"


def add_note(text: str, note_id: str = None, category: str = "general", tags: str = ""):
    """Add a note to ChromaDB."""
    if not text or not text.strip():
        print("Error: Note text cannot be empty", file=sys.stderr)
        sys.exit(1)

    if not note_id:
        note_id = generate_note_id(text)

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "category": category,
        "source": "agent",
        "type": "note"
    }

    if tags:
        metadata["tags"] = tags

    client = get_client()
    collection = get_collection(client)

    collection.upsert(
        ids=[note_id],
        documents=[text],
        metadatas=[metadata]
    )

    print(f"✓ Note saved: {note_id}")
    print(f"  Category: {category}")
    if tags:
        print(f"  Tags: {tags}")
    print(f"  Text: {text[:100]}{'...' if len(text) > 100 else ''}")


def search_notes(query: str, limit: int = 5):
    """Search notes by semantic similarity."""
    client = get_client()
    collection = get_collection(client)

    results = collection.query(
        query_texts=[query],
        n_results=limit
    )

    if not results['ids'] or not results['ids'][0]:
        print("No notes found.")
        return

    print(f"=== Search Results: \"{query}\" ===\n")

    for i, (note_id, text, metadata, distance) in enumerate(zip(
        results['ids'][0],
        results['documents'][0],
        results['metadatas'][0],
        results['distances'][0]
    ), 1):
        similarity = 1 - distance
        print(f"{i}. [{similarity:.3f}] {note_id}")
        print(f"   {text[:150]}{'...' if len(text) > 150 else ''}")

        category = metadata.get('category', 'unknown')
        timestamp = metadata.get('timestamp', 'unknown')
        tags = metadata.get('tags', '')

        print(f"   Category: {category} | Time: {timestamp}")
        if tags:
            print(f"   Tags: {tags}")
        print()


def list_notes(limit: int = 10):
    """List recent notes."""
    client = get_client()
    collection = get_collection(client)

    results = collection.get()

    if not results['ids']:
        print("No notes found.")
        return

    notes = []
    for note_id, text, metadata in zip(results['ids'], results['documents'], results['metadatas']):
        timestamp = metadata.get('timestamp', '1970-01-01T00:00:00')
        notes.append({
            'id': note_id,
            'text': text,
            'metadata': metadata,
            'timestamp': timestamp
        })

    notes.sort(key=lambda x: x['timestamp'], reverse=True)
    notes = notes[:limit]

    print(f"=== Recent Notes (showing {len(notes)}) ===\n")

    for note in notes:
        note_id = note['id']
        text = note['text']
        metadata = note['metadata']

        category = metadata.get('category', 'unknown')
        timestamp = metadata.get('timestamp', 'unknown')
        tags = metadata.get('tags', '')

        print(f"• {note_id}")
        print(f"  {text[:120]}{'...' if len(text) > 120 else ''}")
        print(f"  Category: {category} | Time: {timestamp}")
        if tags:
            print(f"  Tags: {tags}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Capture notes and learnings into ChromaDB"
    )

    parser.add_argument("text", nargs="?", help="Note text to capture")
    parser.add_argument("--id", help="Custom note ID (auto-generated if not provided)")
    parser.add_argument("--category", default="general", help="Note category (default: general)")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--search", help="Search notes by query")
    parser.add_argument("--list", action="store_true", help="List recent notes")
    parser.add_argument("--limit", type=int, default=10, help="Limit for search/list results (default: 10)")

    args = parser.parse_args()

    if args.search:
        search_notes(args.search, args.limit)
        return

    if args.list:
        list_notes(args.limit)
        return

    if not args.text:
        parser.error("Note text is required (or use --search or --list)")

    add_note(args.text, args.id, args.category, args.tags)


if __name__ == "__main__":
    main()
