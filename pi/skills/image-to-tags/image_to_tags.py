#!/usr/bin/env python3
"""
Image to Tags Skill
Extract structured tags from images using WD14 tagger or vision LLM
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Add llm_client to path
sys.path.insert(0, str(Path(__file__).parent.parent / "llm-client"))

# Configuration
WD14_MODEL_REPO = os.environ.get("WD14_MODEL_REPO", "SmilingWolf/wd-vit-tagger-v3")
DEFAULT_THRESHOLD = 0.35
DEFAULT_MAX_TAGS = 30

# Lazy-loaded models
_wd14_model = None
_wd14_tags = None
_wd14_processor = None


def get_wd14():
    """Lazy load WD14 tagger model."""
    global _wd14_model, _wd14_tags, _wd14_processor

    if _wd14_model is None:
        try:
            import torch
            from transformers import AutoModelForImageClassification, AutoProcessor
            import pandas as pd
            from huggingface_hub import hf_hub_download
        except ImportError as e:
            print(f"Error: Required packages not installed: {e}", file=sys.stderr)
            print(
                "Install with: pip install torch transformers pandas huggingface_hub",
                file=sys.stderr,
            )
            sys.exit(1)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading WD14 tagger from {WD14_MODEL_REPO}...", file=sys.stderr)

        _wd14_model = AutoModelForImageClassification.from_pretrained(
            WD14_MODEL_REPO, trust_remote_code=True
        ).to(device).eval()

        _wd14_processor = AutoProcessor.from_pretrained(
            WD14_MODEL_REPO, trust_remote_code=True
        )

        # Load tag names from CSV
        csv_path = hf_hub_download(WD14_MODEL_REPO, "selected_tags.csv")
        df = pd.read_csv(csv_path)
        _wd14_tags = df["name"].tolist()

        # Try to load categories if available
        if "category" in df.columns:
            _wd14_categories = df["category"].tolist()
        else:
            _wd14_categories = ["general"] * len(_wd14_tags)

        print(
            f"Loaded WD14 tagger with {len(_wd14_tags)} tags on {device}",
            file=sys.stderr,
        )

    return _wd14_model, _wd14_tags, _wd14_processor


def generate_tags_wd14(
    image_path: str, threshold: float = DEFAULT_THRESHOLD, max_tags: int = DEFAULT_MAX_TAGS
) -> list[dict[str, Any]]:
    """Generate tags using WD14 tagger model.

    Returns list of dicts with 'tag', 'confidence', and 'category' keys.
    """
    import torch
    from PIL import Image

    model, tags, processor = get_wd14()
    device = next(model.parameters()).device

    img = Image.open(image_path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt").to(device)

    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.sigmoid(outputs.logits).cpu().numpy()[0]

    # Categorize tags based on common prefixes
    def categorize_tag(tag: str) -> str:
        if tag.startswith(("1girl", "1boy", "2girls", "2boys", "solo", "multiple")):
            return "character"
        elif tag.endswith(("_hair", "_eyes", "_skin")):
            return "appearance"
        elif tag in ("masterpiece", "best quality", "high quality", "low quality"):
            return "quality"
        elif "_background" in tag or tag.endswith("_scene"):
            return "background"
        else:
            return "general"

    # Get tags above threshold
    results = []
    for idx, prob in enumerate(probs):
        if prob >= threshold and idx < len(tags):
            tag = tags[idx]
            results.append(
                {
                    "tag": tag,
                    "confidence": float(prob),
                    "category": categorize_tag(tag),
                }
            )

    # Sort by confidence and limit
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:max_tags]


def generate_tags_llm(
    image_path: str, include_natural: bool = False, max_tags: int = DEFAULT_MAX_TAGS
) -> dict[str, Any]:
    """Generate tags using vision LLM.

    Returns dict with 'tags' list and optionally 'natural_description'.
    """
    from client import get_client

    client = get_client()

    system_prompt = """You are an expert at analyzing images and extracting descriptive tags.
Output structured tags that describe the image content accurately.
Focus on: subjects, style, composition, colors, mood, quality indicators."""

    if include_natural:
        user_prompt = f"""Analyze this image and provide:
1. A list of descriptive tags (comma-separated, booru-style with underscores)
2. A natural language description

Format your response EXACTLY as:
TAGS: tag1, tag2, tag3, ...
DESCRIPTION: Your natural language description here.

Provide up to {max_tags} tags, ordered by importance."""
    else:
        user_prompt = f"""Analyze this image and provide descriptive tags.
