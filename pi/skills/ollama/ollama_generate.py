#!/usr/bin/env python3
"""
Ollama Local LLM Generation

Generate text, captions, prompts, and descriptions using a local Ollama
instance. Supports image captioning via a two-stage vision pipeline.
"""

import argparse
import base64
import glob
import json
import os
import sys
import urllib.request
import urllib.error

# ── Configuration ──────────────────────────────────────────────

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL", "qwen3:30b"
)
OLLAMA_VISION_MODEL = os.environ.get(
    "OLLAMA_VISION_MODEL", "qwen3-vl:32b"
)
API_URL = f"{OLLAMA_HOST}/v1/chat/completions"
TIMEOUT = 180  # seconds — network storage means cold loads are slow

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


# ── System Prompts ─────────────────────────────────────────────

SYSTEM_PROMPT_BASE = """You are a skilled content generation assistant running locally via Ollama. You produce vivid, specific, and well-structured output in service of the creative vision. You aim for quality and precision."""

SYSTEM_PROMPTS = {
    "prompt_clip": SYSTEM_PROMPT_BASE + """

You generate image prompts in CLIP/tag style for SDXL and similar diffusion models. Output comma-separated tags and descriptors. Be specific about subjects, poses, expressions, clothing, setting, lighting, and artistic style. Include quality tags (masterpiece, best quality, detailed) and style tags (photorealistic, digital painting, etc.).

Output ONLY the prompt tags. No commentary, no explanation, no markdown.""",

    "prompt_t5": SYSTEM_PROMPT_BASE + """

You generate image prompts in natural language for Flux models with T5 text encoder. Write flowing, descriptive sentences that paint the scene vividly. Be specific about subjects, details, expressions, clothing, setting. Describe lighting, atmosphere, camera angle, and artistic style naturally within the prose.

Output ONLY the prompt text. No commentary, no explanation, no markdown. One continuous paragraph.""",

    "enhance": SYSTEM_PROMPT_BASE + """

You take an existing image prompt and rewrite it with significantly more detail, specificity, and atmosphere. Preserve the original concept, composition, and style — but add what was missing: finer details, richer descriptions, stronger mood, more precise visual language.

Output ONLY the enhanced prompt. No commentary, no explanation. Match the format of the input (tags for tag-style, prose for prose-style).""",

    "describe": SYSTEM_PROMPT_BASE + """

You write model card descriptions for AI art models (LoRAs, checkpoints, etc.) for sharing platforms. Your descriptions are:
- Clear about what the model generates
- Specific about recommended prompts and settings
- Engaging and well-written
- Honest about capabilities and limitations

Include: what the model does, what content it produces, recommended prompt style, suggested weights, and example use cases.""",

    "lore": SYSTEM_PROMPT_BASE + """

You write creative fiction, lore, and scene descriptions. You write with sensory precision: texture, light, sound, atmosphere. You can write character profiles, scene descriptions, world-building lore, dialogue, and narrative fiction.""",

    # ── Vision / Caption prompts ───────────────────────────────

    "vision_raw": """You are an image analysis system. Describe what you see in this image with precise, objective detail. Include:
- Subject(s): number, general appearance, and notable features
- Pose, gesture, and composition
- Clothing, accessories, and visible objects
- Expression and gaze direction
- Setting and background elements
- Lighting, color palette, art style
- Any text, watermarks, or artifacts

Be thorough and precise. Describe what is depicted without adding interpretation or emotional language.""",

    # ── Accurate caption prompts (default) ─────────────────────

    "caption_training": """You write training captions for AI image generation datasets. You are given a description of what an image actually contains. Your job is to rewrite that description as a clean, accurate caption.

CRITICAL: Only describe what was mentioned in the provided description. Do NOT invent or fabricate details. If the image shows crystals on a pipe, caption crystals on a pipe. If the image shows a person, caption that person. Accuracy is everything.

Rules:
- Be faithful to the source description — every detail in your caption must come from it
- Use natural, flowing language (for T5/Flux training)
- Describe all details mentioned in the source description accurately
- Do not invent or add details not present in the source
- Keep to one paragraph, 50-150 words
- Do not include quality tags or artist names unless told to

Output ONLY the caption. No commentary, no explanation, no markdown.""",

    "caption_tags": """You write booru-style tag captions for AI image generation datasets. You are given a description of what an image actually contains. Your job is to extract accurate tags from that description.

CRITICAL: Every tag must correspond to something in the description. Do NOT add tags for content that was not described. Accuracy is everything.

Rules:
- Use standard booru/danbooru tag conventions (underscores between words in multi-word tags)
- Only tag what is actually described — subjects, objects, setting, lighting, style, colors
- Tag all content described accurately
- Do not add tags for content not described
- Order: subject/object tags → appearance/material → setting → lighting → style
- 20-40 tags, comma-separated
- Do not include quality/score tags unless told to

Output ONLY the tags. No commentary, no explanation, no markdown.""",

    "caption_detailed": """You write rich, detailed descriptions of images. You are given a raw description of what an image actually contains. Your job is to rewrite it as vivid, well-crafted prose.

CRITICAL: Only describe what was mentioned in the provided description. Do not invent details. Match the content, not your assumptions.

Rules:
- Write 2-4 sentences of flowing, vivid prose
- Include all details from the source description
- Write about what IS described
- Include artistic style, mood, lighting, composition as described

Output ONLY the description. No commentary, no labels, no markdown.""",

    # ── Creative caption prompts (--creative flag) ─────────────

    "caption_training_creative": """You write evocative, atmospheric image captions. You will be given a factual description of an image. Your job is to rewrite that SAME content — same subject, same setting, same objects — but with vivid atmosphere and artistic depth.

GROUNDING RULE: Every subject, object, and setting element in your caption MUST come from the provided description. If the description says "crystals on a pipe," your caption is about crystals on a pipe — made poetic and alive, but still crystals on a pipe. If the description says "a warrior on a throne," your caption is about that warrior — made vivid and atmospheric. You amplify what exists. You do not replace it.

What you ADD:
- Sensory texture: the way light catches surfaces, the weight of shadow, the feel of materials
- Atmosphere: tension, mystery, foreboding, the feeling of being watched
- Implication: what the scene suggests beyond what it literally shows
- Rich detail: bring every described element to vivid life

Keep to one paragraph, 50-150 words, natural flowing language.
Output ONLY the caption. No commentary, no explanation, no markdown.""",

    "caption_tags_creative": """You write expressive booru-style tags for images, with creative license. You will be given a factual description of an image. Your job is to tag what is described, then add mood and atmosphere tags.

GROUNDING RULE: All subject, object, and setting tags MUST come from the description. If there is no person described, do not add character tags. Start with literal tags, then layer on mood.

Rules:
- Use standard booru/danbooru tag conventions
- First half: literal tags for what is described (subjects, objects, setting, colors, style)
- Second half: atmosphere and mood tags (dark_fantasy, eerie, dramatic, foreboding, etc.)
- Tag all described content accurately, then add mood tags
- 30-50 tags, comma-separated

Output ONLY the tags. No commentary, no explanation, no markdown.""",

    "caption_detailed_creative": """You write vivid, atmospheric descriptions of images. You will be given a factual description of an image. Your job is to rewrite that SAME content as rich, immersive prose.

GROUNDING RULE: Your description must be about the same subject and setting as the provided description. If it describes crystals, you write about crystals — as if they were alive, as if they hummed with energy. If it describes a person, you write about them — their presence, their expression, the weight of their gaze. You transform what exists. You do not replace it.

Rules:
- Write 2-4 sentences of vivid, sensory prose
- Add texture, tension, atmosphere, drama — make the scene breathe
- Include all details from the description vividly
- Make the scene feel immediate and cinematic

Output ONLY the description. No commentary, no labels, no markdown.""",
}


