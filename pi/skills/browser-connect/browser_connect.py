#!/usr/bin/env python3
"""
Browser Connect — CDP automation for Conclave's local Chromium.
"""

import argparse
import json
import os
import sys
import urllib.request
from contextlib import contextmanager

CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = os.environ.get("CDP_PORT", "9222")


def get_ws_url():
    """Discover the WebSocket debugger URL from the CDP endpoint."""
    url = f"http://{CDP_HOST}:{CDP_PORT}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return data["webSocketDebuggerUrl"]
    except Exception as e:
        print(f"ERROR: Cannot reach CDP at {url}: {e}", file=sys.stderr)
        sys.exit(1)


@contextmanager
def BrowserSession():
    """Context manager that connects to the local Chromium via CDP.

    Yields (browser, page) where page is the first open tab.

    Usage::

        with BrowserSession() as (browser, page):
            page.goto("https://example.com")
            page.screenshot(path="out.png")
    """
    from playwright.sync_api import sync_playwright

    ws_url = get_ws_url()
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(ws_url)
        contexts = browser.contexts
        if not contexts:
            ctx = browser.new_context()
        else:
            ctx = contexts[0]

        pages = ctx.pages
        page = pages[0] if pages else ctx.new_page()

        # Basic stealth: override navigator.webdriver
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        yield browser, page
    finally:
        pw.stop()


def cmd_test(_args):
    """Validate CDP connection."""
    ws_url = get_ws_url()
    print(f"CDP WebSocket: {ws_url}")

    with BrowserSession() as (browser, page):
        print(f"Connected. Page URL: {page.url}")
        print(f"Contexts: {len(browser.contexts)}")
        print("OK")


def cmd_screenshot(args):
    """Capture a screenshot of the current page."""
    output = args.output or "screenshot.png"
    with BrowserSession() as (_browser, page):
        page.screenshot(path=output, full_page=args.full_page)
        print(f"Screenshot saved to {output}")


def cmd_cookies(_args):
    """List cookies from the browser."""
    with BrowserSession() as (browser, _page):
        for ctx in browser.contexts:
            cookies = ctx.cookies()
            for cookie in cookies:
                domain = cookie.get("domain", "")
                name = cookie.get("name", "")
                value = cookie.get("value", "")[:40]
                print(f"{domain}\t{name}\t{value}")


def main():
    parser = argparse.ArgumentParser(description="Browser automation via CDP")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("test", help="Validate CDP connection")

    ss = sub.add_parser("screenshot", help="Capture a screenshot")
    ss.add_argument("--output", "-o", help="Output file path (default: screenshot.png)")
    ss.add_argument("--full-page", action="store_true", help="Capture full scrollable page")

    sub.add_parser("cookies", help="List browser cookies")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {"test": cmd_test, "screenshot": cmd_screenshot, "cookies": cmd_cookies}
    cmds[args.command](args)


if __name__ == "__main__":
    main()
