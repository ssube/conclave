#!/usr/bin/env python3
"""
Image Optimize Skill

Resize, compress, and format images for platform-specific requirements.
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow not installed. Run: pip install Pillow")
    sys.exit(1)


# Platform specifications
PLATFORM_SPECS = {
    "twitter": {
        "max_size": 5 * 1024 * 1024,  # 5MB
        "max_width": 4096,
        "max_height": 4096,
        "formats": ["PNG", "JPEG", "WEBP"],
        "default_format": "JPEG",
        "default_quality": 85
    },
    "bluesky": {
        "max_size": 1 * 1024 * 1024,  # 1MB
        "max_width": 2000,
        "max_height": 2000,
        "formats": ["PNG", "JPEG", "WEBP"],
        "default_format": "JPEG",
        "default_quality": 80
    },
    "gallery": {
        "max_size": 16 * 1024 * 1024,  # 16MB
        "max_width": 4096,
        "max_height": 4096,
        "formats": ["PNG", "JPEG", "WEBP"],
        "default_format": "PNG",
        "default_quality": 90
    },
    "deviantart": {
        "max_size": 30 * 1024 * 1024,  # 30MB
        "max_width": 16000,
        "max_height": 16000,
        "formats": ["PNG", "JPEG", "GIF"],
        "default_format": "PNG",
        "default_quality": 95
    },
    "patreon": {
        "max_size": 10 * 1024 * 1024,  # 10MB
        "max_width": 5000,
        "max_height": 5000,
        "formats": ["PNG", "JPEG", "GIF"],
        "default_format": "JPEG",
        "default_quality": 85
    },
    "tumblr": {
        "max_size": 10 * 1024 * 1024,  # 10MB
        "max_width": 4096,
        "max_height": 4096,
        "formats": ["PNG", "JPEG", "GIF"],
        "default_format": "JPEG",
        "default_quality": 85
    }
}


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_image_info(path: Path) -> dict:
    """Get image information."""
    with Image.open(path) as img:
        stat = path.stat()
        return {
            "path": str(path),
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "file_size": stat.st_size,
            "file_size_human": format_size(stat.st_size)
        }


def check_platform_compatibility(info: dict, platform: str) -> dict:
    """Check if image is compatible with platform."""
    spec = PLATFORM_SPECS.get(platform)
    if not spec:
        return {"compatible": False, "reason": "unknown platform"}

    result = {"compatible": True, "action": None, "reasons": []}

    # Check dimensions
    if info["width"] > spec["max_width"] or info["height"] > spec["max_height"]:
        result["compatible"] = False
        result["action"] = "resize"
        result["reasons"].append(f"exceeds {spec['max_width']}x{spec['max_height']}")

    # Check file size
    if info["file_size"] > spec["max_size"]:
        result["compatible"] = False
        if result["action"] != "resize":
            result["action"] = "compress"
        result["reasons"].append(f"exceeds {format_size(spec['max_size'])}")

    # Check format
    if info["format"] and info["format"].upper() not in spec["formats"]:
        result["compatible"] = False
        result["action"] = "convert"
        result["reasons"].append(f"format {info['format']} not supported")

    if result["reasons"]:
        result["reason"] = "; ".join(result["reasons"])
    else:
        result.pop("reasons")

    return result


def resize_image(img: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """Resize image to fit within max dimensions while maintaining aspect ratio."""
    if img.width <= max_width and img.height <= max_height:
        return img

    ratio = min(max_width / img.width, max_height / img.height)
    new_width = int(img.width * ratio)
    new_height = int(img.height * ratio)

    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def save_image(img: Image.Image, output_path: Path, format: str, quality: int) -> int:
    """Save image and return file size."""
    save_kwargs = {}

    if format.upper() in ["JPEG", "JPG"]:
        format = "JPEG"
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
        # Convert RGBA to RGB for JPEG
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
    elif format.upper() == "WEBP":
        save_kwargs["quality"] = quality
        save_kwargs["method"] = 6  # Best compression
    elif format.upper() == "PNG":
        save_kwargs["optimize"] = True

    img.save(output_path, format=format, **save_kwargs)
    return output_path.stat().st_size


def optimize_for_platform(input_path: Path, output_path: Path, platform: str,
                          target_format: str = None, quality: int = None) -> dict:
    """Optimize image for a specific platform."""
    spec = PLATFORM_SPECS.get(platform)
    if not spec:
        raise ValueError(f"Unknown platform: {platform}")

    with Image.open(input_path) as img:
        original_size = input_path.stat().st_size
        original_dims = (img.width, img.height)

        # Resize if needed
        img = resize_image(img, spec["max_width"], spec["max_height"])

        # Determine format
        if target_format:
            out_format = target_format.upper()
        elif img.format and img.format.upper() in spec["formats"]:
            out_format = img.format
        else:
            out_format = spec["default_format"]

        # Determine quality
        if quality is None:
            quality = spec["default_quality"]

        # Save with initial quality
        file_size = save_image(img, output_path, out_format, quality)

        # If still too large, iterate with lower quality
        while file_size > spec["max_size"] and quality > 30:
            quality -= 10
            file_size = save_image(img, output_path, out_format, quality)

        return {
            "success": file_size <= spec["max_size"],
            "input_path": str(input_path),
            "output_path": str(output_path),
            "original_size": original_size,
            "original_dims": original_dims,
            "final_size": file_size,
            "final_dims": (img.width, img.height),
            "format": out_format,
            "quality": quality,
            "platform": platform
        }


def cmd_resize(args):
    """Resize image for platform."""
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1

    if args.platform not in PLATFORM_SPECS:
        print(f"Error: Unknown platform: {args.platform}")
        print(f"Available: {', '.join(PLATFORM_SPECS.keys())}")
        return 1

    if args.output:
        output_path = Path(args.output)
    else:
        # Add platform suffix
        output_path = input_path.parent / f"{input_path.stem}_{args.platform}{input_path.suffix}"

    result = optimize_for_platform(
        input_path, output_path, args.platform,
        target_format=args.format,
        quality=args.quality
    )

    if args.format_output == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Input:  {result['input_path']}")
        print(f"        {result['original_dims'][0]}x{result['original_dims'][1]}, {format_size(result['original_size'])}")
        print(f"Output: {result['output_path']}")
        print(f"        {result['final_dims'][0]}x{result['final_dims'][1]}, {format_size(result['final_size'])}")
        print(f"Format: {result['format']}, Quality: {result['quality']}")
        if result['success']:
            print(f"Status: OK - ready for {args.platform}")
        else:
            print(f"Status: WARNING - still exceeds size limit")

    return 0 if result['success'] else 1


def cmd_compress(args):
    """Compress image to quality or size."""
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1

    output_path = Path(args.output)
    quality = args.quality

    with Image.open(input_path) as img:
        original_size = input_path.stat().st_size

        # Determine format
        out_format = args.format.upper() if args.format else (img.format or "JPEG")

        file_size = save_image(img, output_path, out_format, quality)

        # If max_size specified, iterate
        if args.max_size:
            while file_size > args.max_size and quality > 10:
                quality -= 5
                file_size = save_image(img, output_path, out_format, quality)

    print(f"Input:  {input_path} ({format_size(original_size)})")
    print(f"Output: {output_path} ({format_size(file_size)})")
    print(f"Quality: {quality}, Reduction: {(1 - file_size/original_size) * 100:.1f}%")

    return 0


def cmd_batch(args):
    """Batch optimize images."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    patterns = args.pattern.split(",")
    files = []
    for pattern in patterns:
        if args.recursive:
            files.extend(input_dir.rglob(pattern.strip()))
        else:
            files.extend(input_dir.glob(pattern.strip()))

    if not files:
        print(f"No files found matching {args.pattern}")
        return 0

    results = {"success": 0, "failed": 0, "files": []}

    for input_path in files:
        rel_path = input_path.relative_to(input_dir)
        output_path = output_dir / rel_path.with_suffix(f".{PLATFORM_SPECS[args.platform]['default_format'].lower()}")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = optimize_for_platform(input_path, output_path, args.platform)
            if result["success"]:
                results["success"] += 1
            else:
                results["failed"] += 1
            results["files"].append(result)
            print(f"  {rel_path}: {format_size(result['original_size'])} -> {format_size(result['final_size'])}")
        except Exception as e:
            results["failed"] += 1
            print(f"  {rel_path}: ERROR - {e}")

    print(f"\nProcessed: {results['success']} success, {results['failed']} failed")
    return 0 if results["failed"] == 0 else 1


