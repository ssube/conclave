---
name: browser-connect
description: >-
  Connect to the Chromium browser via CDP (Chrome DevTools Protocol) for
  automation, screenshots, and cookie management. Use when you need to
  interact with web pages, capture screenshots, or automate browser tasks.
---

# Browser Connect Skill

Connect to the local Chromium browser via CDP for automation. The browser runs
inside Conclave with CDP enabled on `127.0.0.1:9222`.

## Usage

### Test the connection

```bash
python3 {baseDir}/browser_connect.py test
```

### Take a screenshot

```bash
python3 {baseDir}/browser_connect.py screenshot [--output /path/to/screenshot.png]
```

### List cookies

```bash
python3 {baseDir}/browser_connect.py cookies
```

## Python API

```python
from browser_connect import BrowserSession

with BrowserSession() as (browser, page):
    page.goto("https://example.com")
    page.screenshot(path="screenshot.png")
```

## Environment Variables

- `CDP_HOST`: CDP host (default: `127.0.0.1`)
- `CDP_PORT`: CDP port (default: `9222`)

## Troubleshooting

### Connection refused
- Verify Chromium is running: `curl http://127.0.0.1:9222/json/version`
- Check the N.eko desktop service is started

### Page not loading
- The browser shares state with the N.eko desktop — if a user is active, pages may already be open
- Use `page.goto()` to navigate to the desired URL
