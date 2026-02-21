---
name: image-optimize
description: >-
  Resize, compress, and format images for platform-specific requirements. Use when preparing images for posting, resizing to meet platform limits, compressing file sizes, or converting between image formats.
---

# Image Optimize Skill

Resize, compress, and format images for platform-specific requirements. Uses Pillow for image processing.

## Requirements

```bash
pip install Pillow
```

## Platform Specifications

| Platform | Max Size | Max Dimensions | Formats |
|----------|----------|----------------|---------|
| Twitter | 5MB | 4096x4096 | PNG, JPG, WebP |
| Bluesky | 1MB | 2000x2000 | PNG, JPG, WebP |
| Gallery | 16MB | 4096x4096 | PNG, JPG, WebP |
| DeviantArt | 30MB | 16000x16000 | PNG, JPG, GIF |
| Patreon | 10MB | 5000x5000 | PNG, JPG, GIF |
| Tumblr | 10MB | 4096x4096 | PNG, JPG, GIF |

## Usage

### Resize for platform

```bash
python3 {baseDir}/optimize.py resize \
  --input /path/to/image.png \
  --platform twitter \
  --output /path/to/output.png
```

Automatically resizes and compresses to meet platform requirements.

### Manual compression

```bash
python3 {baseDir}/optimize.py compress \
  --input /path/to/image.png \
  --quality 85 \
  --output /path/to/output.jpg
```

### Batch optimization

```bash
python3 {baseDir}/optimize.py batch \
  --input-dir /path/to/images/ \
  --platform twitter \
  --output-dir /path/to/optimized/
```

### Get image info

```bash
python3 {baseDir}/optimize.py info /path/to/image.png
```

Returns dimensions, format, file size, and platform compatibility.

### Convert format

```bash
python3 {baseDir}/optimize.py convert \
  --input /path/to/image.png \
  --format webp \
  --output /path/to/output.webp
```

## Commands

### resize

Resize image to fit platform requirements while maintaining aspect ratio.

Options:
- `--input`: Input image path (required)
- `--platform`: Target platform (required)
- `--output`: Output path (default: adds platform suffix to input name)
- `--format`: Output format (default: same as input or platform default)
- `--quality`: JPEG/WebP quality 1-100 (default: auto for platform)

### compress

Compress image to target quality or file size.

Options:
- `--input`: Input image path (required)
- `--output`: Output path (required)
- `--quality`: Quality 1-100 (default: 85)
- `--max-size`: Maximum file size in bytes (optional, iterates to find quality)
- `--format`: Output format (default: same as input)

### batch

Process multiple images.

Options:
- `--input-dir`: Input directory (required)
- `--output-dir`: Output directory (required)
- `--platform`: Target platform (required)
- `--pattern`: Glob pattern for files (default: `*.png,*.jpg,*.jpeg,*.webp`)
- `--recursive`: Process subdirectories

### info

Get image information.

Options:
- `path`: Image path (required)
- `--format`: Output format: text or json (default: text)
- `--check-platforms`: Check compatibility with all platforms

### convert

Convert between formats.

Options:
- `--input`: Input path (required)
- `--output`: Output path (required)
- `--format`: Target format: png, jpg, webp, gif
- `--quality`: Quality for lossy formats (default: 90)

## Output

### info command (text)

```
Image: portrait.png
  Dimensions: 2048x3072
  Format: PNG
  Mode: RGBA
  File Size: 8.5 MB

Platform Compatibility:
  Twitter:      OK (within limits)
  Bluesky:      RESIZE (exceeds 2000x2000)
  Gallery:      OK
  DeviantArt:   OK
  Patreon:      OK
  Tumblr:        OK
```

### info command (json)

```json
{
  "path": "portrait.png",
  "width": 2048,
  "height": 3072,
  "format": "PNG",
  "mode": "RGBA",
  "file_size": 8912345,
  "file_size_human": "8.5 MB",
  "platforms": {
    "twitter": {"compatible": true, "action": null},
    "bluesky": {"compatible": false, "action": "resize", "reason": "exceeds 2000x2000"}
  }
}
```

### Watermark

Add a watermark to images for recognition and theft prevention.

```bash
# Single image with custom logo
python3 {baseDir}/optimize.py watermark \
  --input /path/to/image.png \
  --logo /path/to/logo.png

# Batch watermark an entire directory
python3 {baseDir}/optimize.py watermark \
  --input /path/to/images/ \
  --output /path/to/watermarked/ \
  --logo /path/to/logo.png

# Custom size, opacity, and position
python3 {baseDir}/optimize.py watermark \
  --input /path/to/image.png \
  --logo /path/to/logo.png \
  --size 8 --opacity 0.5 --position top-right
```

Options:
- `--input`: Image path or directory (required)
- `--output`: Output path/directory (default: `_wm` suffix or `watermarked/` subdir)
- `--logo`: Path to a PNG watermark image (required)
- `--size`: Logo size as % of image width (default: 5.0)
- `--opacity`: 0.0 (invisible) to 1.0 (fully opaque) (default: 0.4)
- `--position`: `bottom-right` (default), `bottom-left`, `top-right`, `top-left`
- `--margin`: Edge margin as % of image width (default: 2.0)

## Examples

```bash
# Prepare image for Twitter
python3 {baseDir}/optimize.py resize --input render.png --platform twitter

# Check if image needs optimization
python3 {baseDir}/optimize.py info render.png --check-platforms

# Compress to specific quality
python3 {baseDir}/optimize.py compress --input large.png --quality 75 --output compressed.jpg

# Batch optimize a folder for Bluesky
python3 {baseDir}/optimize.py batch \
  --input-dir ./renders/ \
  --output-dir ./optimized/ \
  --platform bluesky

# Convert PNG to WebP
python3 {baseDir}/optimize.py convert --input image.png --format webp --output image.webp
```

## Quality Guidelines

| Use Case | Recommended Quality |
|----------|---------------------|
| Artwork/Portfolio | 90-95 |
| Social media posts | 80-85 |
| Thumbnails | 70-75 |
| Quick previews | 60-70 |

## Troubleshooting

### Image too large after optimization
Try lowering `--quality` or converting to WebP which has better compression.

### Color shift after save
Some images with ICC profiles may shift. Use `--preserve-metadata` if available.

### Transparency lost
PNG to JPG conversion removes transparency. Use WebP or keep PNG format.
