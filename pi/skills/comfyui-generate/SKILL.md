---
name: comfyui-generate
description: >-
  Generate images via ComfyUI API with support for Flux and LoRAs, plus
  image-to-video via Wan 2.2. Use when creating images, generating artwork,
  running ComfyUI workflows, or producing visual content.
---

# ComfyUI Generate Skill

Generate images using ComfyUI API with Flux text-to-image and Wan 2.2 image-to-video.

**For detailed workflow node maps**, see [references/workflows.md](references/workflows.md).

## Usage

### Generate an image (custom workflow)

```bash
python3 {baseDir}/generate_image.py generate \
    --prompt "a gothic fantasy queen in dark armor" \
    --base flux \
    [--lora creature_lora:0.8] \
    [--size 832x1216] \
    [--output /path/to/output.png]
```

### Generate using a named workflow

```bash
python3 {baseDir}/generate_image.py generate \
    --workflow flux-lora \
    --prompt "a woman in a dark fantasy setting, dramatic lighting"
```

Named workflows are pre-built ComfyUI pipelines with model, LoRA, sampler, and all
settings already configured. Only the positive prompt text is changed. The `--base`,
`--lora`, and `--size` options are ignored when using a named workflow.

### Image-to-video

```bash
python3 {baseDir}/generate_image.py generate \
    --workflow wan22-i2v \
    --prompt "She turns slowly, silk shifting with the movement" \
    --image /path/to/source.png \
    --output video.webm
```

### Override workflow parameters with `--set`

```bash
python3 {baseDir}/generate_image.py generate \
    --workflow flux-lora \
    --prompt "crystal queen" \
    --set '96.inputs.lora_name=my-models/my-lora.safetensors' \
    --set '96.inputs.strength_model=0.8'
```

### List available named workflows

```bash
python3 {baseDir}/generate_image.py generate --workflow help
```

### Check queue / history

```bash
python3 {baseDir}/generate_image.py queue
python3 {baseDir}/generate_image.py history <prompt-id>
```

## Named Workflows

| Name | Model | LoRA Slots | Purpose |
|------|-------|------------|---------|
| `flux-lora` | Flux-dev fp8 | 2 (nodes 96, 200) | Primary text-to-image, natural language prompt |
| `wan22-i2v` | Wan 2.2 I2V (MoE) | None | Image-to-video with auto-captioning and 2x upscale |

For detailed node maps, parameter injection points, and data flow diagrams,
see [references/workflows.md](references/workflows.md).

## Options

### LoRA Support

```bash
--lora creature_lora:0.8
--lora style_lora:0.6
```

Multiple LoRAs can be chained. For named workflows, use `--set` to inject LoRA paths.

### Sizes

- `832x1216` — Portrait 2:3 (default)
- `1024x1024` — Square
- `1216x832` — Landscape 3:2
- `896x1152` — Portrait 3:4
- `1152x896` — Landscape 4:3

## LoRA Path Conventions

```
models/loras/
├── released/          # Published LoRAs
│   └── flux_1_d/      # Flux-trained LoRAs
├── testing/           # In-development LoRAs
│   └── flux_1_d/
└── third_party/       # Third-party style LoRAs
```

## Environment Variables

Required:
- `COMFYUI_HOST`: ComfyUI server hostname (default: localhost)
- `COMFYUI_PORT`: ComfyUI server port (default: 8188)

Optional:
- `COMFYUI_OUTPUT_DIR`: Default output directory

## Content Safety — Age & Maturity Requirements

**All human characters must be unambiguously adult (18+).** This is non-negotiable.

### Before posting or scheduling ANY generated image containing a human figure:

1. **Scan for chibi/young indicators** — Reject images where:
   - Head-to-body ratio is exaggerated (head ≥ 1/3 of total height = chibi proportions)
   - Face has round, childlike features (button nose, puffy cheeks, no jawline definition)
   - Body proportions are childlike (short limbs, no waist definition, small frame)

2. **Prompt for maturity** — When generating characters, always include age-establishing language:
   - ✅ `adult woman`, `mature face`, `defined cheekbones`, `tall figure`, `long legs`
   - ❌ Do NOT use: `cute girl`, `small`, `chibi`, `tiny`, `young`, `petite face`

3. **Stylization is not an excuse** — Cartoon, anime, and 3D stylized renders can still read as clearly adult.

4. **When in doubt, regenerate** — If a generated image could plausibly be interpreted as depicting a minor, delete it and regenerate with stronger maturity prompts.

## Examples

```bash
# Simple Flux generation
python3 {baseDir}/generate_image.py generate --prompt "a majestic dragon" --base flux

# Flux with LoRA (custom workflow)
python3 {baseDir}/generate_image.py generate \
    --prompt "fantasy creature, detailed" \
    --base flux \
    --lora creature_v2:0.7

# Named workflow: Flux with dual LoRA
python3 {baseDir}/generate_image.py generate \
    --workflow flux-lora \
    --prompt "a woman in crystalline armor, dramatic lighting"

# Image-to-video
python3 {baseDir}/generate_image.py generate \
    --workflow wan22-i2v \
    --prompt "gentle camera movement, atmospheric" \
    --image reference.png \
    --output video.webm

# Check queue
python3 {baseDir}/generate_image.py queue
```

## Troubleshooting

### ComfyUI connection refused
- Verify ComfyUI server is running: `curl http://$COMFYUI_HOST:$COMFYUI_PORT/system_stats`
- Check `COMFYUI_HOST` and `COMFYUI_PORT` environment variables

### LoRA not found
- LoRA paths are relative to ComfyUI's `models/loras/` directory
- Check that the file exists on the ComfyUI server

### Output not downloaded / wrong file
- Workflows use `_meta.output: true` on the target SaveImage node
- PreviewImage nodes are skipped — only nodes tagged with `output: true` are downloaded

### Queue stuck or timeout
- Check `python3 {baseDir}/generate_image.py queue` for stuck items
- Video workflows (wan22-i2v) take 5-15 minutes — increase timeout

## Output

Generated images are saved to:
- Specified `--output` path, or
- `$COMFYUI_OUTPUT_DIR/YYYYMMDD-HHMMSS.png`, or
- Current directory with timestamp filename
