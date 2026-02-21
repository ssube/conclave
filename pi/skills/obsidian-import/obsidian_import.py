#!/usr/bin/env python3
"""
Obsidian Import — Index an Obsidian vault into ChromaDB for semantic search.

Parses markdown structure (frontmatter, headings, tags, links, tables),
chunks content by heading hierarchy, and upserts into ChromaDB with
rich metadata for filtering.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:
    yaml = None

# Suppress ONNX Runtime warnings before chromadb import
os.environ.setdefault("ORT_LOG_LEVEL", "ERROR")

try:
    import chromadb
except ImportError:
    print("Error: chromadb package not installed", file=sys.stderr)
    print("Install with: pip install chromadb", file=sys.stderr)
    sys.exit(1)


# ── Configuration ────────────────────────────────────────────

CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8000"))
CHROMADB_PATH = os.environ.get("CHROMADB_PATH", "")

DEFAULT_COLLECTION = "vault"
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 150
MIN_SECTION_LENGTH = 50

# Directories to always skip
SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__", "node_modules"}

STATE_FILE = ".obsidian-import-state.json"


# ── ChromaDB Client ─────────────────────────────────────────

def get_chromadb_client() -> chromadb.ClientAPI:
    """Connect to ChromaDB server or persistent local storage."""
    if CHROMADB_PATH:
        Path(CHROMADB_PATH).mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=CHROMADB_PATH)
    return chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)


# ── Text Utilities ───────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s\-/]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def make_chunk_id(filepath_rel: str, heading_path: str, chunk_index: int = 0,
                  total_chunks: int = 1) -> str:
    """
    Generate a deterministic chunk ID from file path and heading hierarchy.
    Format: slugified-path::slugified-headings[::chunk-N]
    """
    file_slug = slugify(str(filepath_rel).removesuffix(".md"))
    heading_slug = slugify(heading_path) if heading_path else ""
    base_id = f"{file_slug}::{heading_slug}" if heading_slug else f"{file_slug}::"
    if total_chunks > 1:
        base_id += f"::chunk-{chunk_index}"
    return base_id


# ── Frontmatter Parsing ─────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    Extract YAML frontmatter from markdown content.
    Returns (frontmatter_dict, remaining_content).
    """
    if not content.startswith("---"):
        return {}, content

    # Find closing ---
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return {}, content

    yaml_block = content[3:end_match.start() + 3]
    remaining = content[end_match.end() + 3:]

    if yaml is None:
        # Fallback: basic key: value parsing without PyYAML
        fm = {}
        for line in yaml_block.strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value.startswith("[") and value.endswith("]"):
                    # Basic list parsing
                    items = value[1:-1].split(",")
                    fm[key] = [i.strip().strip("\"'") for i in items if i.strip()]
                elif value.lower() in ("true", "false"):
                    fm[key] = value.lower() == "true"
                elif value.replace(".", "", 1).replace("-", "", 1).isdigit():
                    try:
                        fm[key] = int(value) if "." not in value else float(value)
                    except ValueError:
                        fm[key] = value
                else:
                    fm[key] = value.strip("\"'")
        return fm, remaining

    try:
        fm = yaml.safe_load(yaml_block)
        if not isinstance(fm, dict):
            return {}, content
        return fm, remaining
    except yaml.YAMLError:
        return {}, content


def flatten_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten frontmatter for ChromaDB metadata (only str/int/float/bool allowed).
    Lists are joined with commas. Nested objects are skipped.
    """
    flat = {}
    for key, value in fm.items():
        if isinstance(value, (str, int, float, bool)):
            flat[f"fm_{key}"] = value
        elif isinstance(value, list):
            # Join list items as comma-separated string
            str_items = [str(v) for v in value if isinstance(v, (str, int, float))]
            if str_items:
                flat[f"fm_{key}"] = ", ".join(str_items)
        # Skip dicts, None, and other complex types
    return flat


# ── Tag & Link Extraction ───────────────────────────────────

TAG_PATTERN = re.compile(
    r"(?:^|\s)#([a-zA-Z][a-zA-Z0-9_/-]*)",
    re.MULTILINE,
)

LINK_PATTERN = re.compile(
    r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"
)

CODE_FENCE = re.compile(r"^```", re.MULTILINE)


def extract_inline_tags(text: str) -> list[str]:
    """Extract #tags from markdown body text (not inside code blocks)."""
    # Remove code blocks before scanning for tags
    cleaned = CODE_FENCE.sub("", text)
    tags = TAG_PATTERN.findall(cleaned)
    # Deduplicate, preserving order
    seen = set()
    result = []
    for t in tags:
        t_lower = t.lower()
        if t_lower not in seen:
            seen.add(t_lower)
            result.append(t_lower)
    return result