Output ONLY comma-separated tags (booru-style with underscores for multi-word tags).
Provide up to {max_tags} tags, ordered by importance.
Example: 1girl, solo, long_hair, fantasy, magical_forest, detailed_background"""

    response = client.complete_with_image(user_prompt, image_path, system=system_prompt)
    response = response.strip()

    result = {"tags": []}

    if include_natural and "DESCRIPTION:" in response:
        # Parse structured response
        parts = response.split("DESCRIPTION:")
        tags_part = parts[0].replace("TAGS:", "").strip()
        desc_part = parts[1].strip() if len(parts) > 1 else ""

        tag_list = [t.strip() for t in tags_part.split(",") if t.strip()]
        result["tags"] = [
            {"tag": t, "confidence": 1.0, "category": "llm"} for t in tag_list[:max_tags]
        ]
        result["natural_description"] = desc_part
    else:
        # Parse simple comma-separated response
        tag_list = [t.strip() for t in response.split(",") if t.strip()]
        result["tags"] = [
            {"tag": t, "confidence": 1.0, "category": "llm"} for t in tag_list[:max_tags]
        ]

    return result


def generate_tags_ensemble(
    image_path: str,
    threshold: float = DEFAULT_THRESHOLD,
    max_tags: int = DEFAULT_MAX_TAGS,
    include_natural: bool = False,
) -> dict[str, Any]:
    """Generate tags using both WD14 and LLM, then merge results.

    Returns dict with 'tags' list and optionally 'natural_description'.
    """
    # Get WD14 tags
    print("Running WD14 tagger...", file=sys.stderr)
    wd14_tags = generate_tags_wd14(image_path, threshold, max_tags)

    # Get LLM tags
    print("Running LLM tagger...", file=sys.stderr)
    llm_result = generate_tags_llm(image_path, include_natural, max_tags)
    llm_tags = llm_result["tags"]

    # Merge tags, preferring WD14 confidence scores
    seen = {}
    for tag_info in wd14_tags:
        key = tag_info["tag"].lower().replace(" ", "_")
        seen[key] = tag_info

    for tag_info in llm_tags:
        key = tag_info["tag"].lower().replace(" ", "_")
        if key not in seen:
            seen[key] = tag_info

    # Sort by confidence and limit
    merged = sorted(seen.values(), key=lambda x: x["confidence"], reverse=True)

    result = {"tags": merged[:max_tags]}
    if include_natural and "natural_description" in llm_result:
        result["natural_description"] = llm_result["natural_description"]

    return result


def cmd_extract(args):
    """Extract tags from an image."""
    if not os.path.exists(args.image):
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    include_natural = args.format in ("natural", "both")

    # Generate tags based on backend
    if args.backend == "wd14":
        tags = generate_tags_wd14(args.image, args.threshold, args.max_tags)
        result = {"tags": tags}
        if include_natural:
            result["natural_description"] = "(Natural description requires llm or ensemble backend)"
    elif args.backend == "llm":
        result = generate_tags_llm(args.image, include_natural, args.max_tags)
    elif args.backend == "ensemble":
        result = generate_tags_ensemble(
            args.image, args.threshold, args.max_tags, include_natural
        )
    else:
        print(f"Error: Unknown backend: {args.backend}", file=sys.stderr)
        sys.exit(1)

    # Build booru format string
    booru_format = ", ".join(t["tag"] for t in result["tags"])
    result["booru_format"] = booru_format

    # Output
    if args.output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        if args.format == "booru":
            print(booru_format)
        elif args.format == "natural":
            print(result.get("natural_description", booru_format))
        else:  # both
            print("=== Booru Tags ===")
            print(booru_format)
            print("\n=== Natural Description ===")
            print(result.get("natural_description", "(Not available)"))

    print(f"\nExtracted {len(result['tags'])} tags", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Extract Tags from Images")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Extract command
    extract_parser = subparsers.add_parser("extract", help="Extract tags from image")
    extract_parser.add_argument("--image", required=True, help="Path to image file")
    extract_parser.add_argument(
        "--backend",
        choices=["wd14", "llm", "ensemble"],
        default="wd14",
        help="Tagging backend (default: wd14)",
    )
    extract_parser.add_argument(
        "--format",
        choices=["booru", "natural", "both"],
        default="booru",
        help="Output format (default: booru)",
    )
    extract_parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Confidence threshold for WD14 (default: {DEFAULT_THRESHOLD})",
    )
    extract_parser.add_argument(
        "--max-tags",
        type=int,
        default=DEFAULT_MAX_TAGS,
        help=f"Maximum number of tags (default: {DEFAULT_MAX_TAGS})",
    )
    extract_parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    extract_parser.set_defaults(func=cmd_extract)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
