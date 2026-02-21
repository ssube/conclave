---
name: web-browse
description: >-
  Browse the web — take screenshots, extract text, inspect page elements, and
  execute JavaScript using Playwright. Use when visiting a webpage, taking a
  screenshot, extracting text, discovering page structure, or running JS on a site.
---

# Web Browse Skill

Load URLs in a headless browser and extract visual, textual, or structural content.

## Actions

### Screenshot — Visual capture

```bash
python3 {baseDir}/browse.py screenshot <url> [options]
```

Options:
- `--output <path>` — Save screenshot to file (default: `/tmp/screenshot-<timestamp>.png`)
- `--width <px>` — Viewport width (default: 1280)
- `--height <px>` — Viewport height (default: 800)
- `--full-page` — Capture full scrollable page, not just viewport
- `--wait <ms>` — Wait time after page load before capture (default: 2000)
- `--selector <css>` — Screenshot only a specific element

### Text — Content extraction

```bash
python3 {baseDir}/browse.py text <url> [options]
```

Options:
- `--output <path>` — Save text to file (default: stdout)
- `--selector <css>` — Extract text from specific element only
- `--wait <ms>` — Wait time after page load (default: 2000)
- `--links` — Include href URLs in output
- `--max-length <chars>` — Truncate output (default: 50000)

### Inspect — Element discovery

Discover all interactive elements on a page — buttons, links, inputs, forms.
Useful for debugging Playwright automation or understanding a page's structure.

```bash
python3 {baseDir}/browse.py inspect <url> [options]
```

Options:
- `--wait <ms>` — Wait time after page load (default: 2000)
- `--width <px>` — Viewport width (default: 1280)
- `--console` — Capture and display browser console output
- `--screenshot <path>` — Also save a full-page screenshot
- `--json` — Output element data as JSON (for programmatic use)

### Execute — Run JavaScript

Execute a JavaScript expression on a loaded page and return the result.

```bash
python3 {baseDir}/browse.py execute <url> "<script>" [options]
```

Options:
- `--wait <ms>` — Wait time after page load (default: 2000)

## Examples

```bash
# Screenshot a web page
python3 {baseDir}/browse.py screenshot "https://example.com" --output /tmp/example.png

# Full-page screenshot
python3 {baseDir}/browse.py screenshot "https://example.com" --full-page --output /tmp/site.png

# Extract text from a page
python3 {baseDir}/browse.py text "https://example.com/article" --max-length 10000

# Extract text with links
python3 {baseDir}/browse.py text "https://github.com/example/repo" --links

# Discover all interactive elements on a page
python3 {baseDir}/browse.py inspect "https://example.com/form"

# Inspect with console capture and screenshot
python3 {baseDir}/browse.py inspect "https://example.com" --console --screenshot /tmp/inspect.png

# Inspect and get JSON output for scripting
python3 {baseDir}/browse.py inspect "https://example.com/form" --json

# Execute JavaScript to extract specific data
python3 {baseDir}/browse.py execute "https://example.com" "document.querySelectorAll('img').length"

# Get page metadata via JS
python3 {baseDir}/browse.py execute "https://example.com" \
  "JSON.stringify({title: document.title, links: document.querySelectorAll('a').length})"
```

## Reconnaissance Pattern

For debugging automation or understanding unfamiliar pages:

1. **Inspect** — discover all elements:
   ```bash
   python3 {baseDir}/browse.py inspect "https://platform.com/upload" --console --screenshot /tmp/recon.png
   ```
2. **Read the screenshot** — verify visual state matches expectations
3. **Identify selectors** — from the inspect output, find the right buttons/inputs
4. **Execute** — test selectors with JavaScript:
   ```bash
   python3 {baseDir}/browse.py execute "https://platform.com/upload" \
     "document.querySelector('button[type=submit]')?.innerText"
   ```

## Notes

- Uses headless Chromium via Playwright (no GUI required)
- Screenshots are PNG format, suitable for vision analysis via the Read tool
- Text extraction strips HTML tags and returns clean content
- JavaScript renders fully before capture (configurable wait time)
- Navigation falls back from `networkidle` to `load` on timeout
- No authentication — for authenticated sites, use platform-specific skills

## Troubleshooting

### Page load timeout
Some pages are slow or have infinite network activity. Try increasing `--wait`
or the page may be blocking headless browsers.

### Selector not found
Verify the selector with `inspect` first. Dynamic pages may load elements after
the initial `networkidle` state — increase `--wait`.

### Console shows errors
Use `inspect --console` to see what the page is complaining about. Common:
CORS errors (expected for cross-origin resources), missing APIs (page expects auth).
