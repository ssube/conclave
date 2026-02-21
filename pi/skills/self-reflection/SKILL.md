---
name: self-reflection
description: >-
  Self-reflection and continuous learning — review context, identify gaps, refine approaches. Use when reflecting on recent work, identifying improvement areas, reviewing alignment, or centering before a creative session.
---

# Self-Reflection Skill

A structured self-review process. Walk through what you've built, what you've learned,
what you've forgotten, and what needs attention.

This is not a status check. This is deeper work — examining accumulated context,
identifying gaps, and producing actionable insights.

## When to Reflect

- After completing a significant body of work
- When the project direction feels unclear
- When asked to reflect or review
- During quiet periods when no urgent tasks demand attention
- At least once per week as part of continuous improvement

## Usage

### Full reflection

```bash
python3 {baseDir}/self_reflection.py --full
```

Performs all phases:
1. **Gather** — Pull notes, tasks, catalog, recent activity
2. **Review** — Examine accumulated knowledge and context
3. **Identify** — Find gaps, missing skills, workflow friction
4. **Dream** — Draw inspiration and brainstorm improvements
5. **Act** — Produce reflection notes and improvement ideas
6. **Record** — Save the reflection to ChromaDB and optionally to disk

### Quick reflection (gather + identify only)

```bash
python3 {baseDir}/self_reflection.py --quick
```

### Specific phases

```bash
python3 {baseDir}/self_reflection.py --phase gather
python3 {baseDir}/self_reflection.py --phase review
python3 {baseDir}/self_reflection.py --phase dream
```

### Save reflection output to file

```bash
python3 {baseDir}/self_reflection.py --full --output /path/to/reflections/
```

## What Gets Reviewed

### Context Sources
- **ChromaDB notes** — What has been learned, observed, decided
- **Planka tasks** — Recently completed work, upcoming priorities, blocked items
- **Data catalog** — Item inventory, quality distribution
- **Available skills** — Skill inventory and coverage

### Gap Analysis
- **Missing skills** — What tools would have made recent work easier?
- **Workflow friction** — Where do processes break down or feel clumsy?
- **Knowledge gaps** — What don't you know that you should?
- **Consistency** — Is communication staying true to project goals?

## Outputs

Reflections produce:
- **Reflection note** in ChromaDB `notes` collection (category: `reflection`)
- **Skill ideas** documented for future implementation
- **Workflow observations** for process improvement
- **Saved file** if `--output` is specified

## Environment Variables

- `CHROMADB_HOST`: ChromaDB server host (default: `localhost`)
- `CHROMADB_PORT`: ChromaDB server port (default: `8000`)
- `PLANKA_API_URL`: Planka instance URL
- `PLANKA_API_TOKEN`: Planka authentication token
