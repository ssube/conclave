#!/usr/bin/env python3
"""
Generate Image Skill
Generate images via ComfyUI API with support for multiple base models and LoRAs
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
import websocket  # websocket-client package
from datetime import datetime
from pathlib import Path

# Configuration
COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "localhost")
COMFYUI_PORT = os.environ.get("COMFYUI_PORT", "8188")
COMFYUI_HTTPS = os.environ.get("COMFYUI_HTTPS", "false").lower() == "true"
COMFYUI_OUTPUT_DIR = os.environ.get("COMFYUI_OUTPUT_DIR", ".")

# Auto-detect HTTPS if port is 443
if COMFYUI_PORT == "443":
    COMFYUI_HTTPS = True

protocol = "https" if COMFYUI_HTTPS else "http"
ws_protocol = "wss" if COMFYUI_HTTPS else "ws"
BASE_URL = f"{protocol}://{COMFYUI_HOST}:{COMFYUI_PORT}"
WS_URL = f"{ws_protocol}://{COMFYUI_HOST}:{COMFYUI_PORT}"
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WORKFLOWS_DIR = SCRIPT_DIR / "workflows"

# Named workflow files — pre-built workflows where only the prompt changes
# Each entry is a path, or a dict with "path" and "prompt_node" / "prompt_field"
# to override the default node 6 / "text" injection target.
#
# Additional optional keys:
#   "lora_nodes"  — list of node IDs containing LoraLoader nodes (for LoRA swapping)
#   "size_node"   — node ID of the EmptyLatentImage (for resolution changes)
#   "image_node"  — node ID of LoadImage (for image-to-X workflows)
#   "description"  — human-readable description for --list-workflows
NAMED_WORKFLOWS = {
    # ── Flux Text-to-Image ────────────────────────────────────────────────
    "flux-lora": {
        "path": WORKFLOWS_DIR / "flux_lora_text_to_image.json",
        "prompt_node": "112",
        "prompt_field": "string",
        "lora_nodes": ["96", "200"],
        "size_node": "27",
        "description": "Flux text-to-image with 2 LoRA slots. 35 steps, euler/sgm_uniform, guidance 4.",
    },
    # ── Wan 2.2 Image-to-Video ────────────────────────────────────────────
    "wan22-i2v": {
        "path": WORKFLOWS_DIR / "wan22_upscale_image_to_video.json",
        "prompt_node": "118",
        "prompt_field": "text_a",
        "image_node": "62",
        "description": "Wan 2.2 upscale image-to-video. Auto-caption + custom prompt, 20-step two-pass, 2x upscale, RIFE 2x → 32fps.",
    },
}

# Generate a client ID for websocket connection
CLIENT_ID = str(uuid.uuid4())

# Default sizes for each base model
DEFAULT_SIZES = {
    "flux": (832, 1216),
}


def api_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Make an API request to ComfyUI."""
    url = f"{BASE_URL}{endpoint}"

    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode() if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.URLError as e:
        print(f"Error connecting to ComfyUI at {url}: {e}", file=sys.stderr)
        sys.exit(1)


def load_workflow(base: str) -> dict:
    """Load a workflow template for the specified base model."""
    workflow_file = WORKFLOWS_DIR / f"{base}-base.json"

    if not workflow_file.exists():
        print(f"Error: Workflow template not found: {workflow_file}", file=sys.stderr)
        sys.exit(1)

    with open(workflow_file) as f:
        return json.load(f)


def randomize_seeds(workflow: dict) -> dict:
    """Randomize all seed values in a workflow.
    
    Finds all nodes with 'seed' in their inputs (KSampler, etc.)
    and sets them to random values.
    """
    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})
        if "seed" in inputs:
            # Generate a large random seed (up to 2^48 to match ComfyUI range)
            inputs["seed"] = random.randint(0, 2**48 - 1)
    return workflow


