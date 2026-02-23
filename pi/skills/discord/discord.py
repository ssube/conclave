#!/usr/bin/env python3
"""
Discord Skill — Send messages, read channels, and manage Discord communication.

Unified tool with structured error handling, rate-limit awareness,
and reliable JSON parsing. Uses only stdlib (no external dependencies).
"""

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


# ─── Configuration ──────────────────────────────────────────────────────────

DISCORD_API = "https://discord.com/api/v10"


def _load_env_var(name):
    """Load an env var from the environment."""
    return os.environ.get(name, "")


BOT_TOKEN = _load_env_var("DISCORD_BOT_TOKEN")
GUILD_ID = _load_env_var("DISCORD_GUILD_ID")
DEFAULT_CHANNEL = _load_env_var("DISCORD_DEFAULT_CHANNEL")


# ─── Snowflake Helpers ──────────────────────────────────────────────────────

DISCORD_EPOCH = 1420070400000  # ms — Discord epoch (2015-01-01T00:00:00Z)


def snowflake_from_timestamp(ts_ms):
    """Convert a Unix timestamp (ms) to a Discord snowflake for message filtering."""
    return str((int(ts_ms) - DISCORD_EPOCH) << 22)


def snowflake_to_timestamp(snowflake_id):
    """Convert a Discord snowflake to Unix timestamp (ms)."""
    return ((int(snowflake_id) >> 22) + DISCORD_EPOCH)


# ─── API Layer ──────────────────────────────────────────────────────────────

class DiscordError(Exception):
    """Raised when a Discord API call fails."""
    pass


def api_call(method, endpoint, data=None, max_retries=3):
    """
    Make an authenticated API call to Discord with retry logic.

    Handles 429 rate limits by reading retry_after from the response body.
    Retries on 5xx errors with exponential backoff.
    Returns parsed JSON response. Raises DiscordError on failure.
    """
    if not BOT_TOKEN:
        raise DiscordError(
            "DISCORD_BOT_TOKEN not set. Set it in the environment."
        )

    url = f"{DISCORD_API}{endpoint}"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "User-Agent": "DiscordSkill/1.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.dumps(data).encode() if data else None

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url, data=body, headers=headers, method=method
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            # Rate limit — sleep for the duration Discord tells us
            if e.code == 429:
                try:
                    retry_after = json.loads(error_body).get("retry_after", 5)
                except (json.JSONDecodeError, ValueError):
                    retry_after = 5
                print(
                    f"Rate limited. Waiting {retry_after}s "
                    f"(attempt {attempt + 1}/{max_retries})...",
                    file=sys.stderr,
                )
                time.sleep(float(retry_after))
                continue
            # Server errors — exponential backoff
            if e.code >= 500 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise DiscordError(f"HTTP {e.code}: {error_body}")
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise DiscordError(f"Connection failed: {e}")
        except json.JSONDecodeError:
            return {}

    raise DiscordError(f"All {max_retries} attempts failed for {method} {endpoint}")


# ─── Channel Resolution ────────────────────────────────────────────────────

def resolve_channel(channel_arg):
    """
    Resolve a channel argument to a channel ID.

    If the argument is all digits, return it as-is (already an ID).
    Otherwise, look up the channel by name in the guild (case-insensitive).
    Falls back to DISCORD_DEFAULT_CHANNEL if channel_arg is None.
    """
    if channel_arg is None:
        if DEFAULT_CHANNEL:
            return DEFAULT_CHANNEL
        raise DiscordError(
            "No channel specified and DISCORD_DEFAULT_CHANNEL is not set."
        )

    # Already a numeric ID
    if channel_arg.isdigit():
        return channel_arg

    # Name lookup — requires a guild
    if not GUILD_ID:
        raise DiscordError(
            f"Cannot resolve channel name '{channel_arg}' without DISCORD_GUILD_ID."
        )

    channels = api_call("GET", f"/guilds/{GUILD_ID}/channels")
    if not isinstance(channels, list):
        raise DiscordError("Unexpected response when fetching guild channels.")

    target = channel_arg.lower().lstrip("#")
    for ch in channels:
        # Text-like channels: type 0 (text), 5 (announcement)
        if ch.get("name", "").lower() == target and ch.get("type") in (0, 5):
            return ch["id"]

    raise DiscordError(
        f"Channel '{channel_arg}' not found in guild {GUILD_ID}."
    )


# ─── Message Formatting ────────────────────────────────────────────────────

