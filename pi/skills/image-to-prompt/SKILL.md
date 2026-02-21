---
name: image-to-prompt
description: >-
  Analyze images and generate prompts to recreate them. Use when reverse-engineering a prompt from an existing image, describing image contents, or creating reproduction prompts from reference photos.
---

# Image to Prompt Skill

Analyze an image using vision LLM and generate prompts to recreate it in different image generation models.

## Usage

### Analyze an image

```bash
python3 {baseDir}/image_to_prompt.py analyze \
    --image "/path/to/image.png" \
    --format flux|sdxl|pony \
    [--detail high|medium|low] \
    [--with-negative] \
    [--output-format text|json]
```

## Options

### Format (required)

Target prompt format:
- `flux` - Natural language prose prompts
- `sdxl` - Comma-separated tags with optional weights
- `pony` - Score tags prefix + comma-separated tags

### Detail Level

Analysis depth:
- `high` - Comprehensive analysis with all details
- `medium` - Standard analysis (default)
- `low` - Quick overview with key elements only

### With Negative

Include a suggested negative prompt for the target format.

## Output

### Text format (default)

```
A powerful witch queen stands in a dark, ancient forest...
```

### JSON format

```json
{
  "prompt": "A powerful witch queen stands...",
  "negative_prompt": "worst quality, blurry...",
  "analysis": {
    "subjects": ["witch", "queen", "forest"],
    "style": "dark fantasy",
    "composition": "portrait",
    "lighting": "dramatic backlighting",
    "colors": ["purple", "black", "green"],
    "mood": "mysterious"
  },
  "raw_description": "Full Claude analysis..."
}
```

## Environment Variables

LLM provider configuration (see llm_client module):
- `LLM_PROVIDER`: anthropic, openrouter, ollama, openai (default: anthropic)
- `VISION_MODEL`: Model to use for vision (default: same as LLM_MODEL)
- `ANTHROPIC_API_KEY`: Required for Anthropic provider
- `OPENROUTER_API_KEY`: Required for OpenRouter provider
- `OLLAMA_HOST`: Ollama server URL (default: http://localhost:11434)
- `OPENAI_API_KEY`: Required for OpenAI provider

## Examples

```bash
# Generate Flux prompt from image
python3 {baseDir}/image_to_prompt.py analyze \
    --image artwork.png \
    --format flux

# Generate SDXL prompt with negative
python3 {baseDir}/image_to_prompt.py analyze \
    --image photo.jpg \
    --format sdxl \
    --with-negative

# Detailed JSON analysis
python3 {baseDir}/image_to_prompt.py analyze \
    --image complex_scene.png \
    --format flux \
    --detail high \
    --output-format json

# Quick analysis with Ollama
LLM_PROVIDER=ollama VISION_MODEL=llava python3 {baseDir}/image_to_prompt.py analyze \
    --image local.png \
    --format pony \
    --detail low
```

## Integration Example

```bash
# Round-trip: analyze image and regenerate
PROMPT=$(python3 image_to_prompt.py analyze --image original.png --format flux)
python3 ../generate-image/generate_image.py generate --prompt "$PROMPT" --base flux
```

## Dependencies

```
anthropic  # or openai depending on provider
Pillow
```
