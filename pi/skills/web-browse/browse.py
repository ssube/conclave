#!/usr/bin/env python3
"""
Web Browse Skill

Take screenshots, extract text, inspect elements, and execute JavaScript
on web pages using Playwright.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Error: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


# Default viewport
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
DEFAULT_WAIT = 2000
DEFAULT_MAX_LENGTH = 50000

# User agent — present as a normal browser
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def create_browser(playwright, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Launch headless Chromium browser."""
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )
    context = browser.new_context(
        viewport={"width": width, "height": height},
        user_agent=USER_AGENT,
        java_script_enabled=True,
    )
    return browser, context


def new_page(context):
    """Create a new page in the context."""
    return context.new_page()


def navigate(page, url, wait_ms=DEFAULT_WAIT):
    """Navigate to URL and wait for content to settle."""
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
    except PlaywrightTimeout:
        # networkidle can be slow on heavy pages — fall back to load
        try:
            page.goto(url, wait_until="load", timeout=15000)
        except PlaywrightTimeout:
            print(f"Warning: Page load timed out for {url}", file=sys.stderr)

    # Additional wait for JS rendering
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)


def cmd_screenshot(args):
    """Take a screenshot of a URL."""
    url = args.url
    output = args.output
    if not output:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = f"/tmp/screenshot-{ts}.png"

    with sync_playwright() as p:
        browser, context = create_browser(p, args.width, args.height)
        page = new_page(context)

        try:
            navigate(page, url, args.wait)

            screenshot_opts = {"path": output, "type": "png"}

            if args.selector:
                element = page.query_selector(args.selector)
                if element:
                    element.screenshot(**screenshot_opts)
                else:
                    print(f"Error: Selector '{args.selector}' not found on page", file=sys.stderr)
                    sys.exit(1)
            else:
                screenshot_opts["full_page"] = args.full_page
                page.screenshot(**screenshot_opts)

            file_size = Path(output).stat().st_size
            print(f"Screenshot saved: {output}")
            print(f"Size: {file_size:,} bytes")
            print(f"URL: {url}")
            print(f"Title: {page.title()}")

        finally:
            context.close()
            browser.close()


def clean_text(text):
    """Clean extracted text — normalize whitespace, remove excess blank lines."""
    lines = text.split("\n")
    cleaned = []
    prev_blank = False

    for line in lines:
        line = line.strip()
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return "\n".join(cleaned).strip()


def extract_links(page, selector=None):
    """Extract all links from the page or a specific element."""
    scope = f"{selector} " if selector else ""
    links = page.eval_on_selector_all(
        f"{scope}a[href]",
        """els => els.map(el => ({
            text: el.innerText.trim().substring(0, 100),
            href: el.href
        })).filter(l => l.text && l.href)"""
    )
    return links


def cmd_text(args):
    """Extract text content from a URL."""
    url = args.url

    with sync_playwright() as p:
        browser, context = create_browser(p, DEFAULT_WIDTH, DEFAULT_HEIGHT)
        page = new_page(context)

        try:
            navigate(page, url, args.wait)

            title = page.title()

            if args.selector:
                element = page.query_selector(args.selector)
                if element:
                    raw_text = element.inner_text()
                else:
                    print(f"Error: Selector '{args.selector}' not found on page", file=sys.stderr)
                    sys.exit(1)
            else:
                raw_text = page.inner_text("body")

            text = clean_text(raw_text)

            if args.max_length and len(text) > args.max_length:
                text = text[: args.max_length] + f"\n\n[... truncated at {args.max_length:,} chars ...]"

            output_parts = []
            output_parts.append(f"URL: {url}")
            output_parts.append(f"Title: {title}")
            output_parts.append(f"Length: {len(text):,} chars")
            output_parts.append("---")
            output_parts.append(text)

            if args.links:
                links = extract_links(page, args.selector)
                if links:
                    output_parts.append("")
                    output_parts.append("--- Links ---")
                    for link in links[:100]:
                        output_parts.append(f"  [{link['text']}] → {link['href']}")

            result = "\n".join(output_parts)

            if args.output:
                Path(args.output).write_text(result)
                print(f"Text saved: {args.output}")
                print(f"Length: {len(text):,} chars")
            else:
                print(result)

        finally:
            context.close()
            browser.close()