def _parse_timestamp(ts_str):
    """Parse an ISO timestamp string to a display string."""
    try:
        # Handle both Z and +00:00 suffixes
        clean = ts_str.replace("Z", "+00:00")
        from datetime import datetime
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts_str[:16] if ts_str else "?"


def format_message(msg, compact=False):
    """
    Format a single Discord message for display.

    Compact mode: single line with truncated content.
    Verbose mode: multi-line with message ID, full content, attachments, embeds.
    """
    author = msg.get("author", {})
    username = author.get("username", "?")
    is_bot = author.get("bot", False)
    content = msg.get("content", "")
    msg_id = msg.get("id", "")
    ts_str = msg.get("timestamp", "")
    dt_display = _parse_timestamp(ts_str)

    attachments = msg.get("attachments", [])
    embeds = msg.get("embeds", [])
    ref = msg.get("message_reference", {})
    reply_to = ref.get("message_id", "")

    bot_tag = " \U0001f916" if is_bot else ""

    if compact:
        content_short = content[:120].replace("\n", " ") if content else "(no text)"
        attach_str = " [\U0001f4ce files]" if attachments else ""
        embed_str = " [\U0001f4cb embeds]" if embeds else ""
        reply_marker = " [reply]" if reply_to else ""
        reactions = msg.get("reactions", [])
        react_str = ""
        if reactions:
            parts = [f"{r.get('emoji', {}).get('name', '?')} x{r.get('count', 0)}" for r in reactions]
            react_str = f" [{', '.join(parts)}]"
        return (
            f"{dt_display} | \U0001f4ac {username}{bot_tag}{reply_marker} | "
            f"{content_short}{attach_str}{embed_str}{react_str}"
        )

    # Verbose mode
    lines = [f"  \U0001f4ac {dt_display} \u2014 {username}{bot_tag}"]
    if reply_to:
        lines[0] += f"  (reply to {reply_to})"
    lines.append(f"    ID: {msg_id}")

    if content:
        content_lines = content.split("\n")
        for line in content_lines[:15]:
            lines.append(f"    {line}")
        if len(content_lines) > 15:
            lines.append(f"    ... ({len(content_lines) - 15} more lines)")

    if attachments:
        for a in attachments:
            size = a.get("size", 0)
            fname = a.get("filename", "file")
            lines.append(f"    \U0001f4ce {fname} ({size} bytes)")

    if embeds:
        for e in embeds:
            title = e.get("title", "(untitled embed)")
            lines.append(f"    \U0001f4cb {title}")

    reactions = msg.get("reactions", [])
    if reactions:
        parts = [f"{r.get('emoji', {}).get('name', '?')} x{r.get('count', 0)}" for r in reactions]
        lines.append(f"    [{', '.join(parts)}]")

    return "\n".join(lines)


# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_send(args):
    """Send a message to a Discord channel."""
    channel_id = resolve_channel(args.channel)
    payload = {"content": args.message}

    response = api_call("POST", f"/channels/{channel_id}/messages", payload)
    msg_id = response.get("id", "")

    if msg_id:
        print(f"Message sent. ID: {msg_id}")
        print(f"Channel: {channel_id}")
    else:
        print(f"Error: unexpected response: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)


def cmd_read(args):
    """Read recent messages from a Discord channel."""
    channel_id = resolve_channel(args.channel)
    limit = min(args.limit, 100)

    params = {"limit": str(limit)}
    if args.since:
        from datetime import datetime, timezone, timedelta
        cutoff_ms = (
            datetime.now(timezone.utc) - timedelta(minutes=args.since)
        ).timestamp() * 1000
        params["after"] = snowflake_from_timestamp(cutoff_ms)

    # Build URL with query params
    query = urllib.parse.urlencode(params)
    messages = api_call("GET", f"/channels/{channel_id}/messages?{query}")
    if not isinstance(messages, list):
        messages = []

    # Filter by username
    if args.from_user:
        target = args.from_user.lower()
        messages = [
            m for m in messages
            if target in m.get("author", {}).get("username", "").lower()
        ]

    # Filter bots
    if args.humans_only:
        messages = [
            m for m in messages
            if not m.get("author", {}).get("bot", False)
        ]

    if not messages:
        since_str = f"last {args.since} minutes" if args.since else "all time"
        print(f"No messages in {since_str}.")
        return

    # Reverse to chronological order (Discord returns newest first)
    messages = list(reversed(messages))

    # Get channel name for header
    try:
        ch_info = api_call("GET", f"/channels/{channel_id}")
        ch_name = ch_info.get("name", channel_id)
    except DiscordError:
        ch_name = channel_id

    print(f"\n\u2550" * 50)
    print(f"  \U0001f4eb #{ch_name}  ({len(messages)} messages)")
    print(f"\u2550" * 50)

    for msg in messages:
        print(format_message(msg, compact=args.compact))
        if not args.compact:
            print()


def cmd_channels(args):
    """List channels in a guild."""
    guild_id = args.guild or GUILD_ID
    if not guild_id:
        print("Error: No guild specified. Use --guild or set DISCORD_GUILD_ID.",
              file=sys.stderr)
        sys.exit(1)

    channels = api_call("GET", f"/guilds/{guild_id}/channels")
    if not isinstance(channels, list):
        print("Error: unexpected response from guild channels endpoint.",
              file=sys.stderr)
        sys.exit(1)

    # Channel type display icons
    type_icons = {
        0: "\U0001f4ac",   # text
        2: "\U0001f50a",   # voice
        4: "\U0001f4c1",   # category
        5: "\U0001f4e2",   # announce
        13: "\U0001f3ad",  # stage
        15: "\U0001f4cb",  # forum
    }

    # Build parent lookup and sort by parent_id then position
    categories = {}
    children = []
    for ch in channels:
        if ch.get("type") == 4:
            categories[ch["id"]] = ch
        else:
            children.append(ch)

    # Sort categories by position
    sorted_cats = sorted(categories.values(), key=lambda c: c.get("position", 0))

    # Sort children by parent then position
    children.sort(key=lambda c: (c.get("parent_id") or "", c.get("position", 0)))

    # Group children by parent
    children_by_parent = {}
    for ch in children:
        parent = ch.get("parent_id") or "__none__"
        children_by_parent.setdefault(parent, []).append(ch)

    print(f"\u2550" * 50)
    print(f"  Guild Channels ({guild_id})")
    print(f"\u2550" * 50)

    # Print uncategorized channels first
    for ch in children_by_parent.get("__none__", []):
        icon = type_icons.get(ch.get("type", 0), "?")
        print(f"  {icon}  #{ch.get('name', '?')}  (id: {ch['id']})")

    # Print categories with their children
    for cat in sorted_cats:
        icon = type_icons.get(4, "\U0001f4c1")
        print(f"\n  {icon}  {cat.get('name', '?').upper()}  (id: {cat['id']})")
        for ch in children_by_parent.get(cat["id"], []):
            ch_icon = type_icons.get(ch.get("type", 0), "?")
            print(f"      {ch_icon}  #{ch.get('name', '?')}  (id: {ch['id']})")


def cmd_guilds(args):
    """List guilds the bot is a member of."""
    guilds = api_call("GET", "/users/@me/guilds")
    if not isinstance(guilds, list):
        print("Error: unexpected response from guilds endpoint.", file=sys.stderr)
        sys.exit(1)

    print(f"\u2550" * 50)
    print(f"  Bot Guilds")
    print(f"\u2550" * 50)

    for g in guilds:
        name = g.get("name", "?")
        gid = g.get("id", "?")
        owner = " (owner)" if g.get("owner") else ""
        print(f"  {name}  (id: {gid}){owner}")


def _multipart_upload(channel_id, file_path, caption=None):
    """Upload a file to a Discord channel via multipart/form-data."""
    if not BOT_TOKEN:
        raise DiscordError(
            "DISCORD_BOT_TOKEN not set. Set it in the environment."
        )

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    basename = os.path.basename(file_path)
    mimetype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    boundary = uuid.uuid4().hex

    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="files[0]"; filename="{basename}"\r\n'.encode()
    body += f"Content-Type: {mimetype}\r\n".encode()
    body += b"\r\n"
    body += file_bytes
    body += b"\r\n"

    if caption:
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="payload_json"\r\n'
        body += b"Content-Type: application/json\r\n"
        body += b"\r\n"
        body += json.dumps({"content": caption}).encode()
        body += b"\r\n"

    body += f"--{boundary}--\r\n".encode()

    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "User-Agent": "DiscordSkill/1.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise DiscordError(f"HTTP {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise DiscordError(f"Connection failed: {e}")


def cmd_attach(args):
    """Send a file attachment to a Discord channel."""
    channel_id = resolve_channel(args.channel)

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    response = _multipart_upload(channel_id, args.file, caption=args.caption)
    msg_id = response.get("id", "")

    if msg_id:
        print(f"File sent. ID: {msg_id}")
        print(f"Channel: {channel_id}")
        print(f"File: {os.path.basename(args.file)}")
    else:
        print(f"Error: unexpected response: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)


def cmd_poll(args):
    """Create a poll in a Discord channel."""
    channel_id = resolve_channel(args.channel)

    answers = [{"poll_media": {"text": a.strip()}} for a in args.answers.split(",")]
    payload = {
        "poll": {
            "question": {"text": args.question},
            "answers": answers,
            "duration": args.duration,
            "allow_multiselect": args.multi,
        }
    }

    response = api_call("POST", f"/channels/{channel_id}/messages", payload)
    msg_id = response.get("id", "")

    if msg_id:
        print(f"Poll created. ID: {msg_id}")
        print(f"Channel: {channel_id}")
        print(f"Question: {args.question}")
        print(f"Duration: {args.duration}h")
    else:
        print(f"Error: unexpected response: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)


def cmd_react(args):
    """Add a reaction to a message."""
    channel_id = resolve_channel(args.channel)
    encoded_emoji = urllib.parse.quote(args.emoji)

    api_call(
        "PUT",
        f"/channels/{channel_id}/messages/{args.message_id}/reactions/{encoded_emoji}/@me",
    )
    print(f"Reacted with {args.emoji} on message {args.message_id}")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Discord communication — send messages, read channels, list guilds."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # send
    p_send = subparsers.add_parser("send", help="Send a message to a channel")
    p_send.add_argument("message", help="Message text to send")
    p_send.add_argument(
        "--channel", default=None,
        help="Channel ID or name (falls back to DISCORD_DEFAULT_CHANNEL)"
    )

    # read
    p_read = subparsers.add_parser("read", help="Read recent messages from a channel")
    p_read.add_argument(
        "--channel", default=None,
        help="Channel ID or name (falls back to DISCORD_DEFAULT_CHANNEL)"
    )
    p_read.add_argument(
        "--since", type=int, default=120,
        help="Messages from last N minutes (default: 120)"
    )
    p_read.add_argument(
        "--limit", type=int, default=50,
        help="Max messages to fetch (default: 50, max: 100)"
    )
    p_read.add_argument(
        "--from", dest="from_user", default=None,
        help="Filter to messages from this username"
    )
    p_read.add_argument(
        "--humans-only", action="store_true",
        help="Exclude bot messages"
    )
    p_read.add_argument(
        "--compact", action="store_true",
        help="One-line-per-message format"
    )

    # channels
    p_channels = subparsers.add_parser("channels", help="List channels in a guild")
    p_channels.add_argument(
        "--guild", default=None,
        help="Guild ID (falls back to DISCORD_GUILD_ID)"
    )

    # guilds
    subparsers.add_parser("guilds", help="List guilds the bot belongs to")

    # attach
    p_attach = subparsers.add_parser("attach", help="Send a file attachment to a channel")
    p_attach.add_argument(
        "--channel", default=None,
        help="Channel ID or name (falls back to DISCORD_DEFAULT_CHANNEL)"
    )
    p_attach.add_argument(
        "--file", required=True,
        help="Path to the file to upload"
    )
    p_attach.add_argument(
        "--caption", default=None,
        help="Optional caption text to send with the file"
    )

    # poll
    p_poll = subparsers.add_parser("poll", help="Create a poll in a channel")
    p_poll.add_argument(
        "--channel", default=None,
        help="Channel ID or name (falls back to DISCORD_DEFAULT_CHANNEL)"
    )
    p_poll.add_argument(
        "--question", required=True,
        help="Poll question text"
    )
    p_poll.add_argument(
        "--answers", required=True,
        help="Comma-separated list of poll answers"
    )
    p_poll.add_argument(
        "--duration", type=int, default=24,
        help="Poll duration in hours (default: 24)"
    )
    p_poll.add_argument(
        "--multi", action="store_true",
        help="Allow multiple selections"
    )

    # react
    p_react = subparsers.add_parser("react", help="Add a reaction to a message")
    p_react.add_argument(
        "message_id",
        help="ID of the message to react to"
    )
    p_react.add_argument(
        "--emoji", required=True,
        help="Emoji to react with (e.g. a unicode emoji or name:id for custom)"
    )
    p_react.add_argument(
        "--channel", required=True,
        help="Channel ID or name where the message is"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "send": cmd_send,
        "read": cmd_read,
        "channels": cmd_channels,
        "guilds": cmd_guilds,
        "attach": cmd_attach,
        "poll": cmd_poll,
        "react": cmd_react,
    }

    try:
        commands[args.command](args)
    except DiscordError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
