---
name: comfyui-info
description: >-
  Query ComfyUI server for available models, LoRAs, VAEs, workflows, samplers, and system status. Use when checking what models are loaded, listing available LoRAs on the server, verifying ComfyUI status, or browsing generation capabilities.
---

# ComfyUI Info Skill

Query the ComfyUI server to discover available resources — models, LoRAs, ControlNet, upscale models, workflows, and system status.

## Actions

### List models (checkpoints)

```bash
python3 {baseDir}/comfyui_info.py checkpoints [--filter <pattern>] [--base <arch>]
```

Architecture filters: `flux`, `sdxl`, `pony`, `illustrious`, `sd1`, `sd2`, `sd3`

### List LoRAs

```bash
python3 {baseDir}/comfyui_info.py loras [--filter <pattern>] [--base <arch>]
```

### List VAEs

```bash
python3 {baseDir}/comfyui_info.py vaes [--filter <pattern>]
```

### List ControlNet models

```bash
python3 {baseDir}/comfyui_info.py controlnet [--filter <pattern>]
# Alias: cn
```

### List upscale models

```bash
python3 {baseDir}/comfyui_info.py upscale [--filter <pattern>]
# Alias: up
```

### List saved workflows

```bash
python3 {baseDir}/comfyui_info.py workflows [--filter <pattern>]
```

### List samplers and schedulers

```bash
python3 {baseDir}/comfyui_info.py samplers
```

### System status

```bash
python3 {baseDir}/comfyui_info.py status
```

Shows GPU, VRAM, queue depth, and OS info.

### Search across all resources

```bash
python3 {baseDir}/comfyui_info.py search <query>
```

Searches checkpoints, LoRAs, VAEs, ControlNet, upscale models, and workflows for matching names.

## Environment

- `COMFYUI_HOST` — ComfyUI server hostname (from `.env`)
- Uses HTTPS automatically when hostname contains a dot

## Examples

```bash
# Find LoRAs matching a name
python3 {baseDir}/comfyui_info.py loras --filter my-lora

# List all Flux checkpoints
python3 {baseDir}/comfyui_info.py checkpoints --base flux

# Check VRAM usage and queue
python3 {baseDir}/comfyui_info.py status

# Search for anything related to "depth"
python3 {baseDir}/comfyui_info.py search depth

# List all ControlNet models
python3 {baseDir}/comfyui_info.py cn

# Find Flux-compatible ControlNet models
python3 {baseDir}/comfyui_info.py cn --filter flux

# List Illustrious LoRAs
python3 {baseDir}/comfyui_info.py loras --base illustrious

# Find upscale models
python3 {baseDir}/comfyui_info.py up --filter my-model
```

## Troubleshooting

### Connection refused
ComfyUI server is not running at `COMFYUI_HOST:COMFYUI_PORT`. Verify with:
`curl http://localhost:8188/system_stats`

### No LoRAs listed
LoRA files may not be in ComfyUI's configured loras directory, or the model list hasn't been refreshed.
