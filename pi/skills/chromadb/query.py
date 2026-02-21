#!/usr/bin/env python3
"""
ChromaDB Skill
Semantic search for model descriptions and content using ChromaDB vector database
"""

import argparse
import json
import os
import sys

# Suppress ONNX Runtime GPU device discovery warnings.
# Must be set before onnxruntime is imported (chromadb imports it).
# If the warning still appears, set ORT_LOG_LEVEL=ERROR in the shell environment.
os.environ["ORT_LOG_LEVEL"] = "ERROR"

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("Error: chromadb package not installed", file=sys.stderr)
    print("Install with: pip install chromadb", file=sys.stderr)
    sys.exit(1)


# Configuration
CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = os.environ.get("CHROMADB_PORT", "8000")
CHROMADB_PATH = os.environ.get("CHROMADB_PATH")  # Only use if explicitly set

# Default collections
DEFAULT_COLLECTIONS = ["models", "memories", "notes", "posts"]


def get_client() -> chromadb.Client:
    """Get ChromaDB client based on configuration."""
    if CHROMADB_PATH:
        # Persistent local mode (only if explicitly requested)
        return chromadb.PersistentClient(path=CHROMADB_PATH)
    else:
        # Server mode (default)
        return chromadb.HttpClient(host=CHROMADB_HOST, port=int(CHROMADB_PORT))


def get_or_create_collection(client: chromadb.Client, name: str):
    """Get or create a collection."""
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}
    )


def cmd_query(args):
    """Query a collection for similar items."""
    client = get_client()

    try:
        collection = client.get_collection(args.collection)
    except Exception as e:
        print(f"Error: Collection '{args.collection}' not found", file=sys.stderr)
        print("Use 'collections' command to list available collections", file=sys.stderr)
        sys.exit(1)

    # Build query parameters
    query_params = {
        "query_texts": [args.query],
        "n_results": args.limit,
    }

    # Add where filter if provided
    if args.where:
        try:
            query_params["where"] = json.loads(args.where)
        except json.JSONDecodeError as e:
            print(f"Error parsing --where JSON: {e}", file=sys.stderr)
            sys.exit(1)

    results = collection.query(**query_params)

    print(f"=== Search Results: \"{args.query}\" ===")
    print(f"Collection: {args.collection}")
    print("")

    if not results["ids"] or not results["ids"][0]:
        print("No results found.")
        return

    ids = results["ids"][0]
    documents = results["documents"][0] if results["documents"] else [None] * len(ids)
    distances = results["distances"][0] if results["distances"] else [None] * len(ids)
    metadatas = results["metadatas"][0] if results["metadatas"] else [None] * len(ids)

    for i, (id_, doc, dist, meta) in enumerate(zip(ids, documents, distances, metadatas)):
        similarity = 1 - dist if dist is not None else None
        sim_str = f"{similarity:.3f}" if similarity is not None else "N/A"

        print(f"{i+1}. [{sim_str}] {id_}")
        if doc:
            # Truncate long documents
            preview = doc[:200] + "..." if len(doc) > 200 else doc
            print(f"   {preview}")
        if meta:
            print(f"   Metadata: {json.dumps(meta)}")
        print("")


def cmd_similar(args):
    """Find items similar to an existing item."""
    client = get_client()

    try:
        collection = client.get_collection(args.collection)
    except Exception:
        print(f"Error: Collection '{args.collection}' not found", file=sys.stderr)
        sys.exit(1)

    # Get the reference item
    try:
        ref_results = collection.get(ids=[args.id], include=["embeddings", "documents"])
    except Exception as e:
        print(f"Error getting item: {e}", file=sys.stderr)
        sys.exit(1)

    if not ref_results["ids"]:
        print(f"Item not found: {args.id}")
        sys.exit(1)

    # Query with the embedding
    embeddings = ref_results.get("embeddings")
    if embeddings is not None and len(embeddings) > 0:
        results = collection.query(
            query_embeddings=[ref_results["embeddings"][0]],
            n_results=args.limit + 1,  # +1 because it will include itself
        )
    else:
        # Fall back to document text if no embedding stored
        doc = ref_results["documents"][0] if ref_results.get("documents") else None
        if not doc:
            print("Error: Item has no document or embedding", file=sys.stderr)
            sys.exit(1)
        results = collection.query(
            query_texts=[doc],
            n_results=args.limit + 1,
        )

    print(f"=== Similar to: {args.id} ===")
    print(f"Collection: {args.collection}")
    print("")

    ids = results["ids"][0]
    documents = results["documents"][0] if results["documents"] else [None] * len(ids)
    distances = results["distances"][0] if results["distances"] else [None] * len(ids)

    count = 0
    for id_, doc, dist in zip(ids, documents, distances):
        if id_ == args.id:
            continue  # Skip the reference item
        count += 1
        if count > args.limit:
            break

        similarity = 1 - dist if dist is not None else None
        sim_str = f"{similarity:.3f}" if similarity is not None else "N/A"

        print(f"{count}. [{sim_str}] {id_}")
        if doc:
            preview = doc[:200] + "..." if len(doc) > 200 else doc
            print(f"   {preview}")
        print("")


