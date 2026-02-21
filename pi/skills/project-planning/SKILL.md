---
name: project-planning
description: >-
  Interview-driven project planning — structured questioning to produce
  well-defined specs, then generate Planka cards. Use when planning a new
  project, breaking down a large initiative, defining requirements through
  structured questions, or creating a project spec with tasks.
---

# Project Planning Skill

Transform a concept into an actionable specification through structured
interview-style questioning. The output is a **Markdown plan document** and
optionally a set of **Planka cards** ready for the board.

## When to Use

- A concept needs to become actionable work
- A new project or content initiative needs scoping before execution
- Before starting a multi-phase effort

## Process

### The Interview

The interview has **seven phases**. Not every phase applies to every project —
skip what doesn't serve the work.

#### Phase 1: Vision
- What is the project in one sentence?
- What prompted this?
- What does success look like? Be specific.

#### Phase 2: Scope
- What concrete things will this project produce?
- What will it explicitly NOT do?
- What already exists that we can build on?
- What is the minimum viable version?

#### Phase 3: Audience
- Who is the primary audience?
- What do they want from this?
- Where will they encounter it?
- What action do we want them to take?

#### Phase 4: Deliverables
For each deliverable: what, format/specs, who creates it, where it lives,
dependencies, approval needed?

#### Phase 5: Dependencies & Blockers
- What skills/tools are required?
- What human actions are required?
- What information is missing?
- What are the risks?

#### Phase 6: Execution Plan
- Break work into phases — each phase produces something tangible
- Identify what can be parallelized
- Estimate effort for each phase
- Define checkpoints
- Identify the first concrete action

#### Phase 7: Cards
- Which Planka board and list?
- For each card: title, description, labels, dependencies

## Quick Mode

For small tasks that need tracking but not full planning:

```bash
python3 {baseDir}/plan.py new "fix-session-bug" --quick
```

Quick mode creates a lightweight plan with just: What, Why, Done-looks-like, First action.

## Usage

### Start a new plan

```bash
python3 {baseDir}/plan.py new "website-content-update"
```

Creates a template at the configured plans directory.

### List existing plans

```bash
python3 {baseDir}/plan.py list
```

### View a plan summary

```bash
python3 {baseDir}/plan.py summary "website-content-update"
```

### Generate Planka cards from a completed plan

```bash
python3 {baseDir}/plan.py cards "website-content-update" [--board main] [--list backlog] [--dry-run]
```

### Mark a plan as active/completed

```bash
python3 {baseDir}/plan.py status "website-content-update" active
```

## Environment Variables

- `PROJECT_PLANS_DIR`: Directory for plan files (default: `./project_plans`)
- `PLANKA_SKILL_PATH`: Path to planka.sh for card creation
- `PLANKA_API_URL`: Planka instance URL (for card creation)
- `PLANKA_API_TOKEN`: Planka authentication token

## Document Structure

Plans are Markdown files with sections for Vision, Scope, Audience, Deliverables,
Dependencies, Execution Plan, Decisions Log, and Cards.

Cards use a comment format for automated creation:

```markdown
<!-- CARD: board=main | list=backlog | labels=agent | title=Card Title -->
<!-- DESC: Description of the card -->
```
