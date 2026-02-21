#!/usr/bin/env python3
"""
Async Image Job Manager

Queue image generation jobs, track them in SQLite, and harvest completed results
from ComfyUI's history API. Eliminates blocking waits during generation.

Usage:
    # Queue a job (returns immediately with prompt_id)
    python3 async_jobs.py queue --workflow flux-lora --prompt "..." --lora "path/to/lora.safetensors" --output /path/to/output.png

    # Check status of all pending jobs
    python3 async_jobs.py status

    # Harvest completed jobs (download images)
    python3 async_jobs.py harvest

    # Queue + harvest loop (queue one, check all)
    python3 async_jobs.py harvest --download-dir /workspace/outputs/showcase-xyz/
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

# Server config — matches generate_image.py pattern
COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "localhost")
COMFYUI_PORT = os.environ.get("COMFYUI_PORT", "8188")
COMFYUI_HTTPS = os.environ.get("COMFYUI_HTTPS", "false").lower() == "true"
if COMFYUI_PORT == "443":
    COMFYUI_HTTPS = True
_protocol = "https" if COMFYUI_HTTPS else "http"
BASE_URL = f"{_protocol}://{COMFYUI_HOST}:{COMFYUI_PORT}"

DB_PATH = os.environ.get("SQLITE_DB_PATH", "./data/agent.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def comfy_request(path, data=None):
    """Make a request to ComfyUI API."""
    url = f"{BASE_URL}{path}"
    if data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(url)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI {e.code}: {body[:500]}") from e


WORKFLOW_MAP = {
    "flux-lora": "flux_lora_text_to_image.json",
    "wan22-i2v": "wan22_upscale_image_to_video.json",
}


def load_workflow(workflow_name):
    """Load a named workflow JSON."""
    workflow_dir = Path(__file__).parent / "workflows"
    filename = WORKFLOW_MAP.get(workflow_name, f"{workflow_name.replace('-', '_')}.json")
    workflow_file = workflow_dir / filename
    if not workflow_file.exists():
        raise FileNotFoundError(f"Workflow not found: {workflow_file}")
    with open(workflow_file) as f:
        return json.load(f)


def cmd_queue(args):
    """Queue a job on ComfyUI and record it in SQLite."""
    workflow = load_workflow(args.workflow)

    # Apply prompt to the workflow's text node
    # Find the positive prompt node (varies by workflow)
    prompt_applied = False
    for node_id, node in workflow.items():
        if node.get("class_type") in ("CLIPTextEncode", "FluxGuidance") and not prompt_applied:
            if "text" in node.get("inputs", {}):
                node["inputs"]["text"] = args.prompt
                prompt_applied = True

    # Apply --set overrides
    if args.set:
        for override in args.set:
            parts = override.split("=", 1)
            if len(parts) == 2:
                path_parts = parts[0].split(".")
                if len(path_parts) >= 2:
                    node_id = path_parts[0]
                    key_path = ".".join(path_parts[1:])
                    if node_id in workflow:
                        keys = key_path.split(".")
                        target = workflow[node_id]
                        for k in keys[:-1]:
                            target = target.setdefault(k, {})
                        # Try to convert to number
                        val = parts[1]
                        try:
                            val = float(val)
                            if val == int(val):
                                val = int(val)
                        except ValueError:
                            pass
                        target[keys[-1]] = val

    # Submit to ComfyUI
    import uuid
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}
    result = comfy_request("/prompt", data=payload)
    prompt_id = result.get("prompt_id", "unknown")

    # Record in SQLite
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO image_jobs 
           (prompt_id, workflow, prompt, lora_name, lora_strength, output_path, status, metadata)
           VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)""",
        (
            prompt_id,
            args.workflow,
            args.prompt,
            args.lora or "",
            args.strength or 0.85,
            args.output or "",
            json.dumps({"client_id": client_id, "sets": args.set or []}),
        ),
    )
    db.commit()
    db.close()

    print(f"Queued: {prompt_id}")
    print(f"Workflow: {args.workflow}")
    if args.output:
        print(f"Output: {args.output}")
    return prompt_id