# ── API ────────────────────────────────────────────────────────

def call_ollama(system_prompt: str, user_message: str, max_tokens: int = 1024,
                    model: str = None) -> str:
    """Call an Ollama model via OpenAI-compatible API."""
    model = model or OLLAMA_MODEL

    # Append /no_think to suppress qwen3 reasoning blocks
    if isinstance(user_message, str) and "/no_think" not in user_message:
        user_message = user_message.rstrip() + " /no_think"

    # Build messages — user_message can be a string or a list (for multimodal)
    if isinstance(user_message, str):
        user_content = user_message
    else:
        # Multimodal content list (text + images)
        user_content = user_message

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.85,
        "top_p": 0.9,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            # Strip any residual <think> blocks
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:]
            return content.strip()
    except urllib.error.URLError as e:
        print(f"Error connecting to Ollama at {OLLAMA_HOST}: {e}", file=sys.stderr)
        print("The model may be loading from network storage. Try again in 30-60 seconds.",
              file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"Error parsing Ollama response: {e}", file=sys.stderr)
        sys.exit(1)


def call_vision(system_prompt: str, user_text: str, image_b64: str,
                mime_type: str = "image/png", max_tokens: int = 1024) -> str:
    """Call a vision model with an image via native Ollama /api/chat endpoint.

    Uses the native API because Ollama's OpenAI-compatible endpoint has inconsistent
    multimodal support across model families. The native API with the 'images' field
    works reliably for all vision models.
    """
    native_url = f"{OLLAMA_HOST}/api/chat"

    # Build system+user message with image attached to the user message
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text, "images": [image_b64]},
    ]

    payload = json.dumps({
        "model": OLLAMA_VISION_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.85,
            "top_p": 0.9,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        native_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
            content = data.get("message", {}).get("content", "")
            # Strip any residual <think> blocks
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:]
            return content.strip()
    except urllib.error.URLError as e:
        print(f"Error connecting to Ollama vision model at {OLLAMA_HOST}: {e}",
              file=sys.stderr)
        print("The vision model may be loading. Try again in 30-60 seconds.",
              file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"Error parsing Ollama vision response: {e}", file=sys.stderr)
        sys.exit(1)


# ── Image Helpers ──────────────────────────────────────────────

def encode_image(path: str) -> tuple[str, str]:
    """Read an image file and return (base64_data, mime_type)."""
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
    }
    mime_type = mime_map.get(ext, "image/png")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, mime_type


