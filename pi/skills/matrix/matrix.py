#!/usr/bin/env python3
"""
Matrix Skill — Send messages, read channels, upload media, and manage
reactions in Matrix rooms.

Unified tool with structured error handling, rate-limit awareness,
and room alias resolution. Uses only stdlib (no external dependencies).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta


# ─── Configuration ──────────────────────────────────────────────────────────

HOMESERVER = os.environ.get("MATRIX_HOMESERVER_URL", "").rstrip("/")
ACCESS_TOKEN = os.environ.get("MATRIX_ACCESS_TOKEN", "")
MATRIX_USER = os.environ.get("MATRIX_USER", "")
MATRIX_PASSWORD = os.environ.get("MATRIX_PASSWORD", "")
SERVER_NAME = os.environ.get("MATRIX_SERVER_NAME", "")
DEFAULT_ROOM = os.environ.get("MATRIX_DEFAULT_ROOM", "")
MAX_RETRIES = int(os.environ.get("MATRIX_MAX_RETRIES", "5"))

# JSON dict of shortname -> alias local part, e.g. {"home": "home", "dev": "dev"}
_raw_aliases = os.environ.get("MATRIX_ROOM_ALIASES", "")
ROOM_ALIASES = json.loads(_raw_aliases) if _raw_aliases else {}

# JSON array of bot user IDs for --humans-only filtering
_raw_bots = os.environ.get("MATRIX_BOT_USERS", "")
BOT_USERS = set(json.loads(_raw_bots)) if _raw_bots else set()


# ─── Token Management ──────────────────────────────────────────────────────

_cached_token = None


def _get_token():
    """Return an access token, using auto-login as fallback."""
    global _cached_token
    if ACCESS_TOKEN:
        return ACCESS_TOKEN
    if _cached_token:
        return _cached_token

    if not MATRIX_USER or not MATRIX_PASSWORD:
        return ""

    if not HOMESERVER:
        return ""

    payload = json.dumps({
        "type": "m.login.password",
        "user": MATRIX_USER,
        "password": MATRIX_PASSWORD,
    }).encode()
    req = urllib.request.Request(
        f"{HOMESERVER}/_matrix/client/v3/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            token = data.get("access_token", "")
            if token:
                _cached_token = token
            return token
    except Exception:
        return ""


# ─── API Layer ──────────────────────────────────────────────────────────────

class MatrixError(Exception):
    """Raised when a Matrix API call fails."""
    pass


def api_call(method, path, data=None, params=None, raw_body=None,
             content_type="application/json", max_retries=None):
    """
    Make an authenticated API call to Matrix with retry logic.

    Handles 429 rate limits by reading retry_after_ms from the response.
    Retries on 5xx errors with exponential backoff.
    Returns parsed JSON response. Raises MatrixError on failure.

    Args:
        method: HTTP method (GET, POST, PUT)
        path: API path (e.g. /_matrix/client/v3/...)
        data: Dict to JSON-encode as request body (mutually exclusive with raw_body)
        params: Dict of query parameters
        raw_body: Raw bytes for request body (used for media upload)
        content_type: Content-Type header value
        max_retries: Override default retry count
    """
    if not HOMESERVER:
        raise MatrixError("MATRIX_HOMESERVER_URL not set.")

    token = _get_token()
    if not token:
        raise MatrixError(
            "No Matrix credentials. Set MATRIX_ACCESS_TOKEN or MATRIX_USER/MATRIX_PASSWORD."
        )

    retries = max_retries if max_retries is not None else MAX_RETRIES
    url = f"{HOMESERVER}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    body = None
    if raw_body is not None:
        body = raw_body
    elif data is not None:
        body = json.dumps(data).encode()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": content_type,
                },
                method=method,
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            # Rate limit
            if e.code == 429:
                try:
                    retry_ms = json.loads(error_body).get("retry_after_ms", 5000)
                except (json.JSONDecodeError, ValueError):
                    retry_ms = 5000
                wait = max(1, (retry_ms + 999) // 1000)
                print(
                    f"Rate limited. Waiting {wait}s "
                    f"(attempt {attempt + 1}/{retries})...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            # Server errors — exponential backoff
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise MatrixError(f"HTTP {e.code}: {error_body}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise MatrixError(f"Connection failed: {e}")
        except json.JSONDecodeError:
            return {}

    raise MatrixError(f"All {retries} attempts failed for {method} {path}")


# ─── Room Resolution ───────────────────────────────────────────────────────

def _resolve_alias(alias):
    """Resolve a Matrix room alias (#room:server) to a room ID via directory API."""
    encoded = urllib.parse.quote(alias)
    data = api_call("GET", f"/_matrix/client/v3/directory/room/{encoded}")
    room_id = data.get("room_id")
    if not room_id:
        raise MatrixError(f"Could not resolve alias '{alias}'")
    return room_id


def resolve_room(room_str):
    """
    Resolve a room identifier to an internal room ID.

    Accepts:
      - Internal IDs: !abc123:server
      - Shortnames from MATRIX_ROOM_ALIASES: home -> #home:SERVER_NAME
      - Full alias: #room:server
      - Bare names: foo -> #foo:SERVER_NAME (resolved via directory API)
    """
    if not room_str:
        if DEFAULT_ROOM:
            room_str = DEFAULT_ROOM
        else:
            raise MatrixError("No room specified and MATRIX_DEFAULT_ROOM not set.")

    # Already a room ID
    if room_str.startswith("!"):
        return room_str

    # Check alias map
    if room_str in ROOM_ALIASES:
        local_part = ROOM_ALIASES[room_str]
        if SERVER_NAME:
            return _resolve_alias(f"#{local_part}:{SERVER_NAME}")
        raise MatrixError(
            f"MATRIX_SERVER_NAME required to resolve alias '{room_str}'"
        )

    # Full alias
    if room_str.startswith("#"):
        return _resolve_alias(room_str)

    # Bare name — try as #name:SERVER_NAME
    if SERVER_NAME:
        return _resolve_alias(f"#{room_str}:{SERVER_NAME}")

    raise MatrixError(
        f"Cannot resolve room '{room_str}'. "
        f"Known aliases: {', '.join(ROOM_ALIASES.keys()) or '(none)'}. "
        f"Set MATRIX_SERVER_NAME for bare name resolution."
    )


# ─── Room Helpers ──────────────────────────────────────────────────────────

def get_joined_rooms():
    """Get all rooms the bot has joined."""
    data = api_call("GET", "/_matrix/client/v3/joined_rooms")
    return data.get("joined_rooms", [])


def get_room_name(room_id):
    """Get the display name for a room."""
    # Check alias map first
    for alias, local_part in ROOM_ALIASES.items():
        if SERVER_NAME:
            try:
                alias_room_id = _resolve_alias(f"#{local_part}:{SERVER_NAME}")
                if alias_room_id == room_id:
                    return alias
            except MatrixError:
                pass
    try:
        encoded = urllib.parse.quote(room_id, safe="")
        data = api_call("GET", f"/_matrix/client/v3/rooms/{encoded}/state/m.room.name")
        return data.get("name", room_id)
    except MatrixError:
        return room_id


# ─── Message Formatting ───────────────────────────────────────────────────

def _short_sender(sender):
    """Extract short username from full Matrix ID (@user:server -> user)."""
    return sender.split(":")[0].lstrip("@") if ":" in sender else sender


def format_event(event, compact=False):
    """Format a single Matrix event for display."""
    etype = event.get("type", "")
    sender = _short_sender(event.get("sender", ""))
    content = event.get("content", {})
    ts = event.get("origin_server_ts", 0)
    event_id = event.get("event_id", "")
    dt = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")

    if etype == "m.reaction":
        key = content.get("m.relates_to", {}).get("key", "?")
        target = content.get("m.relates_to", {}).get("event_id", "?")[:20]
        if compact:
            return f"{dt} | reaction {sender} reacted {key} to {target}"
        return f"  reaction {dt} -- {sender} reacted {key}\n    on event {target}"

    if etype == "m.room.message":
        body = content.get("body", "")
        msgtype = content.get("msgtype", "m.text")
        relates = content.get("m.relates_to", {})

        # Skip message edits (show only final version)
        if relates.get("rel_type") == "m.replace":
            return None

        reply_to = relates.get("m.in_reply_to", {}).get("event_id", "")

        # Strip Matrix reply fallback from body
        if body.startswith("> "):
            lines = body.split("\n")
            clean_lines = []
            past_quote = False
            for line in lines:
                if past_quote:
                    clean_lines.append(line)
                elif not line.startswith("> ") and line.strip() != "":
                    past_quote = True
                    clean_lines.append(line)
                elif line.strip() == "":
                    past_quote = True
            body = "\n".join(clean_lines).strip() or body

        type_label = {
            "m.text": "text", "m.notice": "notice",
            "m.image": "image", "m.video": "video",
            "m.audio": "audio", "m.file": "file", "m.emote": "emote",
        }.get(msgtype, msgtype)

        if compact:
            body_short = body[:120].replace("\n", " ")
            reply_marker = " [reply]" if reply_to else ""
            return f"{dt} | {type_label} {sender}{reply_marker} | {body_short}"

        lines = [f"  {type_label} {dt} -- {sender}"]
        if reply_to:
            lines[0] += f"  (reply to {reply_to[:20]})"
        lines.append(f"    {event_id}")
        for line in body.split("\n")[:10]:
            lines.append(f"    {line}")
        if body.count("\n") > 10:
            lines.append(f"    ... ({body.count(chr(10)) - 10} more lines)")
        return "\n".join(lines)

    return None


def format_events(events, compact=False):
    """Format a list of events for display (chronological order)."""
    events = list(reversed(events))
    lines = []
    for event in events:
        formatted = format_event(event, compact=compact)
        if formatted:
            lines.append(formatted)
    return "\n".join(lines) if lines else "(no messages)"


# ─── Media Helpers ─────────────────────────────────────────────────────────

def _guess_mimetype(filepath):
    """Guess MIME type from file extension, with fallbacks for types
    not in Python's mimetypes db."""
    ext = os.path.splitext(filepath)[1].lower()
    # Explicit map for types mimetypes may not know
    known = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
    }
    return known.get(ext, "application/octet-stream")


