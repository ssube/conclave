#!/usr/bin/env python3
"""ComfyUI Queue Manager — session tracking, job inspection, output downloading."""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "localhost")
COMFYUI_PORT = os.environ.get("COMFYUI_PORT", "8188")
SESSIONS_DIR = Path(os.environ.get("COMFYUI_SESSIONS_DIR", "/workspace/outputs/sessions"))
DEFAULT_OUTPUT_DIR = Path(os.environ.get("COMFYUI_OUTPUT_DIR", "/workspace/outputs"))

# Use HTTPS when hostname contains a dot (remote server)
SCHEME = "https" if "." in COMFYUI_HOST else "http"
BASE_URL = f"{SCHEME}://{COMFYUI_HOST}" if "." in COMFYUI_HOST else f"{SCHEME}://{COMFYUI_HOST}:{COMFYUI_PORT}"

CURRENT_SESSION_FILE = SESSIONS_DIR / ".current"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(path: str, params: Optional[dict] = None) -> dict:
    """GET request to ComfyUI API."""
    url = f"{BASE_URL}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{qs}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        print(f"Is ComfyUI running at {BASE_URL}?", file=sys.stderr)
        sys.exit(1)


def api_post(path: str, data: dict) -> Optional[dict]:
    """POST request to ComfyUI API."""
    url = f"{BASE_URL}{path}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def download_file(filename: str, subfolder: str, file_type: str, output_path: str) -> bool:
    """Download a file from ComfyUI /view endpoint."""
    params = {"filename": filename, "type": file_type}
    if subfolder:
        params["subfolder"] = subfolder
    qs = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/view?{qs}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.read())
            return True
    except Exception as e:
        print(f"  Download failed: {e}", file=sys.stderr)
        return False


def format_timestamp(ts_ms: Optional[int]) -> str:
    """Format millisecond timestamp to human-readable."""
    if not ts_ms:
        return "—"
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(start_ms: Optional[int], end_ms: Optional[int]) -> str:
    """Format duration from start/end timestamps."""
    if not start_ms or not end_ms:
        return "—"
    secs = (end_ms - start_ms) / 1000
    if secs < 60:
        return f"{secs:.1f}s"
    mins = int(secs // 60)
    remaining = secs % 60
    return f"{mins}m {remaining:.0f}s"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def get_current_session_path() -> Optional[Path]:
    """Get path to current session file."""
    if CURRENT_SESSION_FILE.exists():
        return Path(CURRENT_SESSION_FILE.read_text().strip())
    return None


def set_current_session(path: Path):
    """Set the current session file pointer."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_SESSION_FILE.write_text(str(path))


def load_session(path: Path) -> dict:
    """Load a session file."""
    if path.exists():
        return json.loads(path.read_text())
    return {"id": "", "created": "", "name": "", "jobs": []}


def save_session(path: Path, session: dict):
    """Save a session file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, indent=2))