def cmd_info(args):
    """Get image information."""
    path = Path(args.path)
    if not path.exists():
        print(f"Error: File not found: {path}")
        return 1

    info = get_image_info(path)

    if args.check_platforms:
        info["platforms"] = {}
        for platform in PLATFORM_SPECS:
            info["platforms"][platform] = check_platform_compatibility(info, platform)

    if args.format == "json":
        print(json.dumps(info, indent=2))
    else:
        print(f"Image: {info['path']}")
        print(f"  Dimensions: {info['width']}x{info['height']}")
        print(f"  Format: {info['format']}")
        print(f"  Mode: {info['mode']}")
        print(f"  File Size: {info['file_size_human']}")

        if args.check_platforms:
            print(f"\nPlatform Compatibility:")
            for platform, compat in info["platforms"].items():
                status = "OK" if compat["compatible"] else compat["action"].upper()
                reason = f" ({compat.get('reason', '')})" if not compat["compatible"] else ""
                print(f"  {platform:14} {status}{reason}")

    return 0


def cmd_convert(args):
    """Convert image format."""
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1

    output_path = Path(args.output)
    target_format = args.format.upper()

    with Image.open(input_path) as img:
        save_image(img, output_path, target_format, args.quality)

    print(f"Converted: {input_path} -> {output_path}")
    return 0


