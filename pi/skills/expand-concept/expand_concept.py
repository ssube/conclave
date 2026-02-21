#!/usr/bin/env python3
"""
Expand Concept Skill
Expand brief concepts into full image generation prompts using LLM
"""

import argparse
import json
import sys
from pathlib import Path

# Add llm_client to path
sys.path.insert(0, str(Path(__file__).parent.parent / "llm-client"))
from client import get_client


# System prompts for different formats
SYSTEM_PROMPTS = {
    "flux": """You are an expert at writing image generation prompts for Flux models.

Flux prompts should be written in natural language prose, describing the scene in detail.
Focus on:
- Subject description and positioning
- Environment and setting
- Lighting and atmosphere
- Art style and medium
- Color palette
- Composition and framing

Write flowing, descriptive prose rather than comma-separated tags.
Be specific and evocative. Paint a picture with words.

Output ONLY the prompt text, nothing else.""",
    "sdxl": """You are an expert at writing image generation prompts for SDXL models.

SDXL prompts should use comma-separated tags with optional weights in parentheses.
Format: tag1, tag2, (important tag:1.2), ((very important tag:1.4))

Include tags for:
- Subject and character details
- Art style and medium (digital art, oil painting, etc.)
- Quality modifiers (masterpiece, best quality, highly detailed)
- Lighting and atmosphere
- Composition
- Color palette

Order tags from most to least important.
Use weights (1.0-1.5) to emphasize key elements.

Output ONLY the comma-separated tags, nothing else.""",
    "pony": """You are an expert at writing image generation prompts for Pony Diffusion models.

Pony prompts start with score tags, then comma-separated descriptive tags.
Format: score_9, score_8_up, score_7_up, tag1, tag2, tag3...

Include:
- Score tags at the start (score_9, score_8_up, score_7_up for high quality)
- Character tags (1girl, 1boy, etc.)
- Physical descriptions
- Clothing and accessories
- Setting and background
- Art style tags
- Quality tags

Use underscores in multi-word tags (dark_fantasy, long_hair).
Keep tags concise and specific.

Output ONLY the comma-separated tags starting with score tags, nothing else.""",
}

NEGATIVE_PROMPTS = {
    "flux": "blurry, low quality, distorted, deformed, ugly, bad anatomy, bad proportions, watermark, signature, text",
    "sdxl": "worst quality, low quality, normal quality, lowres, bad anatomy, bad hands, extra fingers, missing fingers, deformed, blurry, watermark, signature, text, logo",
    "pony": "score_4, score_3, score_2, score_1, worst quality, low quality, bad anatomy, bad hands, missing fingers, extra digits, fewer digits, watermark, signature, text",
}

STYLE_HINTS = {
    "dark-fantasy": "dark fantasy aesthetic, gothic elements, moody atmosphere, dramatic shadows, mystical",
    "anime": "anime style, anime art, vibrant colors, clean lines, expressive",
    "photorealistic": "photorealistic, hyperrealistic, photograph, 8k, detailed textures, natural lighting",
    "painterly": "painterly style, visible brushstrokes, oil painting, traditional art, artistic",
    "concept-art": "concept art, professional illustration, detailed environment, cinematic, production quality",
}

MOOD_HINTS = {
    "mysterious": "mysterious atmosphere, enigmatic, atmospheric fog, subtle shadows, intrigue",
    "epic": "epic scale, grand, dramatic lighting, awe-inspiring, monumental",
    "serene": "serene, peaceful, calm, tranquil, gentle lighting, harmonious",
    "dark": "dark, ominous, foreboding, shadows, tension, dramatic",
    "vibrant": "vibrant colors, energetic, dynamic, lively, bold palette",
}