def load_named_workflow(name: str, prompt: str) -> dict:
    """Load a named workflow and inject only the prompt text.

    Named workflows are pre-built ComfyUI workflows (with model, LoRA,
    sampler, etc. already configured) where only the positive prompt
    needs to be changed.

    Workflow entries can be a plain Path (prompt injected into node '6',
    field 'text') or a dict with 'path', 'prompt_node', and 'prompt_field'
    to target a different node/field.
    """
    entry = NAMED_WORKFLOWS.get(name)
    if not entry:
        available = ", ".join(NAMED_WORKFLOWS.keys())
        print(f"Error: Unknown named workflow '{name}'. Available: {available}", file=sys.stderr)
        sys.exit(1)

    # Resolve entry format — plain path or dict with overrides
    if isinstance(entry, dict):
        workflow_path = entry["path"]
        prompt_node = entry.get("prompt_node", "6")
        prompt_field = entry.get("prompt_field", "text")
    else:
        workflow_path = entry
        prompt_node = "6"
        prompt_field = "text"

    if not workflow_path.exists():
        print(f"Error: Workflow file not found: {workflow_path}", file=sys.stderr)
        sys.exit(1)

    with open(workflow_path) as f:
        workflow = json.load(f)

    # Inject prompt into the target node (skip for promptless workflows like upscale, wd14)
    if prompt_node and prompt_node in workflow and prompt:
        workflow[prompt_node]["inputs"][prompt_field] = prompt
    elif prompt_node and prompt_node not in workflow and prompt:
        print(f"Warning: Workflow has no node '{prompt_node}' for prompt (ignored)", file=sys.stderr)

    return workflow


def build_workflow(prompt: str, base: str, loras: list, width: int, height: int) -> dict:
    """Build a workflow with the given parameters."""
    workflow = load_workflow(base)

    # Find and update relevant nodes
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})

        # Update prompt text
        if class_type in ["CLIPTextEncode", "CLIPTextEncodeFlux"]:
            if "text" in inputs or "clip_l" in inputs:
                if "positive" in node.get("_meta", {}).get("title", "").lower() or \
                   node_id in ["6", "positive"]:
                    if "text" in inputs:
                        inputs["text"] = prompt
                    if "clip_l" in inputs:
                        inputs["clip_l"] = prompt
                        inputs["t5xxl"] = prompt

        # Update empty latent size
        if class_type == "EmptyLatentImage":
            inputs["width"] = width
            inputs["height"] = height

        # Update empty SD3 latent
        if class_type == "EmptySD3LatentImage":
            inputs["width"] = width
            inputs["height"] = height

    # Add LoRA nodes if specified
    if loras:
        workflow = add_loras_to_workflow(workflow, loras, base)

    return workflow


def add_loras_to_workflow(workflow: dict, loras: list, base: str) -> dict:
    """Add LoRA loader nodes to the workflow."""
    # Find the model loader node
    model_loader_id = None
    clip_source_id = None
    clip_output_index = 1  # Default for CheckpointLoaderSimple

    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        if class_type in ["CheckpointLoaderSimple", "UNETLoader"]:
            model_loader_id = node_id
        if class_type in ["CheckpointLoaderSimple", "DualCLIPLoader"]:
            clip_source_id = node_id
            if class_type == "DualCLIPLoader":
                clip_output_index = 0

    if not model_loader_id:
        print("Warning: Could not find model loader node for LoRA insertion", file=sys.stderr)
        return workflow

    # Find nodes that reference the model loader
    model_consumers = []
    clip_consumers = []

    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})
        for input_name, input_value in inputs.items():
            if isinstance(input_value, list) and len(input_value) == 2:
                if input_value[0] == model_loader_id:
                    if input_value[1] == 0:  # MODEL output
                        model_consumers.append((node_id, input_name))
                    elif input_value[1] == 1:  # CLIP output
                        clip_consumers.append((node_id, input_name))
                # Only check separate CLIP source if it's different from model loader
                elif clip_source_id and clip_source_id != model_loader_id and input_value[0] == clip_source_id:
                    if input_value[1] == 0:  # CLIP output
                        clip_consumers.append((node_id, input_name))

    # Create LoRA chain
    prev_model_source = [model_loader_id, 0]
    prev_clip_source = [clip_source_id or model_loader_id, clip_output_index]

    for i, lora_spec in enumerate(loras):
        parts = lora_spec.split(":")
        lora_name = parts[0]
        lora_weight = float(parts[1]) if len(parts) > 1 else 1.0

        lora_node_id = f"lora_{i}"

        workflow[lora_node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": f"{lora_name}.safetensors",
                "strength_model": lora_weight,
                "strength_clip": lora_weight,
                "model": prev_model_source,
                "clip": prev_clip_source,
            },
            "_meta": {"title": f"LoRA: {lora_name}"}
        }

        prev_model_source = [lora_node_id, 0]
        prev_clip_source = [lora_node_id, 1]

    # Update consumers to use the last LoRA output
    for node_id, input_name in model_consumers:
        workflow[node_id]["inputs"][input_name] = prev_model_source

    for node_id, input_name in clip_consumers:
        workflow[node_id]["inputs"][input_name] = prev_clip_source

    return workflow


