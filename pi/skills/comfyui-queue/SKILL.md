---
name: comfyui-queue
description: >-
  Manage ComfyUI jobs — track session jobs, download outputs, check errors,
  cancel jobs, and monitor queue. Use when checking job status, downloading
  completed outputs, inspecting failed jobs, or managing the generation queue.
---

# ComfyUI Queue Manager

Track, inspect, and manage ComfyUI generation jobs. Provides session-level tracking,
bulk output downloading, error inspection, and queue control.

Works alongside `generate-image` — that skill builds and queues workflows, this one
manages the jobs after they're queued.

## Session Tracking

Every time `generate-image` queues a prompt, this skill can track the prompt ID in a
session file. At the end of a session (or at any time), you can check status of all
jobs, download their outputs, or inspect failures — without needing to remember
individual prompt IDs.

Session files are stored at `/workspace/outputs/sessions/`.

## Actions

### List jobs (with filtering)

```bash
python3 {baseDir}/queue_manager.py jobs [--status completed|failed|pending|in_progress] [--limit 20] [--session]
```

`--session` filters to only jobs from the current session file.

### Check a specific job

```bash
python3 {baseDir}/queue_manager.py job <prompt_id>
```

Shows full details: status, duration, outputs, errors, workflow info.

### Download outputs from a completed job

```bash
python3 {baseDir}/queue_manager.py download <prompt_id> [--output-dir /workspace/outputs/batch-name]
```

Downloads all output images/videos to a predictable folder structure:
`/workspace/outputs/{dir}/{filename}` or auto-organized by session.

### Download all session outputs

```bash
python3 {baseDir}/queue_manager.py download-session [--output-dir /workspace/outputs/my-batch]
```

Downloads outputs from all completed jobs in the current session.
Skips already-downloaded files. Creates `{output-dir}/{prompt_id_short}/` subfolders.

### Check errors on failed jobs

```bash
python3 {baseDir}/queue_manager.py errors [--session] [--limit 10]
```

Shows error message, exception type, failing node, and traceback for failed jobs.

### Queue status (live)

```bash
python3 {baseDir}/queue_manager.py status
```

Shows running/pending counts, current job progress, VRAM usage.

### Cancel/interrupt a job

```bash
python3 {baseDir}/queue_manager.py cancel <prompt_id>
python3 {baseDir}/queue_manager.py cancel --all
```

### Clear history

```bash
python3 {baseDir}/queue_manager.py clear-history [--keep 50]
```

### Track a prompt ID in the current session

```bash
python3 {baseDir}/queue_manager.py track <prompt_id> [--note "flux landscape sunset"]
```

### Start a new session

```bash
python3 {baseDir}/queue_manager.py new-session [--name "landscape-showcase"]
```

### List sessions

```bash
python3 {baseDir}/queue_manager.py sessions [--limit 10]
```

## Environment

- `COMFYUI_HOST` — ComfyUI server hostname (from `.env`)
- `COMFYUI_PORT` — ComfyUI server port (default: 8188)

## Session File Format

Session files are JSON at `/workspace/outputs/sessions/{timestamp}-{name}.json`:

```json
{
  "id": "20260216-173000-landscape",
  "created": "2026-02-16T17:30:00",
  "name": "landscape-showcase",
  "jobs": [
    {
      "prompt_id": "abc123...",
      "queued_at": "2026-02-16T17:30:05",
      "note": "flux landscape sunset",
      "downloaded": false,
      "output_dir": null
    }
  ]
}
```

## Examples

```bash
# Start a showcase session
python3 {baseDir}/queue_manager.py new-session --name "landscape-showcase"

# ... queue several images via generate-image ...
# Track them:
python3 {baseDir}/queue_manager.py track abc123 --note "mountain sunrise"
python3 {baseDir}/queue_manager.py track def456 --note "coastal cliffs"

# Check progress
python3 {baseDir}/queue_manager.py jobs --session

# After all complete, download everything
python3 {baseDir}/queue_manager.py download-session --output-dir /workspace/outputs/showcase/landscapes

# Check if any failed
python3 {baseDir}/queue_manager.py errors --session

# Browse recent jobs across all sessions
python3 {baseDir}/queue_manager.py jobs --limit 20 --status completed
```