def get_or_create_session() -> tuple[Path, dict]:
    """Get current session or create a default one."""
    path = get_current_session_path()
    if path and path.exists():
        return path, load_session(path)

    # Auto-create a default session
    now = datetime.now()
    session_id = now.strftime("%Y%m%d-%H%M%S")
    name = "default"
    path = SESSIONS_DIR / f"{session_id}-{name}.json"
    session = {
        "id": session_id,
        "created": now.isoformat(),
        "name": name,
        "jobs": []
    }
    save_session(path, session)
    set_current_session(path)
    return path, session


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_jobs(args):
    """List jobs with optional filtering."""
    params = {
        "limit": args.limit,
        "sort_order": "desc",
        "sort_by": "created_at",
    }
    if args.status:
        params["status"] = args.status

    # If --session, filter to session prompt IDs
    session_ids = set()
    if args.session:
        path = get_current_session_path()
        if not path or not path.exists():
            print("No active session. Use 'new-session' first.")
            return
        session = load_session(path)
        session_ids = {j["prompt_id"] for j in session["jobs"]}
        if not session_ids:
            print(f"Session '{session['name']}' has no tracked jobs.")
            return
        # Fetch more than needed since we'll filter client-side
        params["limit"] = max(args.limit * 3, 100)

    data = api_get("/api/jobs", params)
    jobs = data.get("jobs", [])
    pagination = data.get("pagination", {})

    if session_ids:
        jobs = [j for j in jobs if j["id"] in session_ids][:args.limit]

    if not jobs:
        print("No jobs found.")
        return

    # Header
    label = f"Session '{load_session(get_current_session_path())['name']}'" if args.session else "All"
    status_label = f" [{args.status}]" if args.status else ""
    print(f"=== {label} Jobs{status_label} ({pagination.get('total', len(jobs))} total) ===\n")

    for job in jobs:
        status = job["status"].upper()
        status_icon = {"COMPLETED": "✅", "FAILED": "❌", "IN_PROGRESS": "⏳", "PENDING": "⏸️", "CANCELLED": "🚫"}.get(status, "❓")
        duration = format_duration(job.get("execution_start_time"), job.get("execution_end_time"))
        created = format_timestamp(job.get("create_time"))
        preview = job.get("preview_output", {})
        preview_name = preview.get("filename", "") if preview else ""

        print(f"{status_icon} {job['id'][:12]}  {status:<12} {duration:>8}  {created}  {preview_name}")

    if not args.session and pagination.get("has_more"):
        print(f"\n  ... {pagination['total'] - len(jobs)} more (use --limit to see more)")


def cmd_job(args):
    """Show detailed info for a single job."""
    data = api_get(f"/api/jobs/{args.prompt_id}")

    if "error" in data:
        print(f"Job not found: {args.prompt_id}")
        return

    print(f"=== Job: {data['id']} ===\n")
    print(f"Status:    {data['status'].upper()}")
    print(f"Created:   {format_timestamp(data.get('create_time'))}")
    print(f"Started:   {format_timestamp(data.get('execution_start_time'))}")
    print(f"Finished:  {format_timestamp(data.get('execution_end_time'))}")
    print(f"Duration:  {format_duration(data.get('execution_start_time'), data.get('execution_end_time'))}")
    print(f"Outputs:   {data.get('outputs_count', 0)}")

    # Show outputs
    outputs = data.get("outputs", {})
    if outputs:
        print("\nOutput files:")
        for node_id, node_out in outputs.items():
            for media_type in ("images", "gifs", "video", "audio"):
                for item in node_out.get(media_type, []):
                    if isinstance(item, dict) and item.get("filename"):
                        print(f"  [{node_id}] {item['filename']}  (type={item.get('type', '?')}, subfolder={item.get('subfolder', '')})")

    # Show errors
    error = data.get("execution_error")
    if error:
        print(f"\n{'='*40}")
        print(f"ERROR in node {error.get('node_id')} ({error.get('node_type', '?')}):")
        print(f"  {error.get('exception_type', '?')}: {error.get('exception_message', '?')}")
        traceback_lines = error.get("traceback", [])
        if traceback_lines:
            print("\nTraceback:")
            for line in traceback_lines[-5:]:  # Last 5 frames
                print(f"  {line.rstrip()}")

    # Show workflow info (prompt text if available)
    workflow = data.get("workflow", {})
    prompt = workflow.get("prompt", {})
    if prompt:
        # Try to find the positive prompt text
        for node_id, node in prompt.items():
            inputs = node.get("inputs", {})
            if node.get("class_type") in ("CLIPTextEncode", "FluxTextEncode"):
                text = inputs.get("text", "")
                if text and len(text) > 10:
                    print(f"\nPrompt text (node {node_id}):")
                    print(f"  {text[:200]}{'...' if len(text) > 200 else ''}")
                    break