def queue_prompt(workflow: dict, prompt_id: str) -> None:
    """Queue a prompt with a specific prompt ID."""
    payload = {
        "prompt": workflow,
        "client_id": CLIENT_ID,
        "prompt_id": prompt_id
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/prompt", data=data, 
                                  headers={"Content-Type": "application/json"})
    
    try:
        urllib.request.urlopen(req)
    except urllib.error.URLError as e:
        print(f"Error queuing prompt: {e}", file=sys.stderr)
        sys.exit(1)


def wait_for_completion_ws(ws: websocket.WebSocket, prompt_id: str, timeout: int = 900) -> dict:
    """Wait for a prompt to complete via websocket and return the history.
    
    Based on ComfyUI example: monitors websocket for execution completion message,
    then fetches the final history.
    
    Args:
        ws: Connected WebSocket
        prompt_id: ComfyUI prompt ID to wait for
        timeout: Maximum seconds to wait (default 900 = 15 minutes, enough for Wan video)
    """
    import time as _time
    start = _time.time()
    ws.settimeout(60)  # 60s recv timeout — will retry on each timeout
    
    last_node = None
    while True:
        elapsed = _time.time() - start
        if elapsed > timeout:
            print(f"WARNING: Generation timed out after {timeout}s (last node: {last_node})", file=sys.stderr)
            # Try to fetch history anyway — it may have completed
            break
        
        try:
            out = ws.recv()
        except websocket.WebSocketTimeoutException:
            # Recv timed out — check if we've exceeded total timeout, otherwise retry
            print(f"  ⏳ Still generating... ({int(elapsed)}s, last node: {last_node})")
            continue
        except (websocket.WebSocketConnectionClosedException, ConnectionError) as e:
            print(f"WARNING: WebSocket disconnected after {int(elapsed)}s: {e}", file=sys.stderr)
            # Connection dropped — try to fetch history, generation may have completed server-side
            break
            
        if isinstance(out, str):
            message = json.loads(out)
            msg_type = message.get('type', '')
            
            if msg_type == 'executing':
                data = message.get('data', {})
                last_node = data.get('node')
                # When node is None and prompt_id matches, execution is done
                if last_node is None and data.get('prompt_id') == prompt_id:
                    break
            elif msg_type == 'execution_error':
                data = message.get('data', {})
                print(f"ERROR: Execution error on node {data.get('node_id')}: {data.get('exception_message', 'unknown')}", file=sys.stderr)
                sys.exit(1)
        # Binary messages are preview images; ignore them
    
    # Fetch the final history
    req = urllib.request.Request(f"{BASE_URL}/history/{prompt_id}")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            history = json.loads(response.read())
            if prompt_id not in history:
                print(f"ERROR: Prompt {prompt_id} not found in history (generation may have failed)", file=sys.stderr)
                sys.exit(1)
            return history[prompt_id]
    except urllib.error.URLError as e:
        print(f"Error fetching history: {e}", file=sys.stderr)
        sys.exit(1)


def download_image(filename: str, subfolder: str, folder_type: str, output_path: str):
    """Download a generated image from ComfyUI."""
    # Properly encode URL parameters
    params = {
        "filename": filename,
        "subfolder": subfolder,
        "type": folder_type
    }
    url_values = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/view?{url_values}"

    try:
        with urllib.request.urlopen(url) as response:
            with open(output_path, "wb") as f:
                f.write(response.read())
        print(f"Image saved to: {output_path}")
    except urllib.error.URLError as e:
        print(f"Error downloading image: {e}", file=sys.stderr)
        print(f"URL: {url}", file=sys.stderr)


