#!/usr/bin/env python3
"""
Self-Reflection Skill — Self-reflection and continuous learning.

Gather context, review accumulated knowledge, identify gaps,
brainstorm improvements, and produce actionable insights.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

try:
    import chromadb
except ImportError:
    print("Error: chromadb package not installed", file=sys.stderr)
    sys.exit(1)

# ============================================================================
# Configuration — adjust these paths for your project
# ============================================================================

CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = os.environ.get("CHROMADB_PORT", "8000")
COLLECTION = "notes"

WORKSPACE = Path(os.environ.get("WORKSPACE", "."))
REFLECTIONS_DIR = WORKSPACE / "reflections"

# Override these to point at your project's skill directories
SKILL_DIRS = [
    WORKSPACE / "skills",
]

# Path to Planka skill (if available)
PLANKA_SKILL = os.environ.get("PLANKA_SKILL_PATH", "")

# Path to SQLite skill (if available)
SQLITE_SKILL = os.environ.get("SQLITE_SKILL_PATH", "")


# ============================================================================
# ChromaDB
# ============================================================================

def get_chroma_client():
    return chromadb.HttpClient(host=CHROMADB_HOST, port=int(CHROMADB_PORT))


def get_collection_stats(client):
    """Get counts for all collections."""
    stats = {}
    for coll in client.list_collections():
        stats[coll.name] = coll.count()
    return stats


def get_recent_notes(client, limit=20):
    """Get recent notes from the notes collection."""
    try:
        collection = client.get_collection("notes")
        results = collection.get()
        notes = []
        for nid, doc, meta in zip(results['ids'], results['documents'], results['metadatas']):
            ts = meta.get('timestamp', 'unknown')
            cat = meta.get('category', 'unknown')
            tags = meta.get('tags', '')
            source = meta.get('source', 'unknown')
            notes.append({
                'id': nid,
                'text': doc[:200],
                'timestamp': ts,
                'category': cat,
                'tags': tags,
                'source': source,
            })
        notes.sort(key=lambda x: x['timestamp'] if x['timestamp'] != 'unknown' else '', reverse=True)
        return notes[:limit]
    except Exception as e:
        return [{'error': str(e)}]


def get_past_reflections(client, limit=5):
    """Search for past reflection notes."""
    try:
        collection = client.get_collection("notes")
        results = collection.get(where={"category": "reflection"})
        reflections = []
        for nid, doc, meta in zip(results['ids'], results['documents'], results['metadatas']):
            reflections.append({
                'id': nid,
                'text': doc[:300],
                'timestamp': meta.get('timestamp', 'unknown'),
            })
        reflections.sort(key=lambda x: x['timestamp'], reverse=True)
        return reflections[:limit]
    except Exception:
        return []


def save_reflection(client, text, tags=""):
    """Save a reflection note to ChromaDB."""
    collection = client.get_or_create_collection("notes", metadata={"hnsw:space": "cosine"})
    ts = datetime.now()
    note_id = f"reflection-{ts.strftime('%Y-%m-%d-%H%M%S')}"
    metadata = {
        "timestamp": ts.isoformat(),
        "category": "reflection",
        "source": "agent",
        "type": "reflection",
    }
    if tags:
        metadata["tags"] = tags
    collection.upsert(ids=[note_id], documents=[text], metadatas=[metadata])
    return note_id


# ============================================================================
# Shell helpers
# ============================================================================

def run_cmd(cmd, cwd=None, timeout=30):
    """Run a shell command and return stdout."""
    try:
        env = os.environ.copy()
        # Source .env file if present
        env_file = WORKSPACE / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    env[key.strip()] = val.strip().strip('"').strip("'")

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=cwd, timeout=timeout, env=env,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"[error: {e}]"


# ============================================================================
# Gather Phase
# ============================================================================

def gather_planka():
    """Get current Planka task state."""
    if not PLANKA_SKILL:
        return {"note": "Planka skill not configured — set PLANKA_SKILL_PATH"}

    output = run_cmd(f"bash {PLANKA_SKILL} list", cwd=Path(PLANKA_SKILL).parent)
    tasks = {"backlog": [], "next_up": [], "in_progress": [], "done": [], "other": []}

    current_list = "other"
    for line in output.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("[Backlog]"):
            current_list = "backlog"
            tasks["backlog"].append(line_stripped.replace("[Backlog] ", ""))
        elif line_stripped.startswith("[Next Up]"):
            current_list = "next_up"
            tasks["next_up"].append(line_stripped.replace("[Next Up] ", ""))
        elif "Progress" in line_stripped and line_stripped.startswith("["):
            current_list = "in_progress"
            title = line_stripped.split("] ", 1)[-1] if "] " in line_stripped else line_stripped
            tasks["in_progress"].append(title)
        elif line_stripped.startswith("[Done]"):
            current_list = "done"
            tasks["done"].append(line_stripped.replace("[Done] ", ""))
        elif line_stripped.startswith("["):
            current_list = "other"
            tasks["other"].append(line_stripped)

    return tasks


def gather_catalog():
    """Get data catalog summary via SQLite skill."""
    if not SQLITE_SKILL:
        return {"note": "SQLite skill not configured — set SQLITE_SKILL_PATH"}

    status_output = run_cmd(
        f"bash {SQLITE_SKILL} tables",
        cwd=Path(SQLITE_SKILL).parent,
    )

    return {"status_distribution": status_output}


def gather_skills():
    """Inventory all available skills."""
    skills = []
    for skill_dir in SKILL_DIRS:
        if skill_dir.exists():
            for item in sorted(skill_dir.iterdir()):
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    skills.append(item.name)
    return skills


# ============================================================================
# Identify Phase
# ============================================================================

def identify_gaps(skills, tasks, catalog):
    """Identify missing skills, workflow friction, and opportunities."""
    gaps = {
        "missing_skills": [],
        "workflow_friction": [],
        "opportunities": [],
        "blocked_items": [],
    }

    existing = set(skills)

    if "workspace-audit" not in existing:
        gaps["missing_skills"].append({
            "name": "workspace-audit",
            "reason": "Quick scan of disk, processes, database sizes — useful for system health",
        })

    if "catalog-report" not in existing:
        gaps["missing_skills"].append({
            "name": "catalog-report",
            "reason": "Generate formatted reports from data catalog — summaries and pipeline status",
        })

    # Identify blocked items from tasks
    if isinstance(tasks, dict):
        for task in tasks.get("next_up", []):
            if "credential" in task.lower() or "configure" in task.lower():
                gaps["blocked_items"].append(task)

    return gaps


# ============================================================================
# Dream Phase — Brainstorm improvements
# ============================================================================

def dream():
    """Brainstorm improvements and opportunities."""
    insights = []

    insights.append({
        "theme": "Quality Over Quantity",
        "application": "Focus on doing fewer things well rather than spreading thin. "
                       "Document what works, automate what repeats, ship what's ready.",
    })

    insights.append({
        "theme": "The Knowledge Base",
        "application": "Every learning, every decision, every observation should be captured. "
                       "Build the knowledge base that makes future work faster.",
    })

    insights.append({
        "theme": "Accessibility",
        "application": "Make tools easy to use. Clear documentation, sensible defaults, "
                       "example commands. Good tools invite use.",
    })

    insights.append({
        "theme": "Technical Debt",
        "application": "Acknowledge the maintenance burden. Face it directly — "
                       "don't pretend it doesn't exist. Budget time for cleanup.",
    })

    insights.append({
        "theme": "Integration",
        "application": "The power is in connections between systems. "
                       "Build bridges between the databases, the skills, the platforms.",
    })

    insights.append({
        "theme": "Ship What's Ready",
        "application": "Inventory rots. If something is ready, release it. "
                       "Perfect is the enemy of shipped.",
    })

    return insights


# ============================================================================
# Output
# ============================================================================

def format_reflection(gathered, gaps, insights):
    """Format the full reflection as a document."""
    now = datetime.now()
    lines = []

    lines.append(f"# Reflection — {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # === Context Summary ===
    lines.append("## I. Current State")
    lines.append("")

    if isinstance(gathered.get("tasks"), dict):
        tasks = gathered["tasks"]
        lines.append(f"**Tasks:**")
        lines.append(f"- Backlog: {len(tasks.get('backlog', []))} items")
        lines.append(f"- Next Up: {len(tasks.get('next_up', []))} items")
        lines.append(f"- In Progress: {len(tasks.get('in_progress', []))} items")
        lines.append(f"- Done: {len(tasks.get('done', []))} items")
        if tasks.get('in_progress'):
            lines.append(f"- Currently working: {', '.join(tasks['in_progress'])}")
        lines.append("")

    if isinstance(gathered.get("collections"), dict):
        lines.append(f"**ChromaDB Collections:**")
        for name, count in gathered["collections"].items():
            lines.append(f"- {name}: {count} items")
        lines.append("")

    lines.append(f"**Skills Available:** {len(gathered.get('skills', []))}")
    lines.append("")

    # === Gaps ===
    lines.append("## II. What Is Missing")
    lines.append("")

    if gaps.get("missing_skills"):
        lines.append("**Skills that would be useful:**")
        for skill in gaps["missing_skills"]:
            lines.append(f"- **{skill['name']}** — {skill['reason']}")
        lines.append("")

    if gaps.get("blocked_items"):
        lines.append("**Blocked on human action:**")
        for item in gaps["blocked_items"]:
            lines.append(f"- {item}")
        lines.append("")

    if gaps.get("workflow_friction"):
        lines.append("**Workflow friction:**")
        for friction in gaps["workflow_friction"]:
            lines.append(f"- {friction}")
        lines.append("")

    if gaps.get("opportunities"):
        lines.append("**Opportunities:**")
        for opp in gaps["opportunities"]:
            lines.append(f"- {opp}")
        lines.append("")

    # === Insights ===
    lines.append("## III. Insights")
    lines.append("")

    for insight in insights:
        lines.append(f"### {insight['theme']}")
        lines.append(f"→ {insight['application']}")
        lines.append("")

    # === Closing ===
    lines.append("---")
    lines.append(f"*Reflection recorded {now.isoformat()}*")

    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Self-reflection and continuous learning")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="Full reflection")
    mode.add_argument("--quick", action="store_true", help="Quick gather + identify only")
    mode.add_argument("--phase", choices=["gather", "review", "dream"], help="Run a specific phase")
    parser.add_argument("--output", type=str, help="Save reflection to directory")
    parser.add_argument("--no-save", action="store_true", help="Don't save to ChromaDB")

    args = parser.parse_args()

    if not args.full and not args.quick and not args.phase:
        args.full = True

    print("=" * 60)
    print("  SELF-REFLECTION")
    print("=" * 60)
    print()

    # === GATHER ===
    print("◆ Phase I: Gathering context...")
    client = get_chroma_client()
    gathered = {
        "collections": get_collection_stats(client),
        "notes": get_recent_notes(client),
        "past_reflections": get_past_reflections(client),
        "tasks": gather_planka(),
        "catalog": gather_catalog(),
        "skills": gather_skills(),
    }

    print(f"  Collections: {gathered['collections']}")
    print(f"  Notes: {len(gathered['notes'])} recent")
    print(f"  Past reflections: {len(gathered['past_reflections'])}")
    print(f"  Skills: {len(gathered['skills'])}")
    print()

    if args.phase == "gather":
        print(json.dumps(gathered, indent=2, default=str))
        return

    # === IDENTIFY ===
    print("◆ Phase II: Identifying gaps...")
    gaps = identify_gaps(gathered['skills'], gathered['tasks'], gathered['catalog'])
    print(f"  Missing skills: {len(gaps['missing_skills'])}")
    print(f"  Workflow friction: {len(gaps['workflow_friction'])}")
    print(f"  Opportunities: {len(gaps['opportunities'])}")
    print(f"  Blocked items: {len(gaps['blocked_items'])}")
    print()

    if args.quick:
        print("--- Quick Reflection Complete ---")
        print()
        for g in gaps['missing_skills']:
            print(f"  SKILL GAP: {g['name']} — {g['reason']}")
        for f in gaps['workflow_friction']:
            print(f"  FRICTION: {f}")
        for o in gaps['opportunities']:
            print(f"  OPPORTUNITY: {o}")
        return

    # === DREAM ===
    print("◆ Phase III: Brainstorming improvements...")
    insights = dream()
    print(f"  Generated {len(insights)} insights")
    for ins in insights:
        print(f"    • {ins['theme']}")
    print()

    if args.phase == "dream":
        for ins in insights:
            print(f"\n  === {ins['theme']} ===")
            print(f"  {ins['application']}")
        return

    # === FORMAT & SAVE ===
    print("◆ Phase IV: Recording the reflection...")
    reflection_text = format_reflection(gathered, gaps, insights)

    if not args.no_save:
        note_id = save_reflection(
            client, reflection_text,
            tags="reflection,self-knowledge,continuous-learning"
        )
        print(f"  Saved to ChromaDB: {note_id}")

    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"reflection-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"
        output_path = output_dir / filename
        output_path.write_text(reflection_text, encoding='utf-8')
        print(f"  Saved to file: {output_path}")

    print()
    print("=" * 60)
    print()
    print(reflection_text)
    print()
    print("=" * 60)
    print("  Reflection complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