def _detect_msgtype(mimetype):
    """Determine Matrix msgtype from MIME type."""
    if mimetype.startswith("image/"):
        return "m.image"
    if mimetype.startswith("video/"):
        return "m.video"
    if mimetype.startswith("audio/"):
        return "m.audio"
    return "m.file"


def upload_media(filepath):
    """Upload a file to the Matrix media repo. Returns mxc:// URI."""
    filename = os.path.basename(filepath)
    mimetype = _guess_mimetype(filepath)

    with open(filepath, "rb") as f:
        file_bytes = f.read()

    encoded_name = urllib.parse.quote(filename, safe="")
    data = api_call(
        "POST",
        f"/_matrix/media/v3/upload",
        params={"filename": encoded_name},
        raw_body=file_bytes,
        content_type=mimetype,
    )
    mxc = data.get("content_uri", "")
    if not mxc:
        raise MatrixError(f"Upload failed: {json.dumps(data)}")
    return mxc


# ─── Commands ──────────────────────────────────────────────────────────────

def cmd_send(args):
    """Send a text message to a Matrix room."""
    room_id = resolve_room(args.room)
    encoded_room = urllib.parse.quote(room_id, safe="")

    payload = {"msgtype": "m.text", "body": args.message}
    response = api_call(
        "POST",
        f"/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message",
        data=payload,
    )
    event_id = response.get("event_id", "")
    if event_id:
        print(f"Sent. Event ID: {event_id}")
    else:
        print(f"Error: unexpected response: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)


def cmd_read(args):
    """Read recent messages from a Matrix room."""
    # Determine rooms to check
    if args.all:
        rooms = get_joined_rooms()
    else:
        rooms = [resolve_room(args.room)]

    all_results = {}

    for room_id in rooms:
        encoded = urllib.parse.quote(room_id, safe="")
        params = {"dir": "b", "limit": str(args.limit)}
        data = api_call(
            "GET", f"/_matrix/client/v3/rooms/{encoded}/messages", params=params
        )
        events = data.get("chunk", [])

        # Filter by time
        if args.since:
            cutoff_ts = (
                datetime.now(timezone.utc) - timedelta(minutes=args.since)
            ).timestamp() * 1000
            events = [e for e in events if e.get("origin_server_ts", 0) >= cutoff_ts]

        # Filter by sender
        if args.from_user:
            events = [e for e in events if args.from_user in e.get("sender", "")]

        # Filter to humans only
        if args.humans_only:
            events = [e for e in events if e.get("sender", "") not in BOT_USERS]

        # Only include rooms with visible content
        if events:
            visible = [
                e for e in events
                if e.get("type") in ("m.room.message", "m.reaction")
                and e.get("content", {}).get("m.relates_to", {}).get("rel_type") != "m.replace"
            ]
            if visible:
                all_results[room_id] = visible

    # Output
    if args.json:
        output = {}
        for room_id, events in all_results.items():
            name = get_room_name(room_id)
            output[name] = events
        print(json.dumps(output, indent=2))
    else:
        if not all_results:
            since_str = f"last {args.since} minutes" if args.since else "all time"
            filter_str = ""
            if args.humans_only:
                filter_str = " from humans"
            if args.from_user:
                filter_str = f" from {args.from_user}"
            print(f"No messages{filter_str} in {since_str}.")
            return

        for room_id, events in all_results.items():
            name = get_room_name(room_id)
            formatted = format_events(events, compact=args.compact)
            visible_count = len(events)
            print(f"\n{'=' * 50}")
            print(f"  {name}  ({visible_count} messages)")
            print(f"{'=' * 50}")
            print(formatted)
            print()


def cmd_rooms(args):
    """List all joined rooms."""
    rooms = get_joined_rooms()
    if not rooms:
        print("No joined rooms.")
        return

    print(f"{'=' * 50}")
    print(f"  Joined Rooms ({len(rooms)})")
    print(f"{'=' * 50}")
    for room_id in rooms:
        name = get_room_name(room_id)
        if name != room_id:
            print(f"  {name}  ({room_id})")
        else:
            print(f"  {room_id}")


def cmd_attach(args):
    """Upload and send a file to a Matrix room."""
    room_id = resolve_room(args.room)

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    filename = os.path.basename(args.file)
    mimetype = _guess_mimetype(args.file)
    msgtype = _detect_msgtype(mimetype)
    filesize = os.path.getsize(args.file)

    # Send caption first if provided
    if args.caption:
        encoded_room = urllib.parse.quote(room_id, safe="")
        api_call(
            "POST",
            f"/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message",
            data={"msgtype": "m.text", "body": args.caption},
        )

    print(f"Uploading {filename}...", file=sys.stderr)
    mxc_uri = upload_media(args.file)

    encoded_room = urllib.parse.quote(room_id, safe="")
    payload = {
        "msgtype": msgtype,
        "body": filename,
        "url": mxc_uri,
        "info": {
            "mimetype": mimetype,
            "size": filesize,
        },
    }
    response = api_call(
        "POST",
        f"/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message",
        data=payload,
    )
    event_id = response.get("event_id", "")
    if event_id:
        print(f"Sent {filename}. Event ID: {event_id}")
    else:
        print(f"Error: unexpected response: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)


def cmd_react(args):
    """Send a reaction to an event."""
    room_id = resolve_room(args.room)
    encoded_room = urllib.parse.quote(room_id, safe="")

    payload = {
        "m.relates_to": {
            "rel_type": "m.annotation",
            "event_id": args.event_id,
            "key": args.emoji,
        }
    }
    response = api_call(
        "POST",
        f"/_matrix/client/v3/rooms/{encoded_room}/send/m.reaction",
        data=payload,
    )
    event_id = response.get("event_id", "")
    if event_id:
        print(f"Reacted with {args.emoji} on {args.event_id}")
    else:
        print(f"Error: unexpected response: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)


def cmd_reactions(args):
    """Query reactions on a specific event."""
    room_id = resolve_room(args.room)
    encoded_room = urllib.parse.quote(room_id, safe="")
    encoded_event = urllib.parse.quote(args.event_id, safe="")

    try:
        data = api_call(
            "GET",
            f"/_matrix/client/v1/rooms/{encoded_room}/relations/{encoded_event}/m.annotation",
        )
        reactions = data.get("chunk", [])
    except MatrixError:
        # Fallback: scan recent messages for reactions targeting this event
        params = {"dir": "b", "limit": "100"}
        data = api_call(
            "GET", f"/_matrix/client/v3/rooms/{encoded_room}/messages", params=params
        )
        reactions = []
        for e in data.get("chunk", []):
            if e.get("type") == "m.reaction":
                relates = e.get("content", {}).get("m.relates_to", {})
                if relates.get("event_id") == args.event_id:
                    reactions.append(e)

    if args.json:
        print(json.dumps(reactions, indent=2))
    else:
        if not reactions:
            print(f"No reactions found on {args.event_id[:30]}")
        else:
            print(f"Reactions on {args.event_id[:30]}:")
            for r in reactions:
                sender = _short_sender(r.get("sender", ""))
                key = r.get("content", {}).get("m.relates_to", {}).get("key", "?")
                print(f"  {key} -- {sender}")


def cmd_batch(args):
    """Send multiple files with pacing to avoid rate limits."""
    room_id = resolve_room(args.room)
    delay = args.delay
    files = args.files

    total = len(files)
    sent = 0

    print(f"Sending batch: {total} files with {delay}s pacing", file=sys.stderr)

    for i, filepath in enumerate(files):
        if not os.path.isfile(filepath):
            print(f"  Skipping missing file: {filepath}", file=sys.stderr)
            continue

        filename = os.path.basename(filepath)
        mimetype = _guess_mimetype(filepath)
        msgtype = _detect_msgtype(mimetype)
        filesize = os.path.getsize(filepath)

        print(f"  [{i + 1}/{total}] {filename}", file=sys.stderr)

        mxc_uri = upload_media(filepath)
        encoded_room = urllib.parse.quote(room_id, safe="")
        payload = {
            "msgtype": msgtype,
            "body": filename,
            "url": mxc_uri,
            "info": {
                "mimetype": mimetype,
                "size": filesize,
            },
        }
        api_call(
            "POST",
            f"/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message",
            data=payload,
        )
        sent += 1

        # Pace between sends (skip delay after last item)
        if i < total - 1:
            print(f"  Waiting {delay}s...", file=sys.stderr)
            time.sleep(delay)

    print(f"Batch complete: {sent}/{total} sent", file=sys.stderr)


# ─── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Matrix communication -- send messages, read channels, upload media, manage reactions."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # send
    p_send = subparsers.add_parser("send", help="Send a text message to a room")
    p_send.add_argument("message", help="Message text to send")
    p_send.add_argument(
        "--room", default=None,
        help="Room alias, name, or ID (falls back to MATRIX_DEFAULT_ROOM)",
    )

    # read
    p_read = subparsers.add_parser("read", help="Read recent messages from a room")
    p_read.add_argument(
        "--room", default=None,
        help="Room alias, name, or ID (falls back to MATRIX_DEFAULT_ROOM)",
    )
    p_read.add_argument(
        "--all", action="store_true",
        help="Check all joined rooms",
    )
    p_read.add_argument(
        "--since", type=int, default=120,
        help="Messages from last N minutes (default: 120)",
    )
    p_read.add_argument(
        "--limit", type=int, default=50,
        help="Max messages to fetch (default: 50)",
    )
    p_read.add_argument(
        "--from", dest="from_user", default=None,
        help="Filter to messages from this sender",
    )
    p_read.add_argument(
        "--humans-only", action="store_true",
        help="Exclude bot/agent messages (uses MATRIX_BOT_USERS)",
    )
    p_read.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )
    p_read.add_argument(
        "--compact", action="store_true",
        help="One-line-per-message format",
    )

    # rooms
    subparsers.add_parser("rooms", help="List all joined rooms")

    # attach
    p_attach = subparsers.add_parser("attach", help="Upload and send a file")
    p_attach.add_argument(
        "--room", default=None,
        help="Room alias, name, or ID (falls back to MATRIX_DEFAULT_ROOM)",
    )
    p_attach.add_argument(
        "--file", required=True,
        help="Path to the file to upload",
    )
    p_attach.add_argument(
        "--caption", default=None,
        help="Optional caption sent before the file",
    )

    # react
    p_react = subparsers.add_parser("react", help="Send a reaction to an event")
    p_react.add_argument("event_id", help="Event ID to react to")
    p_react.add_argument(
        "--emoji", required=True,
        help="Emoji to react with (e.g. a unicode emoji)",
    )
    p_react.add_argument(
        "--room", required=True,
        help="Room alias, name, or ID",
    )

    # reactions
    p_reactions = subparsers.add_parser("reactions", help="Query reactions on an event")
    p_reactions.add_argument("event_id", help="Event ID to query reactions for")
    p_reactions.add_argument(
        "--room", required=True,
        help="Room alias, name, or ID",
    )
    p_reactions.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )

    # batch
    p_batch = subparsers.add_parser("batch", help="Send multiple files with pacing")
    p_batch.add_argument(
        "--room", default=None,
        help="Room alias, name, or ID (falls back to MATRIX_DEFAULT_ROOM)",
    )
    p_batch.add_argument(
        "--delay", type=float, default=3.0,
        help="Seconds to wait between sends (default: 3)",
    )
    p_batch.add_argument(
        "files", nargs="+",
        help="File paths to upload and send",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "send": cmd_send,
        "read": cmd_read,
        "rooms": cmd_rooms,
        "attach": cmd_attach,
        "react": cmd_react,
        "reactions": cmd_reactions,
        "batch": cmd_batch,
    }

    try:
        commands[args.command](args)
    except MatrixError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