def upload_image(filepath: str, image_type: str = "input", overwrite: bool = True) -> str:
    """Upload an image to ComfyUI's input directory.

    Args:
        filepath: Path to the local image file
        image_type: "input" (default) or "temp"
        overwrite: Whether to overwrite existing files

    Returns:
        The filename on the server (use this in LoadImage/LoadImageMask nodes)
    """
    import mimetypes
    filepath = os.path.abspath(filepath)
    filename = os.path.basename(filepath)
    content_type = mimetypes.guess_type(filepath)[0] or "image/png"

    # Build multipart form data
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
    body = b""

    # image field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: {content_type}\r\n\r\n".encode()
    with open(filepath, "rb") as f:
        body += f.read()
    body += b"\r\n"

    # type field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="type"\r\n\r\n{image_type}\r\n'.encode()

    # overwrite field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="overwrite"\r\n\r\n{"true" if overwrite else "false"}\r\n'.encode()

    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE_URL}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        server_name = result.get("name", filename)
        print(f"  Uploaded: {filename} → {server_name}")
        return server_name


def apply_overrides(workflow: dict, overrides: list) -> dict:
    """Apply --set overrides to a workflow.
    
    Each override is a string like 'node_id.inputs.field=value'.
    Values are auto-cast to int/float where possible.
    """
    for override in overrides:
        path, _, value = override.partition("=")
        if not path or not _:
            print(f"Warning: Invalid --set format '{override}', expected 'node.inputs.field=value'", file=sys.stderr)
            continue
        parts = path.split(".")
        obj = workflow
        try:
            for part in parts[:-1]:
                obj = obj[part]
            key = parts[-1]
            # Auto-cast numeric values
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass
            obj[key] = value
        except (KeyError, TypeError) as e:
            print(f"Warning: Could not apply --set '{override}': {e}", file=sys.stderr)
    return workflow


def download_output(history: dict, output_path: str, workflow: dict = None) -> bool:
    """Download the final image or video output from a completed history entry.
    
    Checks both 'images' (SaveImage etc.) and 'gifs' (VHS_VideoCombine) keys.
    
    Output selection priority:
    1. Nodes tagged with _meta.output: true in the workflow (explicit target)
    2. Videos over images (if workflow produces both, video is typically final)
    3. 'output' type over 'temp' type (SaveImage vs PreviewImage)
    
    Args:
        history: ComfyUI history entry for a completed prompt
        output_path: Local path to save the downloaded file
        workflow: Original workflow dict (optional, used for _meta.output tags)
    
    Returns True if a file was downloaded, False otherwise.
    """
    outputs = history.get("outputs", {})

    # Build set of tagged output node IDs from workflow _meta
    tagged_nodes = set()
    if workflow:
        for node_id, node in workflow.items():
            if node.get("_meta", {}).get("output"):
                tagged_nodes.add(node_id)

    # Collect all candidates with (priority, node_id, data, kind)
    candidates = []

    for node_id, node_output in outputs.items():
        is_tagged = node_id in tagged_nodes

        for gif in node_output.get("gifs", []):
            if gif.get("filename"):
                # Videos: priority 0 if tagged, 1 if untagged
                priority = 0 if is_tagged else 1
                candidates.append((priority, node_id, gif, "video"))

        for img in node_output.get("images", []):
            if img.get("filename"):
                # Images: tagged=2, output-type=3, temp-type=4
                if is_tagged:
                    priority = 2
                elif img.get("type") == "output":
                    priority = 3
                else:
                    priority = 4
                candidates.append((priority, node_id, img, "image"))

    candidates.sort(key=lambda x: x[0])

    for priority, node_id, data, kind in candidates:
        if kind == "video":
            params = {k: v for k, v in data.items()
                      if k in ("filename", "type", "subfolder", "format", "frame_rate")}
            url_values = urllib.parse.urlencode(params)
            url = f"{BASE_URL}/view?{url_values}"
            try:
                with urllib.request.urlopen(url, timeout=120) as response:
                    with open(output_path, "wb") as f:
                        f.write(response.read())
                print(f"Video saved to: {output_path}")
                return True
            except urllib.error.URLError as e:
                print(f"Error downloading video from node {node_id}: {e}", file=sys.stderr)
        else:
            filename = data.get("filename")
            subfolder = data.get("subfolder", "")
            folder_type = data.get("type", "output")
            download_image(filename, subfolder, folder_type, output_path)
            return True

    return False