# ── Watermark ─────────────────────────────────────────────────────────────────

# Default watermark assets — configure with your own logo paths
DEFAULT_WATERMARKS = {}

# Corner positions
CORNER_POSITIONS = {
    "bottom-right": lambda iw, ih, ww, wh, m: (iw - ww - m, ih - wh - m),
    "bottom-left":  lambda iw, ih, ww, wh, m: (m, ih - wh - m),
    "top-right":    lambda iw, ih, ww, wh, m: (iw - ww - m, m),
    "top-left":     lambda iw, ih, ww, wh, m: (m, m),
}


def prepare_watermark(logo_path: str, target_size: int, opacity: float) -> Image.Image:
    """Load a watermark logo, make it transparent, and resize.

    Handles both RGBA images (uses existing alpha) and RGB images with black
    backgrounds (converts black to transparent using luminance thresholding).
    """
    logo = Image.open(logo_path).convert("RGBA")

    # Check if alpha channel is actually used (non-trivial)
    alpha = logo.split()[3]
    alpha_min, alpha_max = alpha.getextrema()

    if alpha_min == alpha_max == 255:
        # No real transparency — assume black background, create alpha from luminance
        r, g, b, _ = logo.split()
        # Luminance: brighter pixels are more opaque
        lum = Image.eval(r, lambda x: x)  # Start with red channel
        # Combine channels for proper luminance
        import numpy as np
        arr = np.array(logo)
        # Luminance from RGB
        lum_arr = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype("uint8")
        # Use luminance as alpha (black=transparent, bright=opaque)
        arr[:, :, 3] = lum_arr
        logo = Image.fromarray(arr)

    # Resize to target size (maintain aspect ratio)
    ratio = target_size / max(logo.width, logo.height)
    new_w = int(logo.width * ratio)
    new_h = int(logo.height * ratio)
    logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Apply opacity
    if opacity < 1.0:
        r, g, b, a = logo.split()
        a = Image.eval(a, lambda x: int(x * opacity))
        logo = Image.merge("RGBA", (r, g, b, a))

    return logo


