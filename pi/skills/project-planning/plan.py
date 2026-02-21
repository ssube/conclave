#!/usr/bin/env python3
"""
Project Planning Tool — Create, manage, and execute project plans.

Usage:
    plan.py new <name> [--from-template <template>]
    plan.py list [--status <status>]
    plan.py summary <name>
    plan.py cards <name> [--board <board>] [--list <list>] [--dry-run]
    plan.py status <name> <status>
    plan.py update-header <name>
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

# ============================================================================
# Configuration
# ============================================================================

PLANS_DIR = Path(os.environ.get("PROJECT_PLANS_DIR", "./project_plans"))
PLANKA_SKILL = Path(os.environ.get("PLANKA_SKILL_PATH", "./skills/planka/planka.sh"))

# ============================================================================
# Helpers
# ============================================================================

def slugify(name: str) -> str:
    """Convert a name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def plan_path(name: str) -> Path:
    """Get the path for a plan by name (with or without .md)."""
    slug = slugify(name)
    path = PLANS_DIR / f"{slug}.md"
    if path.exists():
        return path
    # Try exact name
    exact = PLANS_DIR / name
    if exact.exists():
        return exact
    exact_md = PLANS_DIR / f"{name}.md"
    if exact_md.exists():
        return exact_md
    # Try fuzzy match
    for f in PLANS_DIR.glob("*.md"):
        if slug in f.stem.lower():
            return f
    return path  # Return expected path even if not found