def cmd_inspect(args):
    """Discover page elements — buttons, links, inputs, forms."""
    url = args.url

    with sync_playwright() as p:
        browser, context = create_browser(p, args.width, DEFAULT_HEIGHT)
        page = new_page(context)

        console_logs = []
        if args.console:
            page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        try:
            navigate(page, url, args.wait)

            results = {}

            buttons = page.locator("button").all()
            btn_info = []
            for i, btn in enumerate(buttons):
                try:
                    text = btn.inner_text().strip()[:80] if btn.is_visible() else "[hidden]"
                    btn_info.append({"index": i, "text": text, "visible": btn.is_visible()})
                except Exception:
                    pass
            results["buttons"] = btn_info

            links = page.eval_on_selector_all(
                "a[href]",
                """els => els.slice(0, 50).map(el => ({
                    text: el.innerText.trim().substring(0, 80),
                    href: el.href
                })).filter(l => l.href)"""
            )
            results["links"] = links

            inputs_raw = page.locator("input, textarea, select").all()
            input_info = []
            for inp in inputs_raw[:30]:
                try:
                    name = inp.get_attribute("name") or inp.get_attribute("id") or "[unnamed]"
                    itype = inp.get_attribute("type") or "text"
                    placeholder = inp.get_attribute("placeholder") or ""
                    input_info.append({"name": name, "type": itype, "placeholder": placeholder[:60]})
                except Exception:
                    pass
            results["inputs"] = input_info

            forms = page.locator("form").all()
            form_info = []
            for i, form in enumerate(forms[:10]):
                try:
                    action = form.get_attribute("action") or "[none]"
                    method = form.get_attribute("method") or "GET"
                    form_info.append({"index": i, "action": action, "method": method})
                except Exception:
                    pass
            results["forms"] = form_info

            print(f"URL: {url}")
            print(f"Title: {page.title()}")
            print(f"---")
            print(f"Buttons: {len(results['buttons'])}")
            for b in results["buttons"]:
                vis = "" if b["visible"] else " [hidden]"
                print(f"  [{b['index']}] {b['text']}{vis}")

            print(f"\nLinks: {len(results['links'])}")
            for link in results["links"][:20]:
                print(f"  - {link['text'][:50]} → {link['href']}")

            print(f"\nInputs: {len(results['inputs'])}")
            for inp in results["inputs"]:
                ph = f" ({inp['placeholder']})" if inp["placeholder"] else ""
                print(f"  - {inp['name']} [{inp['type']}]{ph}")

            if results["forms"]:
                print(f"\nForms: {len(results['forms'])}")
                for f in results["forms"]:
                    print(f"  [{f['index']}] {f['method']} → {f['action']}")

            if console_logs:
                print(f"\nConsole ({len(console_logs)} messages):")
                for log in console_logs[:20]:
                    print(f"  {log}")

            if args.screenshot:
                ss_path = args.screenshot
                page.screenshot(path=ss_path, full_page=True)
                print(f"\nScreenshot: {ss_path}")

            if args.json_output:
                print(json.dumps(results, indent=2))

        finally:
            context.close()
            browser.close()


def cmd_execute(args):
    """Execute JavaScript on a page and return the result."""
    url = args.url

    with sync_playwright() as p:
        browser, context = create_browser(p, DEFAULT_WIDTH, DEFAULT_HEIGHT)
        page = new_page(context)

        try:
            navigate(page, url, args.wait)
            result = page.evaluate(args.script)

            if isinstance(result, (dict, list)):
                print(json.dumps(result, indent=2))
            else:
                print(result)

        finally:
            context.close()
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="Web Browse — screenshot, text, inspect, execute")
    subparsers = parser.add_subparsers(dest="command", help="Action to perform")

    ss = subparsers.add_parser("screenshot", help="Take a screenshot of a URL")
    ss.add_argument("url", help="URL to capture")
    ss.add_argument("--output", "-o", help="Output file path")
    ss.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    ss.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    ss.add_argument("--full-page", action="store_true", help="Capture full scrollable page")
    ss.add_argument("--wait", type=int, default=DEFAULT_WAIT)
    ss.add_argument("--selector", "-s", help="CSS selector to screenshot")

    tx = subparsers.add_parser("text", help="Extract text from a URL")
    tx.add_argument("url", help="URL to extract text from")
    tx.add_argument("--output", "-o", help="Output file path (default: stdout)")
    tx.add_argument("--selector", "-s", help="CSS selector to extract from")
    tx.add_argument("--wait", type=int, default=DEFAULT_WAIT)
    tx.add_argument("--links", action="store_true", help="Include links in output")
    tx.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)

    insp = subparsers.add_parser("inspect", help="Discover page elements")
    insp.add_argument("url", help="URL to inspect")
    insp.add_argument("--wait", type=int, default=DEFAULT_WAIT)
    insp.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    insp.add_argument("--console", action="store_true", help="Capture browser console output")
    insp.add_argument("--screenshot", help="Also save a screenshot to this path")
    insp.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    ex = subparsers.add_parser("execute", help="Execute JavaScript on a page")
    ex.add_argument("url", help="URL to load")
    ex.add_argument("script", help="JavaScript to execute")
    ex.add_argument("--wait", type=int, default=DEFAULT_WAIT)

    args = parser.parse_args()

    if args.command == "screenshot":
        cmd_screenshot(args)
    elif args.command == "text":
        cmd_text(args)
    elif args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "execute":
        cmd_execute(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
