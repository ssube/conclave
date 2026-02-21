#!/usr/bin/env python3
"""
Skill Initializer — Scaffold a new skill directory.

Usage:
    init_skill.py <skill-name> --path <target-directory>

Examples:
    init_skill.py my-new-skill --path ./skills
    init_skill.py api-client --path ./skills

Based on the aivena skill-creator by Espen Nilsen, adapted for our conventions.
"""

import sys
from pathlib import Path

SKILL_TEMPLATE = """---
name: {skill_name}
description: >-
  TODO: Complete description of what this skill does and when to use it.
  Include specific trigger scenarios. This text determines when the agent loads the skill.
---

# {skill_title}

TODO: Instructions for using this skill.

## Usage

```bash
# Example usage
bash {{baseDir}}/example.sh
```

## Environment Variables

List any required environment variables here, or remove this section.

## Troubleshooting

Common issues and solutions, or remove this section.
"""


def title_case(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split("-"))


def init_skill(skill_name: str, path: str) -> bool:
    skill_dir = Path(path).resolve() / skill_name

    if skill_dir.exists():
        print(f"Error: {skill_dir} already exists")
        return False

    try:
        skill_dir.mkdir(parents=True)
        print(f"Created {skill_dir}/")

        # SKILL.md
        content = SKILL_TEMPLATE.format(
            skill_name=skill_name,
            skill_title=title_case(skill_name),
        )
        (skill_dir / "SKILL.md").write_text(content)
        print("  Created SKILL.md")

        print(f"\nSkill '{skill_name}' scaffolded at {skill_dir}")
        print("Next: edit SKILL.md, add scripts/references/assets as needed.")
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    if len(sys.argv) < 4 or sys.argv[2] != "--path":
        print("Usage: init_skill.py <skill-name> --path <target-directory>")
        print("\nExamples:")
        print("  init_skill.py my-skill --path ./skills")
        print("  init_skill.py api-client --path ./skills")
        sys.exit(1)

    skill_name = sys.argv[1]
    path = sys.argv[3]

    # Validate name
    import re
    if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', skill_name) or '--' in skill_name:
        print(f"Invalid skill name '{skill_name}'.")
        print("Must be kebab-case: lowercase a-z, 0-9, hyphens. No leading/trailing/consecutive hyphens.")
        sys.exit(1)

    if len(skill_name) > 64:
        print(f"Skill name too long ({len(skill_name)} chars). Max 64.")
        sys.exit(1)

    sys.exit(0 if init_skill(skill_name, path) else 1)


if __name__ == "__main__":
    main()