def cmd_generate(args):
    """Generate an image."""
    # Check if using a named workflow
    if args.workflow:
        print(f"Loading named workflow: {args.workflow}")
        workflow = load_named_workflow(args.workflow, args.prompt)
    else:
        # Parse size
        if args.size:
            width, height = map(int, args.size.split("x"))
        else:
            width, height = DEFAULT_SIZES.get(args.base, (1024, 1024))

        # Build workflow
        print(f"Building workflow for {args.base}...")
        workflow = build_workflow(
            prompt=args.prompt,
            base=args.base,
            loras=args.lora or [],
            width=width,
            height=height,
        )

    # Upload and inject input image (for image-to-X and inpainting workflows)
    if hasattr(args, 'image') and args.image:
        if not os.path.exists(args.image):
            print(f"Error: Image not found: {args.image}", file=sys.stderr)
            sys.exit(1)
        print(f"Uploading input image: {args.image}")
        server_name = upload_image(args.image)
        # Find image_node from named workflow config, or default to node "1"
        wf_config = NAMED_WORKFLOWS.get(args.workflow, {}) if args.workflow else {}
        if isinstance(wf_config, dict):
            image_node = wf_config.get("image_node", "1")
        else:
            image_node = "1"
        if image_node in workflow:
            workflow[image_node]["inputs"]["image"] = server_name
            print(f"  Set node {image_node} image → {server_name}")

    # Upload and inject mask image (for inpainting workflows)
    if hasattr(args, 'mask') and args.mask:
        if not os.path.exists(args.mask):
            print(f"Error: Mask not found: {args.mask}", file=sys.stderr)
            sys.exit(1)
        print(f"Uploading mask: {args.mask}")
        server_name = upload_image(args.mask)
        # Mask node is typically "2" (LoadImageMask) in inpainting workflows
        mask_node = "2"
        if mask_node in workflow:
            workflow[mask_node]["inputs"]["image"] = server_name
            # Force channel to "red" — works with any grayscale mask.
            # "alpha" only works if the mask has a real alpha channel.
            workflow[mask_node]["inputs"]["channel"] = "red"
            print(f"  Set node {mask_node} mask → {server_name} (channel: red)")

    # Apply --set overrides (works with both named and built workflows)
    if args.set:
        workflow = apply_overrides(workflow, args.set)

    # Randomize seeds to get different results each time
    workflow = randomize_seeds(workflow)

    # Connect to websocket
    print("Connecting to ComfyUI...")
    ws = websocket.WebSocket()
    ws_url = f"{WS_URL}/ws?clientId={CLIENT_ID}"
    try:
        ws.connect(ws_url)
    except Exception as e:
        print(f"Error connecting to websocket: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate and queue the prompt
    prompt_id = str(uuid.uuid4())
    print(f"Queuing prompt {prompt_id}...")

    # Pre-validate to catch silent errors (e.g. missing LoRAs, bad node references)
    # Include client_id so ComfyUI routes websocket messages to us
    validate_payload = json.dumps({
        "prompt": workflow,
        "client_id": CLIENT_ID,
    }).encode()
    validate_req = urllib.request.Request(
        f"{BASE_URL}/prompt", data=validate_payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(validate_req) as resp:
            result = json.loads(resp.read())
            node_errors = result.get("node_errors", {})
            if node_errors:
                print("ERROR: Workflow validation failed:", file=sys.stderr)
                for nid, err_info in node_errors.items():
                    for err in err_info.get("errors", []):
                        ct = err_info.get("class_type", "?")
                        print(f"  Node {nid} ({ct}): {err.get('message')} — {err.get('details', '')}", file=sys.stderr)
                sys.exit(1)
            # The validate call also queued it, so we don't need to queue again
            prompt_id = result.get("prompt_id", prompt_id)
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        node_errors = body.get("node_errors", {})
        if node_errors:
            print("ERROR: Workflow validation failed:", file=sys.stderr)
            for nid, err_info in node_errors.items():
                for err in err_info.get("errors", []):
                    ct = err_info.get("class_type", "?")
                    print(f"  Node {nid} ({ct}): {err.get('message')} — {err.get('details', '')}", file=sys.stderr)
            sys.exit(1)
        raise

    print(f"Prompt queued: {prompt_id}")

    # Auto-track in comfyui-queue session if available
    try:
        from pathlib import Path
        sessions_dir = Path(os.environ.get("COMFYUI_SESSIONS_DIR", "/workspace/outputs/sessions"))
        current_file = sessions_dir / ".current"
        if current_file.exists():
            session_path = Path(current_file.read_text().strip())
            if session_path.exists():
                session = json.loads(session_path.read_text())
                if not any(j["prompt_id"] == prompt_id for j in session.get("jobs", [])):
                    from datetime import datetime
                    note = args.prompt[:60] if hasattr(args, 'prompt') and args.prompt else ""
                    session.setdefault("jobs", []).append({
                        "prompt_id": prompt_id,
                        "queued_at": datetime.now().isoformat(),
                        "note": note,
                        "downloaded": False,
                        "output_dir": None
                    })
                    session_path.write_text(json.dumps(session, indent=2))
                    print(f"Tracked in session: {session.get('name', '?')}")
    except Exception:
        pass  # Session tracking is best-effort

    # Wait for completion via websocket
    print("Waiting for generation...")
    try:
        history = wait_for_completion_ws(ws, prompt_id)
    finally:
        ws.close()

    # Download output
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = os.path.join(COMFYUI_OUTPUT_DIR, f"{timestamp}.png")

    if not download_output(history, output_path, workflow=workflow):
        print("No output images or videos found", file=sys.stderr)


def cmd_queue(args):
    """Show queue status."""
    queue_info = api_request("/queue")

    running = queue_info.get("queue_running", [])
    pending = queue_info.get("queue_pending", [])

    print("=== ComfyUI Queue Status ===")
    print(f"Running: {len(running)}")
    print(f"Pending: {len(pending)}")

    if running:
        print("\nCurrently running:")
        for item in running:
            print(f"  - {item[1]} (started: {item[0]})")

    if pending:
        print("\nPending:")
        for item in pending[:5]:
            print(f"  - {item[1]}")
        if len(pending) > 5:
            print(f"  ... and {len(pending) - 5} more")


def cmd_history(args):
    """Show history for a prompt."""
    history = api_request(f"/history/{args.prompt_id}")

    if args.prompt_id not in history:
        print(f"No history found for prompt: {args.prompt_id}")
        return

    prompt_history = history[args.prompt_id]
    status = prompt_history.get("status", {})

    print(f"=== Prompt History: {args.prompt_id} ===")
    print(f"Status: {status.get('status_str', 'unknown')}")
    print(f"Completed: {status.get('completed', False)}")

    outputs = prompt_history.get("outputs", {})
    if outputs:
        print("\nOutputs:")
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            for img in images:
                print(f"  - {img.get('filename')} ({img.get('type')})")


def main():
    parser = argparse.ArgumentParser(description="Generate Image via ComfyUI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate an image")
    gen_parser.add_argument("--prompt", required=True, help="Text prompt for generation")
    gen_parser.add_argument("--workflow", help="Use a named workflow (e.g. 'flux-lora'). "
                           "Only the prompt is changed; all other settings are preset.")
    gen_parser.add_argument("--base", default="flux", choices=["flux"],
                           help="Base model to use (ignored when --workflow is set)")
    gen_parser.add_argument("--lora", action="append",
                           help="LoRA to apply (ignored when --workflow is set)")
    gen_parser.add_argument("--size", help="Image size (ignored when --workflow is set)")
    gen_parser.add_argument("--set", action="append",
                           help="Override workflow values: 'node.inputs.field=value' (repeatable)")
    gen_parser.add_argument("--image", help="Input image path (uploaded to ComfyUI, set on image_node)")
    gen_parser.add_argument("--mask", help="Mask image path (uploaded to ComfyUI, set on mask node 2)")
    gen_parser.add_argument("--output", help="Output file path")
    gen_parser.set_defaults(func=cmd_generate)

    # Queue command
    queue_parser = subparsers.add_parser("queue", help="Check queue status")
    queue_parser.set_defaults(func=cmd_queue)

    # History command
    hist_parser = subparsers.add_parser("history", help="Get prompt history")
    hist_parser.add_argument("prompt_id", help="Prompt ID to query")
    hist_parser.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