def find_images(path: str) -> list[str]:
    """Find all image files in a directory, sorted."""
    files = []
    for ext in IMAGE_EXTENSIONS:
        files.extend(glob.glob(os.path.join(path, f"*{ext}")))
        files.extend(glob.glob(os.path.join(path, f"*{ext.upper()}")))
    return sorted(set(files))


# ── Commands ───────────────────────────────────────────────────

def cmd_prompt(args):
    """Generate a detailed image prompt from a concept."""
    encoder = args.encoder or "t5"
    system_key = f"prompt_{encoder}"
    system_prompt = SYSTEM_PROMPTS[system_key]

    if encoder == "clip":
        user_msg = (
            f"Generate a detailed image prompt in tag/keyword style for this concept:\n\n"
            f"{args.concept}\n\n"
            f"Output comma-separated tags only."
        )
    else:
        user_msg = (
            f"Generate a detailed image prompt in natural language for this concept:\n\n"
            f"{args.concept}\n\n"
            f"Output one flowing paragraph only."
        )

    result = call_ollama(system_prompt, user_msg)
    print(result)


def cmd_enhance(args):
    """Enhance an existing prompt with more detail."""
    intensity_instructions = {
        "mild": "Add subtle atmospheric and sensory details. Enhance lighting, texture, and mood.",
        "moderate": "Significantly expand detail — richer descriptions, stronger atmosphere, more precise visual language.",
        "extreme": "Maximum creative expansion — transform every element with vivid, layered, immersive detail.",
    }
    intensity = args.intensity or "moderate"
    instruction = intensity_instructions.get(intensity, intensity_instructions["moderate"])

    user_msg = (
        f"Enhance this image prompt with more detail.\n\n"
        f"Intensity: {intensity.upper()} — {instruction}\n\n"
        f"Original prompt:\n{args.prompt}\n\n"
        f"Rewrite the full prompt with richer detail. Keep the same format and style."
    )

    result = call_ollama(SYSTEM_PROMPTS["enhance"], user_msg)
    print(result)


