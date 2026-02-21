#!/usr/bin/env python3
"""
Image to Prompt Skill
Analyze images and generate prompts to recreate them
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add llm_client to path
sys.path.insert(0, str(Path(__file__).parent.parent / "llm-client"))
from client import get_client


# Analysis prompts for different detail levels
ANALYSIS_PROMPTS = {
    "high": """Analyze this image in comprehensive detail for recreation with an AI image generator.

Describe the following aspects:

1. SUBJECTS: Main subjects, characters, or objects. Include poses, expressions, clothing, accessories.

2. STYLE: Art style, medium (digital art, oil painting, photograph, etc.), artistic influences.

3. COMPOSITION: Framing, camera angle, perspective, focal points, rule of thirds usage.

4. LIGHTING: Light sources, direction, quality (soft/hard), color temperature, shadows.

5. COLORS: Dominant color palette, color harmony, saturation levels, contrast.

6. MOOD: Emotional tone, atmosphere, tension or calmness.

7. BACKGROUND: Setting, environment details, depth of field.

8. QUALITY: Technical quality indicators, detail level, sharpness.

Be specific and precise. Use descriptive language that can guide image generation.""",
    "medium": """Analyze this image for recreation with an AI image generator.

Describe:
1. Main subjects and their key features
2. Art style and medium
3. Composition and framing
4. Lighting and atmosphere
5. Color palette
6. Overall mood

Be descriptive and specific.""",
    "low": """Briefly describe this image for recreation with an AI image generator.

Focus on:
- Main subject
- Art style
- Key visual elements
- Overall mood

Keep it concise but descriptive.""",
}

# System prompts for different output formats
FORMAT_PROMPTS = {
    "flux": """You are an expert at writing image generation prompts for Flux models.

Based on your analysis, write a natural language prose prompt that captures the image.
Flux prompts should flow like descriptive writing, not comma-separated tags.
Focus on the most important visual elements.

Output ONLY the final prompt, nothing else. No labels, no explanations.""",
    "sdxl": """You are an expert at writing image generation prompts for SDXL models.

Based on your analysis, write a comma-separated tag prompt that captures the image.
Format: tag1, tag2, (important tag:1.2), ((very important tag:1.4))

Include:
- Subject tags first
- Style and medium tags
- Quality tags (masterpiece, best quality, highly detailed)
- Composition and lighting tags
- Color and mood tags

Output ONLY the comma-separated tags, nothing else. No labels, no explanations.""",
    "pony": """You are an expert at writing image generation prompts for Pony Diffusion models.

Based on your analysis, write a Pony-style prompt starting with score tags.
Format: score_9, score_8_up, score_7_up, tag1, tag2, tag3...

Use underscores in multi-word tags (long_hair, dark_fantasy).
Include character counts (1girl, 1boy) if applicable.

Output ONLY the comma-separated tags starting with score tags, nothing else.""",
}

NEGATIVE_PROMPTS = {
    "flux": "blurry, low quality, distorted, deformed, ugly, bad anatomy, bad proportions, watermark, signature, text",
    "sdxl": "worst quality, low quality, normal quality, lowres, bad anatomy, bad hands, extra fingers, missing fingers, deformed, blurry, watermark, signature, text, logo, cropped, out of frame",
    "pony": "score_4, score_3, score_2, score_1, worst quality, low quality, bad anatomy, bad hands, missing fingers, extra digits, fewer digits, watermark, signature, text, blurry",
}


def analyze_image(
    image_path: str, format: str, detail: str = "medium", with_negative: bool = False
) -> dict:
    """Analyze an image and generate a recreation prompt.

    Args:
        image_path: Path to the image file
        format: Target format (flux, sdxl, pony)
        detail: Analysis detail level (high, medium, low)
        with_negative: Whether to include negative prompt

    Returns:
        Dict with prompt, analysis, and optionally negative_prompt
    """
    client = get_client()

    # Step 1: Analyze the image
    analysis_prompt = ANALYSIS_PROMPTS.get(detail, ANALYSIS_PROMPTS["medium"])
    print("Analyzing image...", file=sys.stderr)

    raw_analysis = client.complete_with_image(
        analysis_prompt,
        image_path,
        system="You are an expert art analyst and image description specialist.",
    )

    # Step 2: Generate prompt in target format
    format_prompt = FORMAT_PROMPTS.get(format, FORMAT_PROMPTS["flux"])
    conversion_prompt = f"""Based on this image analysis, generate a prompt:

{raw_analysis}

{format_prompt}"""

    print(f"Generating {format} prompt...", file=sys.stderr)
    final_prompt = client.complete(conversion_prompt)
    final_prompt = final_prompt.strip()

    # Parse analysis into structured form
    analysis_data = parse_analysis(raw_analysis)

    result = {
        "prompt": final_prompt,
        "format": format,
        "analysis": analysis_data,
        "raw_description": raw_analysis,
    }

    if with_negative:
        result["negative_prompt"] = NEGATIVE_PROMPTS.get(format, "")

    return result


def parse_analysis(raw_analysis: str) -> dict:
    """Parse raw analysis text into structured data."""
    analysis = {
        "subjects": [],
        "style": "",
        "composition": "",
        "lighting": "",
        "colors": [],
        "mood": "",
    }

    lines = raw_analysis.lower()

    # Simple heuristic parsing
    if "subject" in lines:
        # Extract subjects mentioned
        pass

    # For now, return a simplified structure
    # A more sophisticated parser could extract structured data
    analysis["summary"] = raw_analysis[:500] if len(raw_analysis) > 500 else raw_analysis

    return analysis


def cmd_analyze(args):
    """Analyze an image and generate a prompt."""
    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    result = analyze_image(
        image_path=args.image,
        format=args.format,
        detail=args.detail,
        with_negative=args.with_negative,
    )

    if args.output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result["prompt"])
        if args.with_negative:
            print("\n--- Negative Prompt ---")
            print(result.get("negative_prompt", ""))


def main():
    parser = argparse.ArgumentParser(description="Analyze Image and Generate Prompt")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze image and generate prompt")
    analyze_parser.add_argument("--image", required=True, help="Path to image file")
    analyze_parser.add_argument(
        "--format",
        required=True,
        choices=["flux", "sdxl", "pony"],
        help="Target prompt format",
    )
    analyze_parser.add_argument(
        "--detail",
        choices=["high", "medium", "low"],
        default="medium",
        help="Analysis detail level (default: medium)",
    )
    analyze_parser.add_argument(
        "--with-negative",
        action="store_true",
        help="Include negative prompt",
    )
    analyze_parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    analyze_parser.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
