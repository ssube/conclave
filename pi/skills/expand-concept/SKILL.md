---
name: expand-concept
description: >-
  Expand brief concepts into rich, creative image prompts using LLM intelligence.
  Use when you want a short idea transformed into a unique, detailed prompt with
  creative interpretation — the LLM adds narrative, atmosphere, and unexpected
  details that templates cannot. Requires LLM API access.
---

# Expand Concept Skill

Take a brief concept and expand it into a full, optimized prompt for image generation using LLM.

## Usage

### Expand a concept

```bash
python3 {baseDir}/expand_concept.py expand \
    --concept "witch queen in dark forest" \
    --format flux \
    [--style dark-fantasy] \
    [--mood mysterious] \
    [--quality high] \
    [--aspect portrait] \
    [--with-negative] \
    [--output-format text|json]
```

## Options

### Format (required)

Target model format:
- `flux` - Natural language prose prompts
- `sdxl` - Comma-separated tags with weights `(tag:1.2)`
- `pony` - Score tags prefix + comma-separated tags

### Style Presets

Optional style hints:
- `dark-fantasy` - Gothic, moody, dramatic
- `anime` - Anime/manga style
- `photorealistic` - Photographic realism
- `painterly` - Traditional art style
- `concept-art` - Professional concept art

### Mood Presets

Optional mood hints:
- `mysterious` - Enigmatic, atmospheric
- `epic` - Grand, dramatic scale
- `serene` - Peaceful, calm
- `dark` - Ominous, foreboding
- `vibrant` - Colorful, energetic

### Quality Presets

- `high` - Maximum quality tags (masterpiece, best quality, etc.)
- `medium` - Standard quality
- `low` - Minimal quality modifiers

### Aspect Presets

- `portrait` - Vertical orientation
- `landscape` - Horizontal orientation
- `square` - 1:1 ratio

## Output

### Text format (default)

```
A powerful witch queen stands in a dark, ancient forest...
```

### JSON format

```json
{
  "prompt": "A powerful witch queen...",
  "negative_prompt": "worst quality, blurry...",
  "parameters": {
    "style": "dark-fantasy",
    "mood": "mysterious",
    "quality": "high",
    "aspect": "portrait"
  }
}
```

## Environment Variables

LLM provider configuration (see llm_client module):
- `LLM_PROVIDER`: anthropic, openrouter, ollama, openai (default: anthropic)
- `LLM_MODEL`: Model to use (default: claude-sonnet-4-20250514)
- `ANTHROPIC_API_KEY`: Required for Anthropic provider
- `OPENROUTER_API_KEY`: Required for OpenRouter provider
- `OLLAMA_HOST`: Ollama server URL (default: http://localhost:11434)
- `OPENAI_API_KEY`: Required for OpenAI provider
- `OPENAI_BASE_URL`: Override for OpenAI-compatible endpoints

## Examples

```bash
# Simple expansion with Flux format
python3 {baseDir}/expand_concept.py expand \
    --concept "dragon" \
    --format flux

# SDXL with style and quality
python3 {baseDir}/expand_concept.py expand \
    --concept "cyberpunk city at night" \
    --format sdxl \
    --style concept-art \
    --quality high \
    --with-negative

# JSON output for integration
python3 {baseDir}/expand_concept.py expand \
    --concept "magical forest" \
    --format pony \
    --output-format json
```