def cmd_describe(args):
    """Generate a model card description."""
    tags_str = f"\nContent tags: {args.tags}" if args.tags else ""
    user_msg = (
        f"Write a model card description for this AI model:\n\n"
        f"Model name: {args.model_name}\n"
        f"Type: {args.type}{tags_str}\n\n"
        f"Write an engaging description. Be specific about what it generates and how to use it."
    )

    result = call_ollama(SYSTEM_PROMPTS["describe"], user_msg, max_tokens=2048)
    print(result)


def cmd_lore(args):
    """Generate creative fiction or lore."""
    length_tokens = {"short": 512, "medium": 1024, "long": 2048}
    tokens = length_tokens.get(args.length or "medium", 1024)

    user_msg = (
        f"Write a {args.length or 'medium'}-length creative scene or lore entry:\n\n"
        f"{args.scenario}\n\n"
        f"Be vivid and detailed."
    )

    result = call_ollama(SYSTEM_PROMPTS["lore"], user_msg, max_tokens=tokens)
    print(result)


def cmd_caption(args):
    """Caption one or more images using a two-stage vision pipeline.

    Two-stage pipeline:
    1. Vision model analyzes the image (raw, clinical description)
    2. Text model refines into the requested caption style

    --creative: Embellishes with atmosphere, mood, and sensory richness.
    Without it: faithful to what the vision model sees. Accuracy over artistry.
    """
    path = args.path
    style = args.style or "training"
    trigger = args.trigger
    prefix = args.prefix
    creative = args.creative

    # Determine if single file or directory
    if os.path.isdir(path):
        images = find_images(path)
        if not images:
            print(f"No image files found in {path}", file=sys.stderr)
            sys.exit(1)
        mode = "creative" if creative else "accurate"
        print(f"Found {len(images)} images in {path} (mode: {mode})", file=sys.stderr)
        batch_caption(images, style, trigger, prefix, creative, args.overwrite)
    elif os.path.isfile(path):
        caption = caption_single(path, style, trigger, prefix, creative)
        print(caption)
    else:
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)


def caption_single(image_path: str, style: str, trigger: str = None,
                   prefix: str = None, creative: bool = False) -> str:
    """Caption a single image. Returns the caption text."""
    image_b64, mime_type = encode_image(image_path)

    # Stage 1: Vision model — raw description
    raw_description = call_vision(
        SYSTEM_PROMPTS["vision_raw"],
        "Describe this image in precise, thorough detail.",
        image_b64,
        mime_type,
        max_tokens=1024,
    )

    # Stage 2: Text model — refine to requested style
    # Creative mode uses the embellished prompts; default uses accurate ones
    style_key = f"caption_{style}_creative" if creative else f"caption_{style}"
    if style_key not in SYSTEM_PROMPTS:
        style_key = f"caption_{style}"
    if style_key not in SYSTEM_PROMPTS:
        style_key = "caption_training"

    extra_instructions = ""
    if trigger:
        extra_instructions += f"\nIMPORTANT: Include the trigger word '{trigger}' naturally in the caption."
    if prefix:
        extra_instructions += f"\nStart the caption with: {prefix}"

    user_msg = (
        f"Here is a factual description of the image you must caption:\n\n"
        f"---BEGIN DESCRIPTION---\n"
        f"{raw_description}\n"
        f"---END DESCRIPTION---\n\n"
        f"Write a {style} caption based ONLY on the content described above.{extra_instructions}"
    )

    caption = call_ollama(SYSTEM_PROMPTS[style_key], user_msg, max_tokens=512)

    return caption