def cmd_add(args):
    """Add an item to a collection."""
    client = get_client()
    collection = get_or_create_collection(client, args.collection)

    # Parse metadata if provided
    metadata = None
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            print(f"Error parsing --metadata JSON: {e}", file=sys.stderr)
            sys.exit(1)

    # Add or update the item
    try:
        collection.upsert(
            ids=[args.id],
            documents=[args.text],
            metadatas=[metadata] if metadata else None,
        )
        print(f"Added/updated item: {args.id}")
        print(f"Collection: {args.collection}")
    except Exception as e:
        print(f"Error adding item: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_collections(args):
    """List all collections."""
    client = get_client()

    collections = client.list_collections()

    print("=== ChromaDB Collections ===")
    print("")

    if not collections:
        print("No collections found.")
        print("")
        print("Create a collection with:")
        print("  search.py create-collection <name>")
        return

    for coll in collections:
        count = coll.count()
        print(f"  {coll.name}: {count} items")

    print("")
    print(f"Total: {len(collections)} collections")


def cmd_create_collection(args):
    """Create a new collection."""
    client = get_client()

    try:
        collection = client.create_collection(
            name=args.name,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"Created collection: {args.name}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"Collection already exists: {args.name}")
        else:
            print(f"Error creating collection: {e}", file=sys.stderr)
            sys.exit(1)


def cmd_delete(args):
    """Delete an item from a collection."""
    client = get_client()

    try:
        collection = client.get_collection(args.collection)
    except Exception:
        print(f"Error: Collection '{args.collection}' not found", file=sys.stderr)
        sys.exit(1)

    try:
        collection.delete(ids=[args.id])
        print(f"Deleted item: {args.id}")
        print(f"Collection: {args.collection}")
    except Exception as e:
        print(f"Error deleting item: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="ChromaDB Semantic Search")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Query command
    query_parser = subparsers.add_parser("query", help="Search for similar items")
    query_parser.add_argument("query", help="Search query text")
    query_parser.add_argument("--collection", required=True, help="Collection to search")
    query_parser.add_argument("--limit", type=int, default=5, help="Max results")
    query_parser.add_argument("--where", help="Metadata filter (JSON)")
    query_parser.set_defaults(func=cmd_query)

    # Similar command
    similar_parser = subparsers.add_parser("similar", help="Find similar to existing item")
    similar_parser.add_argument("id", help="Item ID to find similar to")
    similar_parser.add_argument("--collection", required=True, help="Collection to search")
    similar_parser.add_argument("--limit", type=int, default=5, help="Max results")
    similar_parser.set_defaults(func=cmd_similar)

    # Add command
    add_parser = subparsers.add_parser("add", help="Add an item to a collection")
    add_parser.add_argument("--collection", required=True, help="Collection name")
    add_parser.add_argument("--id", required=True, help="Item ID")
    add_parser.add_argument("--text", required=True, help="Text content")
    add_parser.add_argument("--metadata", help="Metadata (JSON)")
    add_parser.set_defaults(func=cmd_add)

    # Collections command
    coll_parser = subparsers.add_parser("collections", help="List all collections")
    coll_parser.set_defaults(func=cmd_collections)

    # Create collection command
    create_parser = subparsers.add_parser("create-collection", help="Create a new collection")
    create_parser.add_argument("name", help="Collection name")
    create_parser.set_defaults(func=cmd_create_collection)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete an item from a collection")
    delete_parser.add_argument("id", help="Item ID to delete")
    delete_parser.add_argument("--collection", required=True, help="Collection name")
    delete_parser.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