def cmd_download(args):
    """Download outputs from a specific job."""
    data = api_get(f"/api/jobs/{args.prompt_id}")

    if "error" in data:
        print(f"Job not found: {args.prompt_id}")
        return

    if data["status"] != "completed":
        print(f"Job is {data['status']}, not completed. Cannot download.")
        return

    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR / "downloads" / args.prompt_id[:12]
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = data.get("outputs", {})
    downloaded = 0

    for node_id, node_out in outputs.items():
        for media_type in ("images", "gifs", "video", "audio"):
            for item in node_out.get(media_type, []):
                if not isinstance(item, dict) or not item.get("filename"):
                    continue

                filename = item["filename"]
                subfolder = item.get("subfolder", "")
                file_type = item.get("type", "output")
                dest = output_dir / filename

                if dest.exists() and not args.force:
                    print(f"  Skip (exists): {filename}")
                    continue

                print(f"  Downloading: {filename} → {dest}")
                if download_file(filename, subfolder, file_type, str(dest)):
                    downloaded += 1
                    size = dest.stat().st_size
                    print(f"    ✅ {size / 1024:.0f} KB")

    print(f"\nDownloaded {downloaded} file(s) to {output_dir}")

    # Update session if tracked
    _mark_downloaded(args.prompt_id, str(output_dir))


def cmd_download_session(args):
    """Download all outputs from the current session."""
    path = get_current_session_path()
    if not path or not path.exists():
        print("No active session. Use 'new-session' first.")
        return

    session = load_session(path)
    if not session["jobs"]:
        print("Session has no tracked jobs.")
        return

    base_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR / "sessions" / session["id"]

    print(f"=== Downloading session: {session['name']} ({len(session['jobs'])} jobs) ===\n")

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    for job_entry in session["jobs"]:
        pid = job_entry["prompt_id"]
        note = job_entry.get("note", "")
        short_id = pid[:12]

        data = api_get(f"/api/jobs/{pid}")
        if "error" in data:
            print(f"  ❓ {short_id} — not found in ComfyUI history")
            total_failed += 1
            continue

        status = data["status"]
        if status != "completed":
            icon = {"failed": "❌", "in_progress": "⏳", "pending": "⏸️", "cancelled": "🚫"}.get(status, "❓")
            print(f"  {icon} {short_id} — {status}" + (f" ({note})" if note else ""))
            if status == "failed":
                total_failed += 1
            continue

        if job_entry.get("downloaded") and not args.force:
            print(f"  ⏭️  {short_id} — already downloaded" + (f" ({note})" if note else ""))
            total_skipped += 1
            continue

        # Create subfolder using note or short ID
        subfolder_name = note.replace(" ", "-").replace("/", "-")[:40] if note else short_id
        job_dir = base_dir / subfolder_name

        outputs = data.get("outputs", {})
        job_downloaded = 0

        for node_id, node_out in outputs.items():
            for media_type in ("images", "gifs", "video", "audio"):
                for item in node_out.get(media_type, []):
                    if not isinstance(item, dict) or not item.get("filename"):
                        continue

                    filename = item["filename"]
                    subfolder = item.get("subfolder", "")
                    file_type = item.get("type", "output")
                    dest = job_dir / filename

                    if dest.exists() and not args.force:
                        continue

                    if download_file(filename, subfolder, file_type, str(dest)):
                        job_downloaded += 1

        if job_downloaded > 0:
            print(f"  ✅ {short_id} — {job_downloaded} file(s) → {job_dir}" + (f" ({note})" if note else ""))
            total_downloaded += job_downloaded
            job_entry["downloaded"] = True
            job_entry["output_dir"] = str(job_dir)
        else:
            print(f"  ✅ {short_id} — no new files" + (f" ({note})" if note else ""))

    # Save updated session
    save_session(path, session)

    print(f"\nTotal: {total_downloaded} downloaded, {total_skipped} skipped, {total_failed} failed/pending")


def cmd_errors(args):
    """Show errors from failed jobs."""
    params = {"status": "failed", "limit": args.limit, "sort_order": "desc"}
    data = api_get("/api/jobs", params)
    jobs = data.get("jobs", [])

    # Filter to session if requested
    if args.session:
        path = get_current_session_path()
        if path and path.exists():
            session = load_session(path)
            session_ids = {j["prompt_id"] for j in session["jobs"]}
            jobs = [j for j in jobs if j["id"] in session_ids]

    if not jobs:
        print("No failed jobs found. 🎉")
        return

    print(f"=== Failed Jobs ({len(jobs)}) ===\n")

    for job in jobs:
        # Fetch full details for error info
        detail = api_get(f"/api/jobs/{job['id']}")
        error = detail.get("execution_error", {})
        created = format_timestamp(job.get("create_time"))

        print(f"❌ {job['id'][:12]}  {created}")
        if error:
            print(f"   Node: {error.get('node_id', '?')} ({error.get('node_type', '?')})")
            print(f"   {error.get('exception_type', '?')}: {error.get('exception_message', '').strip()}")
            traceback_lines = error.get("traceback", [])
            if traceback_lines and args.traceback:
                print("   Traceback:")
                for line in traceback_lines[-3:]:
                    print(f"     {line.rstrip()}")
        print()