QUALITY_TAGS = {
    "high": {
        "flux": "highly detailed, masterwork quality, professional photography",
        "sdxl": "masterpiece, best quality, highly detailed, 8k, sharp focus",
        "pony": "score_9, score_8_up, score_7_up, masterpiece, best quality",
    },
    "medium": {
        "flux": "detailed, quality artwork",
        "sdxl": "high quality, detailed",
        "pony": "score_8_up, score_7_up, good quality",
    },
    "low": {
        "flux": "",
        "sdxl": "",
        "pony": "score_7_up",
    },
}

ASPECT_HINTS = {
    "portrait": "vertical composition, portrait orientation",
    "landscape": "horizontal composition, landscape orientation, wide view",
    "square": "centered composition, balanced framing",
}


def build_expansion_prompt(
    concept: str,
    format: str,
    style: str = None,
    mood: str = None,
    quality: str = None,
    aspect: str = None,
) -> str:
    """Build the prompt to send to the LLM."""
    parts = [f"Expand this concept into a detailed image prompt: {concept}"]

    if style and style in STYLE_HINTS:
        parts.append(f"Style: {STYLE_HINTS[style]}")

    if mood and mood in MOOD_HINTS:
        parts.append(f"Mood: {MOOD_HINTS[mood]}")

    if quality and quality in QUALITY_TAGS:
        quality_hint = QUALITY_TAGS[quality].get(format, "")
        if quality_hint:
            parts.append(f"Include quality indicators: {quality_hint}")

    if aspect and aspect in ASPECT_HINTS:
        parts.append(f"Composition: {ASPECT_HINTS[aspect]}")

    return "\n".join(parts)


def cmd_expand(args):
    """Expand a concept into a full prompt."""
    client = get_client()

    # Build the expansion request
    user_prompt = build_expansion_prompt(
        concept=args.concept,
        format=args.format,
        style=args.style,
        mood=args.mood,
        quality=args.quality,
        aspect=args.aspect,
    )

    system_prompt = SYSTEM_PROMPTS.get(args.format, SYSTEM_PROMPTS["flux"])

    # Get the expanded prompt
    expanded_prompt = client.complete(user_prompt, system=system_prompt)
    expanded_prompt = expanded_prompt.strip()

    # Build output
    if args.output_format == "json":
        result = {
            "prompt": expanded_prompt,
            "parameters": {
                "format": args.format,
            },
        }

        if args.style:
            result["parameters"]["style"] = args.style
        if args.mood:
            result["parameters"]["mood"] = args.mood
        if args.quality:
            result["parameters"]["quality"] = args.quality
        if args.aspect:
            result["parameters"]["aspect"] = args.aspect

        if args.with_negative:
            result["negative_prompt"] = NEGATIVE_PROMPTS.get(args.format, "")

        print(json.dumps(result, indent=2))
    else:
        print(expanded_prompt)
        if args.with_negative:
            print("\n--- Negative Prompt ---")
            print(NEGATIVE_PROMPTS.get(args.format, ""))


def main():
    parser = argparse.ArgumentParser(description="Expand Concept to Image Prompt")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Expand command
    expand_parser = subparsers.add_parser("expand", help="Expand a concept")
    expand_parser.add_argument(
        "--concept", required=True, help="Brief concept to expand"
    )
    expand_parser.add_argument(
        "--format",
        required=True,
        choices=["flux", "sdxl", "pony"],
        help="Target prompt format",
    )
    expand_parser.add_argument(
        "--style",
        choices=["dark-fantasy", "anime", "photorealistic", "painterly", "concept-art"],
        help="Style preset",
    )
    expand_parser.add_argument(
        "--mood",
        choices=["mysterious", "epic", "serene", "dark", "vibrant"],
        help="Mood preset",
    )
    expand_parser.add_argument(
        "--quality",
        choices=["high", "medium", "low"],
        default="high",
        help="Quality level (default: high)",
    )
    expand_parser.add_argument(
        "--aspect",
        choices=["portrait", "landscape", "square"],
        help="Aspect ratio hint",
    )
    expand_parser.add_argument(
        "--with-negative",
        action="store_true",
        help="Include negative prompt",
    )
    expand_parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    expand_parser.set_defaults(func=cmd_expand)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