def apply_watermark(
    img: Image.Image,
    logo: Image.Image,
    position: str = "bottom-right",
    margin_pct: float = 2.0,
) -> Image.Image:
    """Composite a prepared watermark onto an image.

    Args:
        img: Source image (will be converted to RGBA for compositing)
        logo: Prepared watermark from prepare_watermark()
        position: Corner placement (bottom-right, bottom-left, top-right, top-left)
        margin_pct: Margin from edge as percentage of image width

    Returns:
        Composited image in RGBA mode
    """
    img = img.convert("RGBA")
    margin = int(img.width * margin_pct / 100)

    pos_fn = CORNER_POSITIONS.get(position, CORNER_POSITIONS["bottom-right"])
    x, y = pos_fn(img.width, img.height, logo.width, logo.height, margin)

    # Create a transparent layer and paste the logo onto it
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay.paste(logo, (x, y))

    return Image.alpha_composite(img, overlay)


def watermark_single(
    input_path: Path,
    output_path: Path,
    logo_path: str,
    size_pct: float = 5.0,
    opacity: float = 0.4,
    position: str = "bottom-right",
    margin_pct: float = 2.0,
) -> dict:
    """Watermark a single image.

    Args:
        input_path: Source image
        output_path: Destination
        logo_path: Path to watermark logo
        size_pct: Logo size as percentage of image width
        opacity: Logo opacity (0.0 = invisible, 1.0 = fully opaque)
        position: Corner placement
        margin_pct: Edge margin as percentage of image width

    Returns:
        Result dict with paths and dimensions
    """
    with Image.open(input_path) as img:
        original_format = img.format or "PNG"
        target_size = int(img.width * size_pct / 100)
        logo = prepare_watermark(logo_path, target_size, opacity)
        result = apply_watermark(img, logo, position, margin_pct)

        # Determine output format from extension
        ext = output_path.suffix.lower()
        if ext in [".jpg", ".jpeg"]:
            # Flatten alpha for JPEG
            bg = Image.new("RGB", result.size, (0, 0, 0))
            bg.paste(result, mask=result.split()[3])
            bg.save(output_path, "JPEG", quality=95, optimize=True)
        elif ext == ".webp":
            result.save(output_path, "WEBP", quality=95)
        else:
            result.save(output_path, "PNG", optimize=True)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "logo": logo_path,
        "logo_size": target_size,
        "opacity": opacity,
        "position": position,
    }