def cmd_status(args):
    """Show live queue status and system stats."""
    queue = api_get("/queue")
    running = queue.get("queue_running", [])
    pending = queue.get("queue_pending", [])

    print("=== ComfyUI Queue Status ===\n")
    print(f"Running: {len(running)}")
    print(f"Pending: {len(pending)}")

    if running:
        print("\nCurrently running:")
        for item in running:
            pid = item[1] if len(item) > 1 else "?"
            print(f"  ⏳ {pid[:12]}...")

    if pending:
        print(f"\nPending ({len(pending)}):")
        for item in pending[:5]:
            pid = item[1] if len(item) > 1 else "?"
            print(f"  ⏸️  {pid[:12]}...")
        if len(pending) > 5:
            print(f"  ... and {len(pending) - 5} more")

    # System stats
    try:
        stats = api_get("/system_stats")
        devices = stats.get("devices", [])
        if devices:
            dev = devices[0]
            vram_total_gb = dev.get("vram_total", 0) / (1024**3)
            vram_free_gb = dev.get("vram_free", 0) / (1024**3)
            vram_used_gb = vram_total_gb - vram_free_gb
            vram_pct = (vram_used_gb / vram_total_gb * 100) if vram_total_gb > 0 else 0
            print(f"\nGPU: {dev.get('name', '?')}")
            print(f"VRAM: {vram_used_gb:.1f} / {vram_total_gb:.1f} GB ({vram_pct:.0f}% used)")
        system = stats.get("system", {})
        if system:
            print(f"ComfyUI: {system.get('comfyui_version', '?')}")
    except Exception:
        pass

    # Current session info
    path = get_current_session_path()
    if path and path.exists():
        session = load_session(path)
        completed = sum(1 for j in session["jobs"] if j.get("downloaded"))
        total = len(session["jobs"])
        print(f"\nSession: {session['name']} ({total} jobs, {completed} downloaded)")


def cmd_cancel(args):
    """Cancel/interrupt a job or clear the queue."""
    if args.all:
        api_post("/queue", {"clear": True})
        print("Queue cleared.")
    elif args.prompt_id:
        # Try to interrupt if running
        api_post("/interrupt", {"prompt_id": args.prompt_id})
        # Also try to delete from pending queue
        api_post("/queue", {"delete": [args.prompt_id]})
        print(f"Cancelled/interrupted: {args.prompt_id[:12]}...")
    else:
        print("Specify a prompt_id or use --all")


def cmd_clear_history(args):
    """Clear ComfyUI history."""
    if args.keep:
        # Fetch all, then delete older ones
        data = api_get("/api/jobs", {"status": "completed,failed,cancelled", "limit": 10000, "sort_order": "desc"})
        jobs = data.get("jobs", [])
        to_delete = [j["id"] for j in jobs[args.keep:]]
        if to_delete:
            api_post("/history", {"delete": to_delete})
            print(f"Deleted {len(to_delete)} old history entries (kept {args.keep})")
        else:
            print(f"Only {len(jobs)} entries, nothing to delete (keep={args.keep})")
    else:
        api_post("/history", {"clear": True})
        print("History cleared.")


def cmd_track(args):
    """Track a prompt ID in the current session."""
    path, session = get_or_create_session()

    # Check if already tracked
    if any(j["prompt_id"] == args.prompt_id for j in session["jobs"]):
        print(f"Already tracking: {args.prompt_id[:12]}...")
        return

    session["jobs"].append({
        "prompt_id": args.prompt_id,
        "queued_at": datetime.now().isoformat(),
        "note": args.note or "",
        "downloaded": False,
        "output_dir": None
    })

    save_session(path, session)
    print(f"Tracked: {args.prompt_id[:12]}..." + (f" ({args.note})" if args.note else ""))


