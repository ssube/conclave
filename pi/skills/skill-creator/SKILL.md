---
name: skill-creator
description: Create and validate skills for Pi. Use when building a new skill, improving an existing skill's SKILL.md, scaffolding a skill directory, or reviewing skill quality. Covers structure, frontmatter, progressive disclosure, script/reference/asset patterns, and project conventions.
---

# Skill Creator

Guide for creating effective skills. Merged from the Agent Skills specification and the aivena skill-creator by Espen Nilsen.

## Quick Reference

```bash
# Scaffold a new skill
python3 {baseDir}/scripts/init_skill.py <skill-name> --path <target-directory>

# Example: create a new skill in your skills directory
python3 {baseDir}/scripts/init_skill.py my-new-skill --path ./skills
```

## Core Principles

### 1. Context Is a Public Good

The context window is shared with the system prompt, conversation history, other skills, and the user's request. Default assumption: Claude is already very smart. Only add context Claude doesn't already have.

**Challenge each piece:** "Does Claude really need this?" and "Does this justify its token cost?"

Prefer concise examples over verbose explanations.

### 2. Progressive Disclosure

Skills use three-level loading:

1. **Metadata** (name + description) — Always in context. ~100 words. This is the trigger.
2. **SKILL.md body** — Loaded on-demand when the skill triggers. Keep under 500 lines.
3. **Bundled resources** — Loaded only when specifically needed. Unlimited size.

If SKILL.md approaches 500 lines, split content into `references/` files and link to them.

### 3. Degrees of Freedom

Match specificity to fragility:

- **High freedom** (text instructions): Multiple approaches valid, context-dependent decisions
- **Medium freedom** (pseudocode/scripts with parameters): Preferred pattern exists, some variation OK
- **Low freedom** (exact scripts, few parameters): Operations fragile, consistency critical

A narrow bridge needs guardrails. An open field allows many routes.

## Skill Structure

```
skill-name/
├── SKILL.md              # Required: frontmatter + instructions
├── scripts/              # Executable code (Python/Bash)
│   └── process.sh
├── references/           # Detailed docs loaded on-demand
│   └── api-reference.md
└── assets/               # Files used in output (templates, images)
    └── template.json
```

### SKILL.md Format

```markdown
---
name: my-skill
description: What this skill does and when to use it. Be specific — this is the trigger.
---

# My Skill

Instructions for using the skill and its bundled resources.
```

### Frontmatter Rules

| Field | Required | Rules |
|-------|----------|-------|
| `name` | Yes | 1-64 chars. Lowercase a-z, 0-9, hyphens. Must match parent directory. |
| `description` | Yes | Max 1024 chars. What it does AND when to use it. |
| `license` | No | License name or reference. |
| `compatibility` | No | Environment requirements. |

**Name:** `kebab-case` only. No leading/trailing hyphens, no consecutive hyphens.
Valid: `pdf-processing`, `web-browse`. Invalid: `PDF-Processing`, `-pdf`.

**Description:** This is the primary trigger. Include both what and when.

Good: `Post images using Playwright browser automation. Use when uploading images, posting to a gallery, or publishing visual content.`

Bad: `Helps with posting.`

### Conventions

- **Directories** use `kebab-case`: `{platform}-post`, `{platform}-analytics`, `{verb}-{noun}`
- **Platform skills** split into `-post` (write) and `-analytics` (read)
- **Bash files** use `kebab-case.sh`, Python files use `snake_case.py`
- **Environment variables** follow `{PLATFORM}_{CREDENTIAL_TYPE}`
- **Relative paths** use `{baseDir}` placeholder (resolved by the agent at runtime)

### Resource Patterns

**scripts/** — Executable code run directly. Include when:
- The same code would be rewritten repeatedly
- Deterministic reliability is needed
- Operations are complex enough to warrant a script

**references/** — Documentation loaded on-demand. Include when:
- Information is too detailed for SKILL.md
- Content is only needed for specific use cases
- Files are large (include grep patterns in SKILL.md for discovery)

**assets/** — Files used in output, not loaded into context. Include when:
- Templates, images, boilerplate needed in final output
- Files shouldn't consume context window

**Rule:** Information lives in ONE place. SKILL.md or references, not both.

## Writing SKILL.md

### Structure Patterns

Choose based on the skill's purpose:

**Workflow-Based** (sequential processes):
```markdown
# Skill Name

Processing involves these steps:
1. Analyze input (run analyze.py)
2. Transform data (run transform.py)
3. Validate output (run validate.py)

## Step 1: Analyze
...
```

**Task-Based** (tool collections):
```markdown
# Skill Name

## Quick Start
...

## Action: Post
...

## Action: Analytics
...
```

**Reference/Guidelines** (standards):
```markdown
# Skill Name

## Guidelines
...

## Specifications
...
```

### Conditional Workflows

For branching logic:
```markdown
1. Determine the type:
   **Creating new?** → Follow "Creation workflow"
   **Editing existing?** → Follow "Editing workflow"
```

### Progressive Disclosure Patterns

**Pattern: High-level guide with references**
```markdown
## Advanced Features
- **Form filling**: See [FORMS.md](references/forms.md) for complete guide
- **API reference**: See [REFERENCE.md](references/api.md) for all methods
```

**Pattern: Domain-specific organization**
```
skill-name/
├── SKILL.md (overview + navigation)
└── references/
    ├── platform-a.md
    ├── platform-b.md
    └── platform-c.md
```

When user asks about Platform A, only `platform-a.md` loads.

## Creation Process

### Step 1: Understand the Skill

Gather concrete examples of how the skill will be used:
- What inputs does it take?
- What outputs does it produce?
- What triggers it?
- What variations exist?

### Step 2: Plan Resources

For each example, consider:
1. What code would be rewritten each time? → `scripts/`
2. What reference docs are needed? → `references/`
3. What templates or assets are needed? → `assets/`

### Step 3: Scaffold

```bash
python3 {baseDir}/scripts/init_skill.py <skill-name> --path <target-directory>
```

### Step 4: Implement

1. Write the scripts, references, and assets identified in Step 2
2. Test scripts by actually running them
3. Write SKILL.md — keep it concise, link to references for detail
4. Delete any example files you don't need

### Step 5: Validate

Check against these criteria:
- [ ] Name matches directory, kebab-case, ≤64 chars
- [ ] Description is specific about what AND when (≤1024 chars)
- [ ] SKILL.md is under 500 lines
- [ ] All referenced files exist
- [ ] Scripts are tested and working
- [ ] No duplicate information between SKILL.md and references
- [ ] Relative paths use `{baseDir}` placeholder
- [ ] Environment variables documented if required

### Step 6: Iterate

Use the skill on real tasks, notice struggles, improve. The best skills are refined through use.

## Making Skills Effective

LLMs respond to the same persuasion principles as humans. See [persuasion.md](references/persuasion.md) for the full guide. Key takeaway: Authority + Commitment + Scarcity are the most effective principles for discipline-enforcing skills.

**Quick rules:**
- Use imperative language for critical steps: "YOU MUST verify" not "consider verifying"
- Require announcements for accountability: "Announce: 'I'm using [skill]'"
- Add immediate verification: "IMMEDIATELY after X, verify Y"
- Set bright-line rules: "Posting without verification = broken links. Every time."

## What NOT to Include

- README.md (SKILL.md IS the readme)
- INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, CHANGELOG.md
- User-facing documentation (skills are for the agent, not humans)
- Setup/testing procedures for the skill itself
- Any auxiliary context about the creation process