def cmd_watermark(args):
    """Add watermark to image(s)."""
    # Resolve logo path
    logo_path = args.logo
    if logo_path in DEFAULT_WATERMARKS:
        logo_path = DEFAULT_WATERMARKS[logo_path]
    if not Path(logo_path).exists():
        print(f"Error: Logo not found: {logo_path}")
        return 1

    input_path = Path(args.input)

    if input_path.is_dir():
        # Batch mode
        output_dir = Path(args.output) if args.output else input_path / "watermarked"
        output_dir.mkdir(parents=True, exist_ok=True)

        patterns = ["*.png", "*.jpg", "*.jpeg", "*.webp"]
        files = []
        for p in patterns:
            files.extend(input_path.glob(p))

        if not files:
            print("No image files found.")
            return 0

        count = 0
        for f in sorted(files):
            out = output_dir / f.name
            try:
                watermark_single(f, out, logo_path, args.size, args.opacity,
                                 args.position, args.margin)
                count += 1
                print(f"  ✅ {f.name}")
            except Exception as e:
                print(f"  ❌ {f.name}: {e}")

        print(f"\nWatermarked {count}/{len(files)} images → {output_dir}")
    else:
        # Single file
        if not input_path.exists():
            print(f"Error: File not found: {input_path}")
            return 1

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = input_path.parent / f"{input_path.stem}_wm{input_path.suffix}"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = watermark_single(input_path, output_path, logo_path,
                                  args.size, args.opacity, args.position, args.margin)
        print(f"Watermarked: {result['input']} → {result['output']}")
        print(f"  Logo: {Path(result['logo']).name} ({result['logo_size']}px, {result['opacity']*100:.0f}% opacity)")
        print(f"  Position: {result['position']}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Image optimization for social platforms")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Resize command
    resize_parser = subparsers.add_parser("resize", help="Resize for platform")
    resize_parser.add_argument("--input", required=True, help="Input image path")
    resize_parser.add_argument("--platform", required=True, choices=list(PLATFORM_SPECS.keys()))
    resize_parser.add_argument("--output", help="Output path")
    resize_parser.add_argument("--format", help="Output format")
    resize_parser.add_argument("--quality", type=int, help="Quality 1-100")
    resize_parser.add_argument("--format-output", choices=["text", "json"], default="text")

    # Compress command
    compress_parser = subparsers.add_parser("compress", help="Compress image")
    compress_parser.add_argument("--input", required=True, help="Input path")
    compress_parser.add_argument("--output", required=True, help="Output path")
    compress_parser.add_argument("--quality", type=int, default=85, help="Quality 1-100")
    compress_parser.add_argument("--max-size", type=int, help="Max file size in bytes")
    compress_parser.add_argument("--format", help="Output format")

    # Batch command
    batch_parser = subparsers.add_parser("batch", help="Batch optimize")
    batch_parser.add_argument("--input-dir", required=True, help="Input directory")
    batch_parser.add_argument("--output-dir", required=True, help="Output directory")
    batch_parser.add_argument("--platform", required=True, choices=list(PLATFORM_SPECS.keys()))
    batch_parser.add_argument("--pattern", default="*.png,*.jpg,*.jpeg,*.webp", help="File pattern")
    batch_parser.add_argument("--recursive", action="store_true", help="Process subdirectories")

    # Info command
    info_parser = subparsers.add_parser("info", help="Get image info")
    info_parser.add_argument("path", help="Image path")
    info_parser.add_argument("--format", choices=["text", "json"], default="text")
    info_parser.add_argument("--check-platforms", action="store_true", help="Check platform compatibility")

    # Convert command
    convert_parser = subparsers.add_parser("convert", help="Convert format")
    convert_parser.add_argument("--input", required=True, help="Input path")
    convert_parser.add_argument("--output", required=True, help="Output path")
    convert_parser.add_argument("--format", required=True, choices=["png", "jpg", "jpeg", "webp", "gif"])
    convert_parser.add_argument("--quality", type=int, default=90, help="Quality for lossy formats")

    # Watermark command
    wm_parser = subparsers.add_parser("watermark", help="Add watermark")
    wm_parser.add_argument("--input", required=True, help="Input image or directory")
    wm_parser.add_argument("--output", help="Output path or directory (default: adds _wm suffix or watermarked/ subdir)")
    wm_parser.add_argument("--logo", required=True,
                           help="Path to watermark logo PNG image")
    wm_parser.add_argument("--size", type=float, default=5.0,
                           help="Logo size as %% of image width (default: 5.0)")
    wm_parser.add_argument("--opacity", type=float, default=0.4,
                           help="Logo opacity 0.0-1.0 (default: 0.4)")
    wm_parser.add_argument("--position", default="bottom-right",
                           choices=["bottom-right", "bottom-left", "top-right", "top-left"],
                           help="Corner placement (default: bottom-right)")
    wm_parser.add_argument("--margin", type=float, default=2.0,
                           help="Edge margin as %% of image width (default: 2.0)")

    args = parser.parse_args()

    if args.command == "resize":
        sys.exit(cmd_resize(args))
    elif args.command == "compress":
        sys.exit(cmd_compress(args))
    elif args.command == "batch":
        sys.exit(cmd_batch(args))
    elif args.command == "info":
        sys.exit(cmd_info(args))
    elif args.command == "convert":
        sys.exit(cmd_convert(args))
    elif args.command == "watermark":
        sys.exit(cmd_watermark(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