def cmd_new_session(args):
    """Start a new session."""
    now = datetime.now()
    session_id = now.strftime("%Y%m%d-%H%M%S")
    name = args.name or "default"
    safe_name = name.replace(" ", "-").replace("/", "-")[:40]
    path = SESSIONS_DIR / f"{session_id}-{safe_name}.json"

    session = {
        "id": f"{session_id}-{safe_name}",
        "created": now.isoformat(),
        "name": name,
        "jobs": []
    }

    save_session(path, session)
    set_current_session(path)
    print(f"New session: {name}")
    print(f"File: {path}")


def cmd_sessions(args):
    """List available sessions."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SESSIONS_DIR.glob("*.json"), reverse=True)
    files = [f for f in files if f.name != ".current"]

    current_path = get_current_session_path()

    if not files:
        print("No sessions found.")
        return

    print("=== Sessions ===\n")
    for f in files[:args.limit]:
        session = load_session(f)
        is_current = "→ " if current_path and f == current_path else "  "
        n_jobs = len(session.get("jobs", []))
        n_downloaded = sum(1 for j in session.get("jobs", []) if j.get("downloaded"))
        print(f"{is_current}{session.get('name', '?'):<30} {n_jobs:>3} jobs ({n_downloaded} dl)  {session.get('created', '?')[:19]}")


def _mark_downloaded(prompt_id: str, output_dir: str):
    """Mark a job as downloaded in the current session."""
    path = get_current_session_path()
    if not path or not path.exists():
        return
    session = load_session(path)
    for job in session["jobs"]:
        if job["prompt_id"] == prompt_id:
            job["downloaded"] = True
            job["output_dir"] = output_dir
    save_session(path, session)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ComfyUI Queue Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # jobs
    p = sub.add_parser("jobs", help="List jobs")
    p.add_argument("--status", choices=["completed", "failed", "pending", "in_progress", "cancelled"])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--session", action="store_true", help="Filter to current session")
    p.set_defaults(func=cmd_jobs)

    # job (single)
    p = sub.add_parser("job", help="Show single job details")
    p.add_argument("prompt_id", help="Prompt ID")
    p.set_defaults(func=cmd_job)

    # download
    p = sub.add_parser("download", help="Download job outputs")
    p.add_argument("prompt_id", help="Prompt ID")
    p.add_argument("--output-dir", "-o", help="Output directory")
    p.add_argument("--force", action="store_true", help="Re-download existing files")
    p.set_defaults(func=cmd_download)

    # download-session
    p = sub.add_parser("download-session", help="Download all session outputs")
    p.add_argument("--output-dir", "-o", help="Base output directory")
    p.add_argument("--force", action="store_true", help="Re-download existing files")
    p.set_defaults(func=cmd_download_session)

    # errors
    p = sub.add_parser("errors", help="Show failed job errors")
    p.add_argument("--session", action="store_true", help="Filter to current session")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--traceback", action="store_true", help="Show tracebacks")
    p.set_defaults(func=cmd_errors)

    # status
    p = sub.add_parser("status", help="Queue status + system info")
    p.set_defaults(func=cmd_status)

    # cancel
    p = sub.add_parser("cancel", help="Cancel/interrupt a job")
    p.add_argument("prompt_id", nargs="?", help="Prompt ID to cancel")
    p.add_argument("--all", action="store_true", help="Clear entire queue")
    p.set_defaults(func=cmd_cancel)

    # clear-history
    p = sub.add_parser("clear-history", help="Clear ComfyUI history")
    p.add_argument("--keep", type=int, help="Keep N most recent entries")
    p.set_defaults(func=cmd_clear_history)

    # track
    p = sub.add_parser("track", help="Track a prompt ID in current session")
    p.add_argument("prompt_id", help="Prompt ID to track")
    p.add_argument("--note", "-n", help="Description note")
    p.set_defaults(func=cmd_track)

    # new-session
    p = sub.add_parser("new-session", help="Start a new session")
    p.add_argument("--name", "-n", help="Session name")
    p.set_defaults(func=cmd_new_session)

    # sessions
    p = sub.add_parser("sessions", help="List sessions")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_sessions)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
