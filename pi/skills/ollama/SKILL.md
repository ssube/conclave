---
name: ollama
description: >-
  Local LLM generation via Ollama — image captioning, prompt generation,
  text enhancement, and creative writing. Use when captioning images for
  LoRA training datasets, generating image prompts, enhancing existing
  prompts, writing model descriptions, or producing creative text without
  requiring cloud API access.
---

# Ollama — Local LLM Generation

Generate text and caption images using a local Ollama instance. No cloud API
keys required — everything runs on your own hardware.

## Actions

### caption — Caption images for training datasets

Uses a two-stage pipeline: a vision model *sees* the image, then a text model
*writes* a polished caption in the requested style.

**Single image:**

```bash
python3 {baseDir}/ollama_generate.py caption /path/to/image.png [--style training|tags|detailed]
```

**Batch directory** (writes `.txt` files alongside each image):

```bash
python3 {baseDir}/ollama_generate.py caption /path/to/dataset/ [--style training] [--overwrite]
```

**Creative mode** — embellishes with atmosphere, mood, and descriptive richness:

```bash
python3 {baseDir}/ollama_generate.py caption /path/to/image.png --style detailed --creative
```

Without `--creative`: faithful, accurate captions — only what the vision model sees.
With `--creative`: adds atmosphere, mood, and sensory detail. Use for model cards,
gallery descriptions, social alt text — anywhere prose matters more than raw data.

**Caption styles:**

| Style | Format | Use for |
|-------|--------|---------|
| `training` | Natural language paragraph (50-150 words) | Flux/T5 LoRA training datasets |
| `tags` | Booru-style comma-separated tags (20-40 tags) | SDXL/Pony/Illustrious training |
| `detailed` | Rich prose description (2-4 sentences) | Model cards, galleries, catalogs |

**Options:**

- `--creative` / `-c` — Embellish with atmosphere and mood (default: accurate)
- `--trigger <word>` — Include a trigger word in every caption (for LoRA training)
- `--prefix <text>` — Prepend text to every caption
- `--overwrite` — Overwrite existing `.txt` files (default: skip existing)

**Batch output pattern:**

```
dataset/
├── image_001.png
├── image_001.txt   ← generated caption
├── image_002.jpg
├── image_002.txt   ← generated caption
└── ...
```

### prompt — Generate an image prompt from a concept

```bash
python3 {baseDir}/ollama_generate.py prompt "<concept>" [--encoder clip|t5]
```

Generates a detailed image generation prompt from a concept. Use `--encoder t5`
for Flux (natural language) or `--encoder clip` for SDXL/Pony (tag-style).

### enhance — Enrich an existing prompt with more detail

```bash
python3 {baseDir}/ollama_generate.py enhance "<prompt>" [--intensity mild|moderate|extreme]
```

Takes an existing prompt and rewrites it with additional detail, atmosphere,
and specificity. Intensity controls how much creative liberty the model takes.

### describe — Write a model card description

```bash
python3 {baseDir}/ollama_generate.py describe "<model_name>" --type <lora_type> [--tags <tags>]
```

Generates a model card description for sharing platforms like HuggingFace.

### lore — Generate creative fiction or scene descriptions

```bash
python3 {baseDir}/ollama_generate.py lore "<scenario>" [--length short|medium|long]
```

Produces creative fiction, scene descriptions, character profiles, or world-building lore.

## Environment

| Variable | Purpose | Default |
|----------|---------|---------|
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Text generation model | `qwen3-30b-a3b:latest` |
| `OLLAMA_VISION_MODEL` | Vision model for image captioning | `qwen3-vl:32b` |

## How Captioning Works

The two-stage pipeline separates *seeing* from *writing*:

1. **Vision stage**: `OLLAMA_VISION_MODEL` analyzes the image with a precise system
   prompt — extracting subject, pose, clothing, setting, lighting, and art style.

2. **Refinement stage**: `OLLAMA_MODEL` takes the raw description and rewrites it
   in the requested caption style — training-ready natural language, booru tags,
   or rich prose.

This two-stage approach means:
- The vision model focuses on accurate description
- The text model focuses on style and formatting
- You can swap either model independently

## Notes

- First call may be slow (~30-60s) if models need to load into VRAM
- Captioning loads TWO models — the vision model and the text model. Allow extra time.
- Subsequent calls are fast while models stay warm
- Uses `/no_think` to suppress qwen3 reasoning blocks
- Batch captioning skips existing `.txt` files by default (use `--overwrite` to redo)

## Troubleshooting

### "Error connecting to Ollama"
Check that `OLLAMA_HOST` is set and the Ollama server is running.

### Vision model not available
Verify with `curl $OLLAMA_HOST/api/tags` that the vision model is pulled.
Pull it: `ollama pull qwen3-vl:32b`

### Captions are too vague
Try a different vision model, or increase `max_tokens`. The text refinement stage
can only work with the detail the vision model provides.

### Batch is slow
Each image requires two model calls. For large datasets (100+ images), expect several
hours. Run in tmux: `tmux new-session -d -s caption 'python3 ollama_generate.py caption ./dataset/'`
