## Named Workflows Reference

Named workflows are complete pre-built ComfyUI pipelines. Each has a specific purpose
and set of configurable parameters. **When using `--workflow`, only `--prompt` is needed.**
All other settings (model, sampler, steps, CFG, etc.) are baked into the workflow.

### `flux-lora` — Flux Text-to-Image with 2 LoRA Slots

**File:** `workflows/flux_lora_text_to_image.json`

The primary Flux generation workflow. Uses flux-dev-fp8 with two chained LoRA loaders.

| Setting | Value |
|---------|-------|
| Model | `flux_1_d/flux-dev-fp8.safetensors` |
| Steps | 35 |
| CFG | 1 |
| Sampler | euler / sgm_uniform |
| Guidance | 4.0 (FluxGuidance) |
| Default Size | 1024×1280 |
| LoRA Slot 1 | Node `96` — primary concept LoRA |
| LoRA Slot 2 | Node `200` — secondary/style LoRA |

**Node Map — Where to inject parameters:**

| Parameter | Node ID | Field | Notes |
|-----------|---------|-------|-------|
| **Prompt** | `112` | `string` | StringConstantMultiline → feeds CLIPTextEncode |
| **Negative** | `33` | `text` | Empty by default (Flux doesn't need negatives) |
| **LoRA 1 name** | `96` | `lora_name` | Path relative to ComfyUI loras/ dir |
| **LoRA 1 weight** | `96` | `strength_model` / `strength_clip` | Typically 0.5–0.9 |
| **LoRA 2 name** | `200` | `lora_name` | Second LoRA in chain |
| **LoRA 2 weight** | `200` | `strength_model` / `strength_clip` | Typically 0.4–0.8 |
| **Width** | `27` | `width` | EmptySD3LatentImage |
| **Height** | `27` | `height` | EmptySD3LatentImage |
| **Seed** | `31` | `seed` | KSampler — auto-randomized |
| **Guidance** | `35` | `guidance` | FluxGuidance strength |

**Data Flow:**
```
Checkpoint → LoRA 1 → LoRA 2 → KSampler
                                    ↑
Prompt → StringConstant → CLIPTextEncode → FluxGuidance ─┘
                                    
KSampler → VAEDecode → SaveImage
```

**Usage:**
```bash
python3 generate_image.py generate --workflow flux-lora \
    --prompt "a woman in a crystal-covered dress, dramatic lighting"
```

**To swap LoRAs** (via --set):
```bash
python3 generate_image.py generate --workflow flux-lora \
    --prompt "your prompt here" \
    --set '96.inputs.lora_name=my-models/my-lora.safetensors' \
    --set '96.inputs.strength_model=0.8' \
    --set '200.inputs.lora_name=my-models/style-lora.safetensors' \
    --set '200.inputs.strength_model=0.6'
```

---

### `wan22-i2v` — Wan 2.2 Upscale Image-to-Video (Quality)

**File:** `workflows/wan22_upscale_image_to_video.json`

High-quality image-to-video using Wan 2.2's two-pass MoE architecture. Auto-
captioning tags the input image, then the custom prompt is prepended to the tags.
Output is 2x upscaled before RIFE interpolation to 32fps.

| Setting | Value |
|---------|-------|
| High-Noise Model | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` |
| Low-Noise Model | `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` |
| Text Encoder | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| VAE | `wan_2.1_vae.safetensors` |
| Steps | 20 total (10 high-noise + 10 low-noise) |
| CFG | 3.5 |
| Shift | 8.0 (both passes) |
| Default Size | 720×640 (→ 1440×1280 after upscale) |
| Frame Count | 81 |
| RIFE | 2x interpolation → 32fps webm |
| Auto-Caption | WD14 tagger (threshold 0.35) |

**Node Map:**

| Parameter | Node ID | Field | Notes |
|-----------|---------|-------|-------|
| **Custom Prompt** | `118` | `text_a` | StringFunction — prepended to auto-caption |
| **Input Image** | `62` | `image` | LoadImage (must upload first) |
| **Seed** | `57` | `noise_seed` | First KSampler |
| **Width** | `63` | `width` | WanImageToVideo |
| **Height** | `63` | `height` | WanImageToVideo |
| **Frame Count** | `63` | `length` | Default 81 |

**Architecture:**
```
LoadImage → WD14Tagger → StringFunction(custom_prompt + tags) → CLIPTextEncode
    ↓                                                               ↓
WanImageToVideo (conditioning) ← ← ← ← ← ← ← ← ← ← ← ← ← ← ← ↓
    ↓
High-Noise UNET + ModelSamplingSD3(shift=8) → KSampler(steps 0-10)
                                                    ↓
Low-Noise UNET + ModelSamplingSD3(shift=8)  → KSampler(steps 10-20)
                                                    ↓
                                                VAEDecode
                                                    ↓
                                          Upscale 2x (neural)
                                                    ↓
                                              RIFE 2x → 32fps webm
```

**Usage:**
```bash
python3 generate_image.py generate --workflow wan22-i2v \
    --prompt "gentle camera movement, atmospheric lighting" \
    --image reference.png \
    --output video.webm
```

**Notes:**
- Long generation time (~10-15min due to 20 steps + upscale + RIFE)
- Auto-captioning via WD14 — custom prompt enhances but doesn't replace vision understanding
- 2x neural upscale produces high-resolution output (1440×1280 from 720×640 base)
- No user LoRA slots — the pipeline uses base models directly

---

## Workflow Template (for custom generation)

| File | Model | Description |
|------|-------|-------------|
| `flux-base.json` | Flux-dev | Basic Flux workflow (prompt + LoRA injection) |

This template is used by `generate_image.py` when you pass `--base flux` instead of
`--workflow`. The script dynamically injects the prompt, LoRAs, and size parameters.

---

## Output Node Tagging

Workflows use `_meta.output: true` on the intended download target (SaveImage or
VHS_VideoCombine). This tells `download_output()` which node's result to download,
avoiding confusion with PreviewImage nodes that produce intermediate results.

```json
{
  "121": {
    "class_type": "SaveImage",
    "_meta": { "title": "Save Output", "output": true }
  }
}
```

## LoRA Path Conventions

LoRA files on the ComfyUI server follow this directory structure:

```
models/loras/
├── released/          # Published LoRAs
│   └── flux_1_d/      # Flux-trained LoRAs
├── testing/           # In-development LoRAs
│   └── flux_1_d/
└── third_party/       # Third-party LoRAs
```
