#!/usr/bin/env python3
"""
ComfyUI Info Skill

Query the ComfyUI server for available models, LoRAs, VAEs,
workflows, samplers, and system status.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from fnmatch import fnmatch


# Server configuration — match generate-image pattern
COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "localhost")
COMFYUI_PORT = os.environ.get("COMFYUI_PORT", "8188")
COMFYUI_HTTPS = os.environ.get("COMFYUI_HTTPS", "false").lower() == "true"
if COMFYUI_PORT == "443":
    COMFYUI_HTTPS = True
_protocol = "https" if COMFYUI_HTTPS else "http"
BASE_URL = f"{_protocol}://{COMFYUI_HOST}:{COMFYUI_PORT}"

# Architecture path prefixes for filtering
ARCH_PATHS = {
    "flux": ["flux_1_d/", "flux_1_s/", "flux/"],
    "sdxl": ["sdxl/"],
    "pony": ["pony/"],
    "illustrious": ["illustrious/"],
    "sd1": ["sd1/"],
    "sd2": ["sd2/"],
    "sd3": ["sd3_5/", "sd3/"],
}

# LoRA architecture paths
LORA_ARCH_PATHS = {
    "flux": ["released/flux_1_d/", "testing/flux_1_d/", "flux_1_d/", "flux/"],
    "sdxl": ["released/sdxl/", "testing/sdxl/", "sdxl/"],
    "pony": ["released/pony/", "testing/pony/", "pony/"],
    "illustrious": ["released/illustrious/", "testing/illustrious/", "illustrious/"],
    "sd1": ["released/sd1/", "testing/sd1/", "sd1/"],
}


def _extract_model_names(data, node_name, input_key):
    """Extract model name list from ComfyUI object_info response.

    Handles two formats:
      - Simple list: [["model_a.safetensors", "model_b.safetensors"]]
      - COMBO format: ["COMBO", {"options": ["model_a.safetensors", ...]}]
    """
    raw = data[node_name]["input"]["required"][input_key]
    if isinstance(raw[0], list):
        return raw[0]
    # COMBO format — options are in the second element
    if len(raw) > 1 and isinstance(raw[1], dict) and "options" in raw[1]:
        return raw[1]["options"]
    # Fallback: if raw[0] is a list-like thing
    if isinstance(raw[0], str) and raw[0] == "COMBO":
        return raw[1].get("options", []) if len(raw) > 1 else []
    return raw[0] if isinstance(raw[0], list) else []


def api_get(endpoint):
    """Make a GET request to the ComfyUI API."""
    url = f"{BASE_URL}/api{endpoint}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"Error connecting to ComfyUI at {BASE_URL}: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid response from {url}", file=sys.stderr)
        sys.exit(1)


def filter_names(names, pattern=None, arch=None, arch_paths=None):
    """Filter a list of names by glob pattern and/or architecture."""
    results = names

    if arch and arch_paths:
        arch = arch.lower()
        if arch in arch_paths:
            prefixes = arch_paths[arch]
            results = [n for n in results if any(n.lower().startswith(p) for p in prefixes)]
        else:
            print(f"Warning: Unknown architecture '{arch}'. Available: {', '.join(arch_paths.keys())}", file=sys.stderr)

    if pattern:
        pattern_lower = pattern.lower()
        results = [n for n in results if pattern_lower in n.lower() or fnmatch(n.lower(), f"*{pattern_lower}*")]

    return sorted(results)


def cmd_checkpoints(args):
    """List available checkpoint models."""
    data = api_get("/object_info/CheckpointLoaderSimple")
    names = data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    filtered = filter_names(names, args.filter, args.base, ARCH_PATHS)

    print(f"Checkpoints: {len(filtered)}/{len(names)}")
    if args.filter or args.base:
        filters = []
        if args.base:
            filters.append(f"arch={args.base}")
        if args.filter:
            filters.append(f"filter={args.filter}")
        print(f"Filters: {', '.join(filters)}")
    print("---")
    for name in filtered:
        print(f"  {name}")


def cmd_loras(args):
    """List available LoRA models."""
    data = api_get("/object_info/LoraLoader")
    names = data["LoraLoader"]["input"]["required"]["lora_name"][0]
    filtered = filter_names(names, args.filter, args.base, LORA_ARCH_PATHS)

    print(f"LoRAs: {len(filtered)}/{len(names)}")
    if args.filter or args.base:
        filters = []
        if args.base:
            filters.append(f"arch={args.base}")
        if args.filter:
            filters.append(f"filter={args.filter}")
        print(f"Filters: {', '.join(filters)}")
    print("---")
    for name in filtered:
        print(f"  {name}")


def cmd_vaes(args):
    """List available VAE models."""
    data = api_get("/object_info/VAELoader")
    names = data["VAELoader"]["input"]["required"]["vae_name"][0]
    filtered = filter_names(names, args.filter)

    print(f"VAEs: {len(filtered)}/{len(names)}")
    print("---")
    for name in filtered:
        print(f"  {name}")


def cmd_workflows(args):
    """List saved workflows."""
    data = api_get("/userdata?dir=workflows")
    names = sorted(data) if isinstance(data, list) else []
    filtered = filter_names(names, args.filter) if args.filter else names

    print(f"Workflows: {len(filtered)}/{len(names)}")
    print("---")
    for name in filtered:
        print(f"  {name}")


def cmd_samplers(args):
    """List available samplers and schedulers."""
    data = api_get("/object_info/KSampler")
    ks = data["KSampler"]["input"]["required"]
    samplers = ks["sampler_name"][0]
    schedulers = ks["scheduler"][0]

    print(f"Samplers ({len(samplers)}):")
    for s in samplers:
        print(f"  {s}")
    print(f"\nSchedulers ({len(schedulers)}):")
    for s in schedulers:
        print(f"  {s}")


def cmd_status(args):
    """Show system status."""
    stats = api_get("/system_stats")
    queue = api_get("/prompt")

    sys_info = stats.get("system", {})
    devices = stats.get("devices", [])
    gpu = devices[0] if devices else {}

    vram_total = gpu.get("vram_total", 0)
    vram_free = gpu.get("vram_free", 0)
    vram_used = vram_total - vram_free

    print("=== ComfyUI Status ===")
    print(f"Host: {BASE_URL}")
    print(f"OS: {sys_info.get('os', 'unknown')}")
    print(f"Python: {sys_info.get('python_version', 'unknown').split('(')[0].strip()}")
    print(f"GPU: {gpu.get('name', 'unknown')}")
    print(f"VRAM: {vram_used / 1e9:.1f}GB / {vram_total / 1e9:.1f}GB ({vram_free / 1e9:.1f}GB free)")
    print(f"Queue: {queue.get('exec_info', {}).get('queue_remaining', 'unknown')} pending")


def cmd_controlnet(args):
    """List available ControlNet models."""
    data = api_get("/object_info/ControlNetLoader")
    names = data["ControlNetLoader"]["input"]["required"]["control_net_name"][0]
    filtered = filter_names(names, args.filter)

    print(f"ControlNet models: {len(filtered)}/{len(names)}")
    print("---")
    for name in filtered:
        print(f"  {name}")


def cmd_upscale(args):
    """List available upscale models."""
    data = api_get("/object_info/UpscaleModelLoader")
    names = _extract_model_names(data, "UpscaleModelLoader", "model_name")
    filtered = filter_names(names, args.filter)

    print(f"Upscale models: {len(filtered)}/{len(names)}")
    print("---")
    for name in filtered:
        print(f"  {name}")


# Node loaders to scan in search — maps category name to (node_name, input_key)
SEARCH_NODES = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "loras": ("LoraLoader", "lora_name"),
    "vaes": ("VAELoader", "vae_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "upscale": ("UpscaleModelLoader", "model_name"),
}


def cmd_search(args):
    """Search across all resource types."""
    query = args.query.lower()

    results = {}

    # Scan all node-based model types
    for category, (node_name, input_key) in SEARCH_NODES.items():
        try:
            data = api_get(f"/object_info/{node_name}")
            names = _extract_model_names(data, node_name, input_key)
            matches = [n for n in names if query in n.lower()]
            if matches:
                results[category] = matches
        except Exception:
            pass

    # Workflows are a different endpoint
    try:
        data = api_get("/userdata?dir=workflows")
        names = data if isinstance(data, list) else []
        matches = [n for n in names if query in n.lower()]
        if matches:
            results["workflows"] = matches
    except Exception:
        pass

    total = sum(len(v) for v in results.values())
    print(f"Search: '{args.query}' — {total} results")
    print("---")

    for category, items in results.items():
        if items:
            print(f"\n{category.upper()} ({len(items)}):")
            for item in sorted(items):
                print(f"  {item}")


def main():
    parser = argparse.ArgumentParser(description="ComfyUI Info — discover available resources")
    subparsers = parser.add_subparsers(dest="command", help="Action to perform")

    # Checkpoints
    cp = subparsers.add_parser("checkpoints", aliases=["ckpt"], help="List checkpoints")
    cp.add_argument("--filter", "-f", help="Filter by name pattern")
    cp.add_argument("--base", "-b", help="Filter by architecture (flux, sdxl, pony, illustrious, sd1, sd2, sd3)")

    # LoRAs
    lr = subparsers.add_parser("loras", aliases=["lora"], help="List LoRAs")
    lr.add_argument("--filter", "-f", help="Filter by name pattern")
    lr.add_argument("--base", "-b", help="Filter by architecture")

    # VAEs
    va = subparsers.add_parser("vaes", aliases=["vae"], help="List VAEs")
    va.add_argument("--filter", "-f", help="Filter by name pattern")

    # Workflows
    wf = subparsers.add_parser("workflows", aliases=["wf"], help="List saved workflows")
    wf.add_argument("--filter", "-f", help="Filter by name pattern")

    # ControlNet
    cn = subparsers.add_parser("controlnet", aliases=["cn"], help="List ControlNet models")
    cn.add_argument("--filter", "-f", help="Filter by name pattern")

    # Upscale
    up = subparsers.add_parser("upscale", aliases=["up"], help="List upscale models")
    up.add_argument("--filter", "-f", help="Filter by name pattern")

    # Samplers
    subparsers.add_parser("samplers", help="List samplers and schedulers")

    # Status
    subparsers.add_parser("status", help="Show system status")

    # Search
    sr = subparsers.add_parser("search", help="Search across all resources")
    sr.add_argument("query", help="Search query")

    args = parser.parse_args()

    commands = {
        "checkpoints": cmd_checkpoints, "ckpt": cmd_checkpoints,
        "loras": cmd_loras, "lora": cmd_loras,
        "vaes": cmd_vaes, "vae": cmd_vaes,
        "controlnet": cmd_controlnet, "cn": cmd_controlnet,
        "upscale": cmd_upscale, "up": cmd_upscale,
        "workflows": cmd_workflows, "wf": cmd_workflows,
        "samplers": cmd_samplers,
        "status": cmd_status,
        "search": cmd_search,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