def cmd_status(args):
    """Show status of all tracked jobs."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM image_jobs ORDER BY queued_at DESC LIMIT ?",
        (args.limit or 20,),
    ).fetchall()
    db.close()

    if not rows:
        print("No tracked jobs.")
        return

    # Also check ComfyUI queue
    try:
        queue = comfy_request("/queue")
        running = len(queue.get("queue_running", []))
        pending = len(queue.get("queue_pending", []))
        print(f"ComfyUI Queue: {running} running, {pending} pending\n")
    except Exception as e:
        print(f"ComfyUI unreachable: {e}\n")

    for row in rows:
        status_icon = {"queued": "⏳", "completed": "✅", "downloaded": "📥", "error": "❌"}.get(
            row["status"], "❓"
        )
        print(f"{status_icon} {row['prompt_id'][:12]}... [{row['status']}]")
        print(f"   Workflow: {row['workflow']} | Queued: {row['queued_at']}")
        if row["prompt"]:
            print(f"   Prompt: {row['prompt'][:80]}...")
        if row["output_path"]:
            print(f"   Output: {row['output_path']}")
        if row["error"]:
            print(f"   Error: {row['error']}")
        print()


def cmd_harvest(args):
    """Check ComfyUI history and download completed images."""
    db = get_db()
    pending = db.execute(
        "SELECT * FROM image_jobs WHERE status = 'queued'"
    ).fetchall()

    if not pending:
        print("No pending jobs to harvest.")
        db.close()
        return

    print(f"Checking {len(pending)} pending jobs...")

    # Fetch history
    try:
        history = comfy_request("/history?max_items=50")
    except Exception as e:
        print(f"Error fetching history: {e}")
        db.close()
        return

    downloaded = 0
    completed = 0

    for job in pending:
        pid = job["prompt_id"]
        if pid in history:
            info = history[pid]
            status = info.get("status", {}).get("status_str", "unknown")

            if status == "success":
                completed += 1
                # Find output images
                outputs = info.get("outputs", {})
                for node_id, node_out in outputs.items():
                    for img in node_out.get("images", []):
                        fname = img["filename"]
                        subfolder = img.get("subfolder", "")

                        # Determine output path
                        out_path = job["output_path"]
                        if not out_path and args.download_dir:
                            out_path = os.path.join(args.download_dir, fname)
                        elif not out_path:
                            out_path = os.path.join("/workspace/outputs", fname)

                        # Download
                        os.makedirs(os.path.dirname(out_path), exist_ok=True)
                        url = f"{BASE_URL}/view?filename={fname}&subfolder={subfolder}&type=output"
                        try:
                            urllib.request.urlretrieve(url, out_path)
                            print(f"  ✅ {pid[:12]}... → {out_path}")
                            downloaded += 1
                            db.execute(
                                "UPDATE image_jobs SET status='downloaded', completed_at=?, downloaded_at=? WHERE prompt_id=?",
                                (datetime.now().isoformat(), datetime.now().isoformat(), pid),
                            )
                        except Exception as e:
                            print(f"  ❌ Download failed for {pid[:12]}...: {e}")
                            db.execute(
                                "UPDATE image_jobs SET status='error', error=? WHERE prompt_id=?",
                                (str(e), pid),
                            )
                        break  # One image per job
                    break  # One output node

                if downloaded == 0:
                    # Completed but no images found
                    db.execute(
                        "UPDATE image_jobs SET status='completed', completed_at=? WHERE prompt_id=?",
                        (datetime.now().isoformat(), pid),
                    )

            elif status == "error":
                db.execute(
                    "UPDATE image_jobs SET status='error', error='ComfyUI error' WHERE prompt_id=?",
                    (pid,),
                )
                print(f"  ❌ {pid[:12]}... error in ComfyUI")

    db.commit()
    db.close()
    print(f"\nHarvested: {downloaded} downloaded, {completed} completed, {len(pending) - completed} still pending")


def cmd_queue_batch(args):
    """Queue N jobs with varied seeds for the same prompt."""
    import random

    results = []
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    print(f"🎲 Queuing {args.count} jobs ({args.workflow})")

    for i in range(args.count):
        seed = random.randint(1, 2**32 - 1)
        output_path = str(out_dir / f"{args.prefix}-{timestamp}-{i+1:02d}.png")

        # Create a modified args object for cmd_queue
        class QueueArgs:
            pass
        qa = QueueArgs()
        qa.workflow = args.workflow
        qa.prompt = args.prompt
        qa.lora = args.lora
        qa.strength = args.strength
        qa.output = output_path
        # Add seed override
        qa.set = list(args.set or [])
        qa.set.append(f"25.inputs.noise_seed={seed}")

        try:
            prompt_id = cmd_queue(qa)
            results.append({"prompt_id": prompt_id, "path": output_path, "seed": seed})
            print(f"  [{i+1}/{args.count}] {prompt_id} (seed: {seed})")
        except Exception as e:
            print(f"  [{i+1}/{args.count}] ❌ Failed: {e}")

    print(f"\n✅ {len(results)}/{args.count} jobs queued")
    print(f"   Use 'harvest --download-dir {args.output_dir}' when ready")


def cmd_wait(args):
    """Wait for all pending jobs to complete, then harvest."""
    import time as t

    timeout = args.timeout
    poll = args.poll
    start = t.time()

    while t.time() - start < timeout:
        db = get_db()
        pending = db.execute("SELECT COUNT(*) FROM image_jobs WHERE status = 'queued'").fetchone()[0]
        db.close()

        if pending == 0:
            print("✅ All jobs complete")
            break

        elapsed = int(t.time() - start)
        print(f"⏳ {pending} jobs pending... ({elapsed}s / {timeout}s)")
        t.sleep(poll)
    else:
        print(f"⚠️ Timeout after {timeout}s — some jobs may still be pending")

    # Harvest whatever is done
    cmd_harvest(args)


def main():
    parser = argparse.ArgumentParser(description="Async Image Job Manager")
    sub = parser.add_subparsers(dest="command")

    # Queue
    q = sub.add_parser("queue", help="Queue a generation job")
    q.add_argument("--workflow", required=True, help="Named workflow")
    q.add_argument("--prompt", required=True, help="Positive prompt text")
    q.add_argument("--lora", help="LoRA path")
    q.add_argument("--strength", type=float, default=0.85, help="LoRA strength")
    q.add_argument("--output", help="Output file path")
    q.add_argument("--set", action="append", help="Workflow overrides (node.key=value)")

    # Queue Batch
    qb = sub.add_parser("queue-batch", help="Queue N jobs with varied seeds")
    qb.add_argument("-n", "--count", type=int, default=4, help="Number of jobs")
    qb.add_argument("--workflow", required=True, help="Named workflow")
    qb.add_argument("--prompt", required=True, help="Text prompt")
    qb.add_argument("--lora", help="LoRA path")
    qb.add_argument("--strength", type=float, default=0.85, help="LoRA strength")
    qb.add_argument("--prefix", default="batch", help="Output filename prefix")
    qb.add_argument("--output-dir", default="/workspace/outputs", help="Output directory")
    qb.add_argument("--set", action="append", help="Workflow overrides")

    # Status
    s = sub.add_parser("status", help="Show job status")
    s.add_argument("--limit", type=int, default=20, help="Max jobs to show")

    # Harvest
    h = sub.add_parser("harvest", help="Download completed images")
    h.add_argument("--download-dir", help="Default download directory")

    # Wait (harvest with polling)
    w = sub.add_parser("wait", help="Wait for all pending jobs then harvest")
    w.add_argument("--timeout", type=int, default=600, help="Max wait seconds")
    w.add_argument("--poll", type=int, default=15, help="Poll interval seconds")
    w.add_argument("--download-dir", help="Default download directory")

    args = parser.parse_args()

    if args.command == "queue":
        cmd_queue(args)
    elif args.command == "queue-batch":
        cmd_queue_batch(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "harvest":
        cmd_harvest(args)
    elif args.command == "wait":
        cmd_wait(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