def extract_links(text: str) -> list[str]:
    """Extract [[wiki links]] from text."""
    links = LINK_PATTERN.findall(text)
    seen = set()
    result = []
    for link in links:
        link = link.strip()
        if link and link not in seen:
            seen.add(link)
            result.append(link)
    return result


# ── Section Splitting ────────────────────────────────────────

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


class Section:
    """A heading-delimited section of a markdown file."""

    def __init__(self, heading: str, level: int, content: str,
                 heading_path: str):
        self.heading = heading
        self.level = level
        self.content = content
        self.heading_path = heading_path  # "H1 > H2 > H3"

    @property
    def text(self) -> str:
        """Full text including heading."""
        if self.heading:
            prefix = "#" * self.level
            return f"{prefix} {self.heading}\n\n{self.content}"
        return self.content

    @property
    def has_table(self) -> bool:
        return bool(re.search(r"^\|.*\|.*\|", self.content, re.MULTILINE))

    @property
    def has_code(self) -> bool:
        return "```" in self.content

    def __repr__(self):
        return f"Section({self.heading_path!r}, {len(self.content)} chars)"


def split_into_sections(content: str) -> list[Section]:
    """
    Split markdown content into sections by heading hierarchy.
    Tracks the full heading path (e.g., "Overview > Design > API").
    """
    sections = []
    heading_stack: list[tuple[int, str]] = []  # [(level, heading), ...]

    # Find all headings with their positions
    headings = list(HEADING_PATTERN.finditer(content))

    if not headings:
        # No headings — entire content is one section
        text = content.strip()
        if text:
            sections.append(Section("", 0, text, ""))
        return sections

    # Content before first heading
    pre_heading = content[:headings[0].start()].strip()
    if pre_heading:
        sections.append(Section("", 0, pre_heading, ""))

    for i, match in enumerate(headings):
        level = len(match.group(1))
        heading = match.group(2).strip()

        # Determine content: from end of this heading line to start of next heading
        content_start = match.end()
        content_end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        section_content = content[content_start:content_end].strip()

        # Update heading stack
        # Pop everything at this level or deeper
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, heading))

        # Build heading path
        heading_path = " > ".join(h for _, h in heading_stack)

        sections.append(Section(heading, level, section_content, heading_path))

    return sections


# ── Chunking ─────────────────────────────────────────────────

class Chunk:
    """A chunk of content ready for ChromaDB insertion."""

    def __init__(self, text: str, metadata: dict[str, Any], chunk_id: str):
        self.text = text
        self.metadata = metadata
        self.chunk_id = chunk_id

    def __repr__(self):
        return f"Chunk({self.chunk_id!r}, {len(self.text)} chars)"


