---
name: image-to-tags
description: >-
  Extract structured tags from images using WD14 tagger or vision LLM. Use when tagging images, extracting booru-style keywords, classifying image content, or generating tag lists for dataset preparation.
---

# Image to Tags Skill

Extract structured tags from images using multiple backends.

## Usage

### Extract tags from an image

```bash
python3 {baseDir}/image_to_tags.py extract \
    --image "/path/to/image.png" \
    --backend wd14|llm|ensemble \
    [--format booru|natural|both] \
    [--threshold 0.35] \
    [--max-tags 30] \
    [--output-format text|json]
```

## Backends

### wd14 (default)

WD14 Tagger neural network - fast, optimized for anime/illustration styles.
Outputs tags with confidence scores. No API key required.

### llm

Vision LLM (Claude Vision, OpenAI GPT-4V, Ollama LLaVA, etc.)
Uses the configured LLM provider with vision capability.
Best quality and most versatile but requires API access.

### ensemble

Combines WD14 + LLM results, merging and deduplicating tags.
Provides the most comprehensive tag coverage.

## Options

### Format

- `booru` (default) - Comma-separated booru-style tags
- `natural` - Natural language description
- `both` - Both formats

### Threshold

Confidence threshold for WD14 tags (default: 0.35)
Higher values = fewer but more confident tags.

### Max Tags

Maximum number of tags to return (default: 30)

## Output

### Text format

```
1girl, solo, witch, dark_fantasy, glowing_eyes, long_hair, purple_hair
```

### JSON format

```json
{
  "tags": [
    {"tag": "1girl", "confidence": 0.95, "category": "character"},
    {"tag": "dark_fantasy", "confidence": 0.87, "category": "style"}
  ],
  "booru_format": "1girl, solo, witch, dark_fantasy, glowing_eyes...",
  "natural_description": "A dark fantasy witch with glowing eyes..."
}
```

## Environment Variables

WD14 tagger:
- `WD14_MODEL_REPO`: HuggingFace model repo (default: SmilingWolf/wd-vit-tagger-v3)

LLM provider (for llm/ensemble backends):
- `LLM_PROVIDER`: anthropic, openrouter, ollama, openai (default: anthropic)
- `VISION_MODEL`: Model to use for vision (default: same as LLM_MODEL)
- `ANTHROPIC_API_KEY`: Required for Anthropic provider
- `OPENROUTER_API_KEY`: Required for OpenRouter provider
- `OLLAMA_HOST`: Ollama server URL (default: http://localhost:11434)

## Examples

```bash
# Quick WD14 tagging (no API needed)
python3 {baseDir}/image_to_tags.py extract --image photo.jpg --backend wd14

# LLM-based tagging with natural description
python3 {baseDir}/image_to_tags.py extract \
    --image artwork.png \
    --backend llm \
    --format both

# High-confidence tags with JSON output
python3 {baseDir}/image_to_tags.py extract \
    --image image.png \
    --backend wd14 \
    --threshold 0.5 \
    --output-format json

# Ensemble for comprehensive coverage
python3 {baseDir}/image_to_tags.py extract \
    --image complex_scene.png \
    --backend ensemble \
    --max-tags 50
```

## Dependencies

For WD14 backend:
```
torch
transformers
pandas
huggingface_hub
Pillow
```

For LLM backend:
```
anthropic  # or openai depending on provider
Pillow
```