def load_env():
    """Load environment variables from .env files."""
    env = os.environ.copy()
    for env_file in [Path(".env")]:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def run_planka(args: str, env=None) -> str:
    """Run a planka.sh command."""
    if env is None:
        env = load_env()
    try:
        result = subprocess.run(
            f"bash {PLANKA_SKILL} {args}",
            shell=True, capture_output=True, text=True,
            cwd=PLANKA_SKILL.parent, timeout=30, env=env,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"[error: {e}]"


# ============================================================================
# Template
# ============================================================================

PLAN_TEMPLATE = """\
# Project: {title}

**Status:** draft
**Created:** {date}
**Updated:** {date}
**Origin:** <!-- What prompted this project -->

---

## Vision

<!-- What is this project, in one paragraph? Why does it matter? -->

### Success Criteria

- [ ] <!-- Specific, measurable outcome -->
- [ ] <!-- Another outcome -->
- [ ] <!-- Another outcome -->

---

## Scope

### In Scope

- <!-- What we're doing -->

### Out of Scope

- <!-- What we're explicitly NOT doing -->

### Existing Assets

- <!-- What already exists that we can build on -->

---

## Audience

<!-- Who is this for? What do they want? Where will they find it? What action do we want them to take? -->

| Question | Answer |
|----------|--------|
| **Primary audience** | <!-- e.g., end users, internal team, customers --> |
| **What they want** | <!-- e.g., a tool, a world, entertainment --> |
| **Where they find it** | <!-- e.g., website, app, email, social feed --> |
| **Desired action** | <!-- e.g., download, subscribe, share, pay --> |
| **Secondary audience** | <!-- e.g., other creators, press --> |

---

## Deliverables

### <!-- Deliverable 1 Name -->

- **Format:** <!-- dimensions, file type, word count, platform specs -->
- **Created by:** <!-- who -->
- **Location:** <!-- file path, platform, URL -->
- **Dependencies:** <!-- what must exist first -->
- **Approval:** <!-- yes/no — does this need review? -->

<!-- Repeat for each deliverable -->

---

## Dependencies & Blockers

| Dependency | Type | Status | Owner |
|------------|------|--------|-------|
| <!-- what's needed --> | <!-- skill / credential / human / data --> | <!-- ready / blocked / unknown --> | <!-- who --> |

---

## Execution Plan

### Phase 1: <!-- Name -->

**Effort:** <!-- estimate in hours/days -->
**Produces:** <!-- tangible output -->
**Parallelizable:** <!-- yes/no — can other work happen simultaneously? -->

1. <!-- Step -->
2. <!-- Step -->
3. <!-- Step -->

**Checkpoint:** <!-- What do we review before moving to Phase 2? -->

### Phase 2: <!-- Name -->

**Effort:** <!-- estimate -->
**Produces:** <!-- output -->

1. <!-- Step -->
2. <!-- Step -->

<!-- Repeat for each phase -->

### First Action

<!-- The very first concrete thing to do when planning ends. Not a phase — a single action. -->

---

## Decisions Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| 1 | <!-- what was decided --> | <!-- why --> | {date} |

---

## Cards

<!-- Cards to create on Planka boards. Use the format below for automated card creation. -->
<!-- CARD: board=main | list=backlog | labels=agent | title=Card Title -->
<!-- DESC: Description of the card that will be created -->

### Phase 1 Cards

<!-- CARD: board=main | list=backlog | labels=agent | title=Example Card -->
<!-- DESC: Example description for this card -->

### Phase 2 Cards

<!-- CARD: board=main | list=backlog | labels=agent | title=Example Card -->
<!-- DESC: Example description for this card -->

---

## Notes

<!-- Running notes, observations, open questions gathered during the interview. -->

---

*Plan created {date}*
"""


# ============================================================================
# Commands
# ============================================================================

def cmd_new(args):
    """Create a new plan from template."""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    slug = slugify(args.name)
    path = PLANS_DIR / f"{slug}.md"

    if path.exists() and not args.force:
        print(f"Plan already exists: {path}")
        print("Use --force to overwrite.")
        return 1

    # Build a display title from the name
    title = args.name.replace('-', ' ').replace('_', ' ').title()
    date = datetime.now().strftime('%Y-%m-%d')

    content = PLAN_TEMPLATE.format(title=title, date=date)
    path.write_text(content, encoding='utf-8')

    print(f"Plan created: {path}")
    print(f"  Title: {title}")
    print(f"  Status: draft")
    print()
    print("Begin the interview. Fill in the sections as answers emerge.")
    return 0


def cmd_list(args):
    """List existing plans."""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    plans = sorted(PLANS_DIR.glob("*.md"))
    if not plans:
        print("No plans found in /workspace/project_plans/")
        return 0

    print(f"=== Project Plans ({len(plans)}) ===")
    print()

    for p in plans:
        text = p.read_text(encoding='utf-8')

        # Extract status
        status_match = re.search(r'\*\*Status:\*\*\s*(\w+)', text)
        status = status_match.group(1) if status_match else 'unknown'

        # Extract title
        title_match = re.search(r'^# Project:\s*(.+)', text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else p.stem

        # Extract created date
        created_match = re.search(r'\*\*Created:\*\*\s*(\S+)', text)
        created = created_match.group(1) if created_match else '?'

        # Filter by status if requested
        if args.status and status.lower() != args.status.lower():
            continue

        # Count cards
        card_count = len(re.findall(r'<!-- CARD:', text))

        # Count completed success criteria
        total_criteria = len(re.findall(r'- \[[ x]\]', text))
        done_criteria = len(re.findall(r'- \[x\]', text))

        status_icon = {
            'draft': '📝', 'active': '🔥', 'completed': '✅', 'abandoned': '💀'
        }.get(status.lower(), '❓')

        print(f"  {status_icon} {p.stem}")
        print(f"     {title} | {status} | created {created}")
        print(f"     {card_count} cards defined | {done_criteria}/{total_criteria} criteria met")
        print()

    return 0


def cmd_summary(args):
    """Print a summary of a plan."""
    path = plan_path(args.name)
    if not path.exists():
        print(f"Plan not found: {args.name}")
        print(f"  Expected at: {path}")
        return 1

    text = path.read_text(encoding='utf-8')

    # Extract key sections
    print(f"=== Plan: {path.stem} ===")
    print(f"  File: {path}")
    print()

    # Status
    status_match = re.search(r'\*\*Status:\*\*\s*(\w+)', text)
    print(f"  Status: {status_match.group(1) if status_match else 'unknown'}")

    # Created/Updated
    created_match = re.search(r'\*\*Created:\*\*\s*(\S+)', text)
    updated_match = re.search(r'\*\*Updated:\*\*\s*(\S+)', text)
    if created_match:
        print(f"  Created: {created_match.group(1)}")
    if updated_match:
        print(f"  Updated: {updated_match.group(1)}")

    # Vision (first paragraph after ## Vision)
    vision_match = re.search(
        r'## Vision\s*\n\s*\n(.+?)(?=\n\s*\n|\n###)',
        text, re.DOTALL
    )
    if vision_match:
        vision = vision_match.group(1).strip()
        if not vision.startswith('<!--'):
            print(f"\n  Vision: {vision[:300]}{'...' if len(vision) > 300 else ''}")

    # Success criteria
    criteria = re.findall(r'- \[([ x])\]\s*(.+)', text)
    if criteria:
        print(f"\n  Success Criteria ({sum(1 for c, _ in criteria if c == 'x')}/{len(criteria)} met):")
        for check, item in criteria:
            if not item.strip().startswith('<!--'):
                icon = '✅' if check == 'x' else '⬡'
                print(f"    {icon} {item.strip()}")

    # Deliverables count
    deliverables = re.findall(r'### (?!Phase|<!-- )(.+)', text)
    deliverable_names = [
        d.strip() for d in deliverables
        if not d.strip().startswith('<!--')
        and d.strip() not in ('In Scope', 'Out of Scope', 'Existing Assets',
                               'Success Criteria', 'First Action', 'Notes')
        and 'Cards' not in d
    ]
    if deliverable_names:
        print(f"\n  Deliverables ({len(deliverable_names)}):")
        for d in deliverable_names:
            print(f"    • {d}")

    # Cards
    cards = parse_cards(text)
    if cards:
        print(f"\n  Cards ({len(cards)}):")
        for card in cards:
            print(f"    [{card['board']}/{card['list']}] {card['title']}")

    # Phases
    phases = re.findall(r'### Phase (\d+):\s*(.+)', text)
    if phases:
        print(f"\n  Execution Phases ({len(phases)}):")
        for num, name in phases:
            if not name.strip().startswith('<!--'):
                print(f"    {num}. {name.strip()}")

    # First action
    first_match = re.search(
        r'### First Action\s*\n\s*\n(.+?)(?=\n\s*\n|\n---|\n##)',
        text, re.DOTALL
    )
    if first_match:
        first = first_match.group(1).strip()
        if not first.startswith('<!--'):
            print(f"\n  First Action: {first[:200]}")

    print()
    return 0


def parse_cards(text: str) -> list:
    """Parse CARD/DESC comment pairs from plan text."""
    cards = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        card_match = re.match(
            r'<!-- CARD:\s*(.+?)\s*-->',
            line
        )
        if card_match:
            # Parse card attributes
            attrs_str = card_match.group(1)
            attrs = {}
            for pair in attrs_str.split('|'):
                pair = pair.strip()
                if '=' in pair:
                    key, _, val = pair.partition('=')
                    attrs[key.strip()] = val.strip()

            # Look for DESC on next line
            desc = ""
            if i + 1 < len(lines):
                desc_match = re.match(
                    r'<!-- DESC:\s*(.+?)\s*-->',
                    lines[i + 1].strip()
                )
                if desc_match:
                    desc = desc_match.group(1)
                    i += 1

            cards.append({
                'board': attrs.get('board', 'main'),
                'list': attrs.get('list', 'backlog'),
                'labels': attrs.get('labels', ''),
                'title': attrs.get('title', 'Untitled'),
                'description': desc,
            })
        i += 1
    return cards


def cmd_cards(args):
    """Create Planka cards from a plan."""
    path = plan_path(args.name)
    if not path.exists():
        print(f"Plan not found: {args.name}")
        return 1

    text = path.read_text(encoding='utf-8')
    cards = parse_cards(text)

    if not cards:
        print("No cards found in plan.")
        print("Cards must use the format:")
        print('  <!-- CARD: board=main | list=backlog | labels=agent | title=Card Title -->')
        print('  <!-- DESC: Description of the card -->')
        return 1

    # Override board/list if specified on command line
    override_board = args.board
    override_list = args.list

    print(f"=== Cards from: {path.stem} ===")
    print(f"  Found {len(cards)} cards")
    if override_board:
        print(f"  Override board: {override_board}")
    if override_list:
        print(f"  Override list: {override_list}")
    print()

    env = load_env()

    for i, card in enumerate(cards, 1):
        board = override_board or card['board']
        list_name = override_list or card['list']
        title = card['title']
        desc = card['description']
        labels = card['labels']

        print(f"  [{i}/{len(cards)}] {title}")
        print(f"    Board: {board} | List: {list_name}")
        if labels:
            print(f"    Labels: {labels}")
        if desc:
            print(f"    Desc: {desc[:100]}{'...' if len(desc) > 100 else ''}")

        if args.dry_run:
            print("    → DRY RUN (not created)")
        else:
            cmd = f'create --board {board} --title "{title}" --list "{list_name}"'
            if desc:
                # Escape quotes in description
                safe_desc = desc.replace('"', '\\"')
                cmd += f' --description "{safe_desc}"'
            if labels:
                cmd += f' --labels "{labels}"'
            result = run_planka(cmd, env=env)
            if 'Error' in result:
                print(f"    → FAILED: {result}")
            else:
                # Extract card ID
                id_match = re.search(r'ID:\s*(\S+)', result)
                card_id = id_match.group(1) if id_match else '?'
                print(f"    → Created: {card_id}")
        print()

    if args.dry_run:
        print(f"Dry run complete. {len(cards)} cards would be created.")
        print("Remove --dry-run to create them.")
    else:
        print(f"Done. {len(cards)} cards created.")

    return 0


def cmd_status(args):
    """Update the status of a plan."""
    path = plan_path(args.name)
    if not path.exists():
        print(f"Plan not found: {args.name}")
        return 1

    valid_statuses = ['draft', 'active', 'completed', 'abandoned']
    if args.new_status not in valid_statuses:
        print(f"Invalid status: {args.new_status}")
        print(f"Valid: {', '.join(valid_statuses)}")
        return 1

    text = path.read_text(encoding='utf-8')
    today = datetime.now().strftime('%Y-%m-%d')

    # Update status
    text = re.sub(
        r'(\*\*Status:\*\*)\s*\w+',
        f'\\1 {args.new_status}',
        text
    )

    # Update "Updated" date
    text = re.sub(
        r'(\*\*Updated:\*\*)\s*\S+',
        f'\\1 {today}',
        text
    )

    path.write_text(text, encoding='utf-8')
    print(f"Plan '{path.stem}' → status: {args.new_status}")
    print(f"  Updated: {today}")
    return 0


def cmd_update_header(args):
    """Update the 'Updated' timestamp in a plan."""
    path = plan_path(args.name)
    if not path.exists():
        print(f"Plan not found: {args.name}")
        return 1

    text = path.read_text(encoding='utf-8')
    today = datetime.now().strftime('%Y-%m-%d')

    text = re.sub(
        r'(\*\*Updated:\*\*)\s*\S+',
        f'\\1 {today}',
        text
    )

    path.write_text(text, encoding='utf-8')
    print(f"Plan '{path.stem}' updated: {today}")
    return 0


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Project Planning — from concept to actionable spec"
    )
    sub = parser.add_subparsers(dest='command')

    # new
    p_new = sub.add_parser('new', help='Create a new plan')
    p_new.add_argument('name', help='Plan name (will be slugified for filename)')
    p_new.add_argument('--force', action='store_true', help='Overwrite existing plan')

    # list
    p_list = sub.add_parser('list', help='List existing plans')
    p_list.add_argument('--status', help='Filter by status')

    # summary
    p_summary = sub.add_parser('summary', help='Show plan summary')
    p_summary.add_argument('name', help='Plan name')

    # cards
    p_cards = sub.add_parser('cards', help='Create Planka cards from plan')
    p_cards.add_argument('name', help='Plan name')
    p_cards.add_argument('--board', help='Override board for all cards')
    p_cards.add_argument('--list', help='Override list for all cards')
    p_cards.add_argument('--dry-run', action='store_true', help='Preview without creating')

    # status
    p_status = sub.add_parser('status', help='Update plan status')
    p_status.add_argument('name', help='Plan name')
    p_status.add_argument('new_status', help='New status (draft/active/completed/abandoned)')

    # update-header
    p_update = sub.add_parser('update-header', help='Update the Updated timestamp')
    p_update.add_argument('name', help='Plan name')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        'new': cmd_new,
        'list': cmd_list,
        'summary': cmd_summary,
        'cards': cmd_cards,
        'status': cmd_status,
        'update-header': cmd_update_header,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