def chunk_text(text: str, max_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """
    Split text into chunks at paragraph boundaries with overlap.
    Returns a list of chunk strings.
    """
    if len(text) <= max_size:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
                # Overlap: keep tail of previous chunk
                if overlap > 0 and len(current) > overlap:
                    tail = current[-overlap:]
                    # Try to start at a sentence boundary
                    sentence_break = tail.rfind(". ")
                    if sentence_break > 0:
                        tail = tail[sentence_break + 2:]
                    current = (tail + "\n\n" + para).strip()
                else:
                    current = para
            else:
                # Single paragraph exceeds max — split by sentences
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    candidate = (current + " " + sent).strip() if current else sent
                    if len(candidate) <= max_size:
                        current = candidate
                    else:
                        if current:
                            chunks.append(current)
                        current = sent

    if current:
        chunks.append(current)

    return chunks


def sections_to_chunks(
    sections: list[Section],
    filepath_rel: str,
    frontmatter: dict[str, Any],
    file_tags: list[str],
    max_chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """
    Convert parsed sections into chunks with metadata, ready for ChromaDB.
    Merges short sections into subsequent sections.
    """
    now = datetime.now(timezone.utc).isoformat()
    fm_metadata = flatten_frontmatter(frontmatter)
    chunks = []

    # Merge short sections into the next one
    merged_sections: list[Section] = []
    pending_text = ""

    for section in sections:
        full_text = section.text.strip()
        if len(full_text) < MIN_SECTION_LENGTH and not section.has_table:
            # Too short to stand alone — prepend to next section
            pending_text += full_text + "\n\n"
        else:
            if pending_text:
                full_text = pending_text + full_text
                pending_text = ""
            merged_sections.append(
                Section(section.heading, section.level, full_text,
                        section.heading_path)
            )

    # Flush any remaining pending text
    if pending_text:
        if merged_sections:
            last = merged_sections[-1]
            merged_sections[-1] = Section(
                last.heading, last.level,
                last.content + "\n\n" + pending_text.strip(),
                last.heading_path,
            )
        else:
            merged_sections.append(Section("", 0, pending_text.strip(), ""))

    for section in merged_sections:
        section_text = section.text.strip()
        if not section_text:
            continue

        # Extract links and tags from this section
        section_tags = extract_inline_tags(section.content)
        section_links = extract_links(section.content)
        all_tags = sorted(set(file_tags + section_tags))

        # Chunk the section if needed
        text_chunks = chunk_text(section_text, max_chunk_size, chunk_overlap)
        total_chunks = len(text_chunks)

        for idx, chunk_text_str in enumerate(text_chunks):
            chunk_id = make_chunk_id(filepath_rel, section.heading_path,
                                     idx, total_chunks)
            metadata = {
                "source_file": filepath_rel,
                "heading_path": section.heading_path,
                "heading_level": section.level,
                "chunk_index": idx,
                "total_chunks": total_chunks,
                "char_count": len(chunk_text_str),
                "has_table": section.has_table,
                "has_code": section.has_code,
                "imported_at": now,
            }

            if all_tags:
                metadata["tags"] = ", ".join(all_tags)
            if section_links:
                metadata["links"] = ", ".join(section_links[:20])  # Cap at 20

            # Merge frontmatter metadata
            metadata.update(fm_metadata)

            chunks.append(Chunk(chunk_text_str, metadata, chunk_id))

    return chunks


# ── File Discovery ───────────────────────────────────────────

def discover_files(
    vault_path: Path,
    folder: Optional[str] = None,
    tag: Optional[str] = None,
    glob_pattern: Optional[str] = None,
) -> list[Path]:
    """
    Find all .md files in the vault, applying filters.
    Returns absolute paths sorted alphabetically.
    """
    files = []

    # Determine search root
    search_root = vault_path
    if folder:
        search_root = vault_path / folder
        if not search_root.exists():
            print(f"Warning: folder not found: {search_root}", file=sys.stderr)
            return []

    for md_file in sorted(search_root.rglob("*.md")):
        # Skip excluded directories
        parts = md_file.relative_to(vault_path).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in parts):
            continue

        # Apply glob filter
        if glob_pattern:
            rel = str(md_file.relative_to(vault_path))
            if not fnmatch(rel, glob_pattern):
                continue

        files.append(md_file)

    # Apply tag filter (requires reading files)
    if tag:
        tag_lower = tag.lower().lstrip("#")
        filtered = []
        for f in files:
            content = f.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_frontmatter(content)

            # Check frontmatter tags
            fm_tags = fm.get("tags", [])
            if isinstance(fm_tags, str):
                fm_tags = [t.strip() for t in fm_tags.split(",")]
            elif isinstance(fm_tags, list):
                fm_tags = [str(t).strip() for t in fm_tags]
            else:
                fm_tags = []

            # Check inline tags
            inline_tags = extract_inline_tags(body)

            all_tags = [t.lower().lstrip("#") for t in fm_tags + inline_tags]
            if tag_lower in all_tags:
                filtered.append(f)

        files = filtered

    return files


# ── Incremental State ────────────────────────────────────────

def load_state(vault_path: Path) -> dict[str, float]:
    """Load import state (file mtimes) from state file."""
    state_path = vault_path / STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(vault_path: Path, state: dict[str, float]):
    """Save import state to state file."""
    state_path = vault_path / STATE_FILE
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Parse a Single File ─────────────────────────────────────

def parse_file(filepath: Path, vault_path: Path, max_chunk_size: int,
               chunk_overlap: int) -> list[Chunk]:
    """Parse a markdown file into chunks."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    filepath_rel = str(filepath.relative_to(vault_path))

    # Parse frontmatter
    frontmatter, body = parse_frontmatter(content)

    # Collect file-level tags
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, str):
        fm_tags = [t.strip().lower().lstrip("#") for t in fm_tags.split(",")]
    elif isinstance(fm_tags, list):
        fm_tags = [str(t).strip().lower().lstrip("#") for t in fm_tags]
    else:
        fm_tags = []

    # Split into sections
    sections = split_into_sections(body)

    # Convert to chunks
    return sections_to_chunks(
        sections, filepath_rel, frontmatter, fm_tags,
        max_chunk_size, chunk_overlap,
    )


# ── Commands ─────────────────────────────────────────────────

def cmd_scan(args):
    """Preview what would be imported (dry run)."""
    vault_path = Path(args.vault).resolve()
    if not vault_path.exists():
        print(f"Error: vault not found at {vault_path}", file=sys.stderr)
        sys.exit(1)

    files = discover_files(vault_path, args.folder, args.tag, args.glob)
    if not files:
        print("No .md files found matching filters.")
        return

    total_sections = 0
    total_chunks = 0
    total_chars = 0

    print(f"=== Vault Scan: {vault_path} ===")
    print(f"Files found: {len(files)}")
    print()

    for f in files:
        chunks = parse_file(f, vault_path, args.chunk_size, args.chunk_overlap)
        rel = f.relative_to(vault_path)
        sections = len(set(c.metadata["heading_path"] for c in chunks))

        total_sections += sections
        total_chunks += len(chunks)
        total_chars += sum(len(c.text) for c in chunks)

        print(f"  {rel}: {sections} sections, {len(chunks)} chunks")

    print()
    print(f"Total: {len(files)} files, {total_sections} sections, "
          f"{total_chunks} chunks, {total_chars:,} chars")


def cmd_import(args):
    """Import vault content into ChromaDB."""
    vault_path = Path(args.vault).resolve()
    if not vault_path.exists():
        print(f"Error: vault not found at {vault_path}", file=sys.stderr)
        sys.exit(1)

    files = discover_files(vault_path, args.folder, args.tag, args.glob)
    if not files:
        print("No .md files found matching filters.")
        return

    # Incremental: filter to changed files
    state = {}
    if args.incremental:
        state = load_state(vault_path)
        changed = []
        for f in files:
            rel = str(f.relative_to(vault_path))
            mtime = f.stat().st_mtime
            if rel not in state or state[rel] != mtime:
                changed.append(f)
        skipped = len(files) - len(changed)
        if skipped > 0:
            print(f"Incremental: skipping {skipped} unchanged files")
        files = changed
        if not files:
            print("All files up to date. Nothing to import.")
            return

    # Connect to ChromaDB
    try:
        client = get_chromadb_client()
        collection = client.get_or_create_collection(
            name=args.collection,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"ChromaDB collection: {args.collection}")
    except Exception as e:
        print(f"Error connecting to ChromaDB: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Importing {len(files)} files from {vault_path}")
    print()

    stats = {"files": 0, "chunks": 0, "errors": 0}
    new_state = dict(state)  # Copy existing state for incremental

    for f in files:
        rel = str(f.relative_to(vault_path))
        try:
            chunks = parse_file(f, vault_path, args.chunk_size, args.chunk_overlap)

            if not chunks:
                print(f"  {rel}: (empty, skipped)")
                continue

            # Batch upsert (ChromaDB supports batches)
            batch_size = 100
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                collection.upsert(
                    ids=[c.chunk_id for c in batch],
                    documents=[c.text for c in batch],
                    metadatas=[c.metadata for c in batch],
                )

            stats["files"] += 1
            stats["chunks"] += len(chunks)
            new_state[rel] = f.stat().st_mtime
            print(f"  + {rel}: {len(chunks)} chunks")

        except Exception as e:
            stats["errors"] += 1
            print(f"  ! {rel}: {e}", file=sys.stderr)

    # Save state for incremental
    if args.incremental:
        save_state(vault_path, new_state)

    print()
    print(f"=== Import Summary ===")
    print(f"Files imported: {stats['files']}")
    print(f"Chunks upserted: {stats['chunks']}")
    print(f"Collection total: {collection.count()} items")
    if stats["errors"]:
        print(f"Errors: {stats['errors']}")


def cmd_clear(args):
    """Delete a collection entirely."""
    try:
        client = get_chromadb_client()
        client.delete_collection(args.collection)
        print(f"Deleted collection: {args.collection}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_stats(args):
    """Show collection statistics."""
    try:
        client = get_chromadb_client()
    except Exception as e:
        print(f"Error connecting to ChromaDB: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        collection = client.get_collection(args.collection)
    except Exception:
        print(f"Collection not found: {args.collection}")
        return

    count = collection.count()
    print(f"=== Collection: {args.collection} ===")
    print(f"Total items: {count}")

    if count == 0:
        return

    # Sample some items for metadata overview
    sample = collection.peek(min(count, 10))
    if sample and sample.get("metadatas"):
        # Gather unique source files and tags
        sources = set()
        all_tags = set()
        for meta in sample["metadatas"]:
            if meta and meta.get("source_file"):
                sources.add(meta["source_file"])
            if meta and meta.get("tags"):
                for t in meta["tags"].split(", "):
                    if t:
                        all_tags.add(t)

        if sources:
            print(f"Source files (sample): {len(sources)}")
            for s in sorted(sources)[:10]:
                print(f"  {s}")
        if all_tags:
            print(f"Tags (sample): {', '.join(sorted(all_tags)[:20])}")


# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Import an Obsidian vault into ChromaDB for semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Preview what would be imported
  python3 obsidian_import.py scan --vault ~/my-vault

  # Import everything
  python3 obsidian_import.py import --vault ~/my-vault

  # Import only a subfolder
  python3 obsidian_import.py import --vault ~/my-vault --folder "Projects"

  # Import only tagged files
  python3 obsidian_import.py import --vault ~/my-vault --tag reference

  # Incremental re-import (only changed files)
  python3 obsidian_import.py import --vault ~/my-vault --incremental

  # Clear and start fresh
  python3 obsidian_import.py clear --collection vault
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── scan ──
    p_scan = subparsers.add_parser("scan", help="Preview what would be imported")
    p_scan.add_argument("--vault", required=True, help="Path to Obsidian vault")
    p_scan.add_argument("--folder", help="Only import files in this subfolder")
    p_scan.add_argument("--tag", help="Only import files with this tag")
    p_scan.add_argument("--glob", help="Only import files matching this glob pattern")
    p_scan.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Max chunk size in characters (default: {DEFAULT_CHUNK_SIZE})")
    p_scan.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP,
                        help=f"Chunk overlap in characters (default: {DEFAULT_CHUNK_OVERLAP})")
    p_scan.set_defaults(func=cmd_scan)

    # ── import ──
    p_import = subparsers.add_parser("import", help="Import vault into ChromaDB")
    p_import.add_argument("--vault", required=True, help="Path to Obsidian vault")
    p_import.add_argument("--collection", default=DEFAULT_COLLECTION,
                          help=f"ChromaDB collection name (default: {DEFAULT_COLLECTION})")
    p_import.add_argument("--folder", help="Only import files in this subfolder")
    p_import.add_argument("--tag", help="Only import files with this tag")
    p_import.add_argument("--glob", help="Only import files matching this glob pattern")
    p_import.add_argument("--incremental", action="store_true",
                          help="Skip unchanged files (tracks mtimes)")
    p_import.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                          help=f"Max chunk size in characters (default: {DEFAULT_CHUNK_SIZE})")
    p_import.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP,
                          help=f"Chunk overlap in characters (default: {DEFAULT_CHUNK_OVERLAP})")
    p_import.set_defaults(func=cmd_import)

    # ── clear ──
    p_clear = subparsers.add_parser("clear", help="Delete a collection")
    p_clear.add_argument("--collection", default=DEFAULT_COLLECTION,
                         help=f"Collection to delete (default: {DEFAULT_COLLECTION})")
    p_clear.set_defaults(func=cmd_clear)

    # ── stats ──
    p_stats = subparsers.add_parser("stats", help="Show collection statistics")
    p_stats.add_argument("--collection", default=DEFAULT_COLLECTION,
                         help=f"Collection to inspect (default: {DEFAULT_COLLECTION})")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