def batch_caption(images: list[str], style: str, trigger: str = None,
                  prefix: str = None, creative: bool = False,
                  overwrite: bool = False):
    """Caption a batch of images, writing .txt files alongside each."""
    total = len(images)
    written = 0
    skipped = 0

    for i, image_path in enumerate(images, 1):
        # Output path: same name with .txt extension
        base = os.path.splitext(image_path)[0]
        txt_path = base + ".txt"

        # Skip if caption already exists and not overwriting
        if os.path.exists(txt_path) and not overwrite:
            print(f"[{i}/{total}] SKIP (exists): {os.path.basename(image_path)}",
                  file=sys.stderr)
            skipped += 1
            continue

        print(f"[{i}/{total}] Captioning: {os.path.basename(image_path)}",
              file=sys.stderr)

        try:
            caption = caption_single(image_path, style, trigger, prefix, creative)
            with open(txt_path, "w") as f:
                f.write(caption + "\n")
            written += 1
            # Show the caption on stdout for visibility
            print(f"  → {txt_path}: {caption[:100]}{'...' if len(caption) > 100 else ''}",
                  file=sys.stderr)
        except Exception as e:
            print(f"  ✗ Error: {e}", file=sys.stderr)

    print(f"\nDone: {written} written, {skipped} skipped, "
          f"{total - written - skipped} errors", file=sys.stderr)


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Local LLM generation via Ollama — captions, prompts, descriptions."
    )
    subparsers = parser.add_subparsers(dest="command", help="Action to perform")

    # prompt
    p_prompt = subparsers.add_parser("prompt", help="Generate a detailed image prompt")
    p_prompt.add_argument("concept", help="Concept to generate a prompt for")
    p_prompt.add_argument(
        "--encoder", "-e", choices=["clip", "t5"], default="t5",
        help="Target encoder: clip (SDXL/Pony tags) or t5 (Flux prose). Default: t5"
    )

    # enhance
    p_enhance = subparsers.add_parser("enhance", help="Enhance an existing prompt with more detail")
    p_enhance.add_argument("prompt", help="Safe/censored prompt to enhance")
    p_enhance.add_argument(
        "--intensity", "-i", choices=["mild", "moderate", "extreme"], default="moderate",
        help="Detail intensity level. Default: moderate"
    )

    # describe
    p_describe = subparsers.add_parser("describe", help="Write a model card description")
    p_describe.add_argument("model_name", help="Model name")
    p_describe.add_argument(
        "--type", "-t", required=True,
        help="LoRA type (e.g., character, style, concept, pose, clothing, world-morph)"
    )
    p_describe.add_argument("--tags", help="Comma-separated content tags")

    # lore
    p_lore = subparsers.add_parser("lore", help="Generate creative fiction or lore")
    p_lore.add_argument("scenario", help="Scene or scenario to write")
    p_lore.add_argument(
        "--length", "-l", choices=["short", "medium", "long"], default="medium",
        help="Output length. Default: medium"
    )

    # caption
    p_caption = subparsers.add_parser(
        "caption",
        help="Caption images via two-stage vision pipeline"
    )
    p_caption.add_argument(
        "path",
        help="Image file or directory of images to caption"
    )
    p_caption.add_argument(
        "--style", "-s",
        choices=["training", "tags", "detailed"],
        default="training",
        help="Caption style. training: natural language for Flux/T5. "
             "tags: booru-style for SDXL/Pony. detailed: rich prose. Default: training"
    )
    p_caption.add_argument(
        "--trigger", "-t",
        help="Trigger word to include in every caption (for LoRA training)"
    )
    p_caption.add_argument(
        "--prefix", "-p",
        help="Prefix to prepend to every caption"
    )
    p_caption.add_argument(
        "--creative", "-c",
        action="store_true",
        help="Embellish with atmosphere and creative detail (default: accurate/faithful)"
    )
    p_caption.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .txt caption files (default: skip)"
    )

    args = parser.parse_args()

    if args.command == "prompt":
        cmd_prompt(args)
    elif args.command == "enhance":
        cmd_enhance(args)
    elif args.command == "describe":
        cmd_describe(args)
    elif args.command == "lore":
        cmd_lore(args)
    elif args.command == "caption":
        cmd_caption(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
