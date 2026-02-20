#!/usr/bin/env python3
"""
Matrix Read — Fetch recent messages, reactions, and replies from Matrix rooms.
The ears of Xuthal: hear what echoes through the green corridors.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta

import sys; sys.path.insert(0, "/workspace"); import load_env  # noqa: E402

# ─── Watermark Integration ──────────────────────────────────────────────────
# Advance heartbeat watermarks when messages are read, so the heartbeat
# doesn't re-report messages already seen via manual reads.

def _advance_watermark(room: str, ts: int):
    """Best-effort watermark advance — never fails the read."""
    try:
        sys.path.insert(0, "/workspace/scripts")
        from watermark import advance_watermark
        advance_watermark(room, ts)
    except Exception:
        pass  # watermark is best-effort, never block reads


# ─── Room Aliases ───────────────────────────────────────────────────────────

ROOM_ALIASES = {
    "general":   "!EOujKPtUOJPbbyBnHr:matrix.home.holdmyran.ch",
    "drafts":    "!DTwKgcNMAqKTqCCbyY:matrix.home.holdmyran.ch",
    "published": "!HRUMcHLpGmtWRPMjpz:matrix.home.holdmyran.ch",
    "data":      "!AXdouVagECaWEfWlqF:matrix.home.holdmyran.ch",
    "image":     "!oGVcqxQeeZWtYNqWIk:matrix.home.holdmyran.ch",
    "calendar":  "!xJqiFXNHCVTkaeoIfl:matrix.home.holdmyran.ch",
}

# Known bot/agent user IDs (for --humans-only filtering)
BOT_USERS = {
    "@thalis-agent:matrix.home.holdmyran.ch",
    "@image-bot:matrix.home.holdmyran.ch",
    "@data-bot:matrix.home.holdmyran.ch",
}

# ─── Matrix API Helpers ─────────────────────────────────────────────────────

def matrix_get(path, params=None):
    """Make an authenticated GET request to the Matrix API."""
    homeserver = os.environ.get("MATRIX_HOMESERVER_URL", "").rstrip("/")
    token = os.environ.get("MATRIX_ACCESS_TOKEN", "")
    
    if not homeserver or not token:
        print("ERROR: MATRIX_HOMESERVER_URL and MATRIX_ACCESS_TOKEN must be set", file=sys.stderr)
        sys.exit(1)
    
    url = f"{homeserver}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR: Matrix API returned {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Matrix API request failed: {e}", file=sys.stderr)
        sys.exit(1)


def resolve_room(room_str):
    """Resolve a room identifier to an internal room ID.
    
    Accepts:
      - Internal IDs: !EOujKPtUOJPbbyBnHr:matrix.home.holdmyran.ch
      - Shortnames: general, drafts, published, data, image, calendar
      - Full alias format: #thalis-general:matrix.home.holdmyran.ch (mapped locally)
    
    Note: Room aliases don't actually exist on the server — the #thalis-* format
    is resolved via a local map, not the Matrix directory API.
    """
    if room_str.startswith("!"):
        return room_str
    if room_str in ROOM_ALIASES:
        return ROOM_ALIASES[room_str]
    
    # Strip # prefix and :server suffix for matching
    clean = room_str.lstrip("#")
    if ":" in clean:
        clean = clean.split(":")[0]
    # Strip thalis- prefix if present
    if clean.startswith("thalis-"):
        clean = clean[len("thalis-"):]
    # Map common room name variants
    name_map = {
        "general": "general",
        "content-drafts": "drafts",
        "content-published": "published",
        "ask-data": "data",
        "conjure-image": "image",
        "content-calendar": "calendar",
    }
    mapped = name_map.get(clean, clean)
    if mapped in ROOM_ALIASES:
        return ROOM_ALIASES[mapped]
    
    # Partial match on shortnames
    for alias, room_id in ROOM_ALIASES.items():
        if alias in clean or clean in alias:
            return room_id
    
    print(f"ERROR: Unknown room '{room_str}'. Known: {', '.join(ROOM_ALIASES.keys())}", file=sys.stderr)
    sys.exit(1)


def get_joined_rooms():
    """Get all rooms the bot has joined."""
    data = matrix_get("/_matrix/client/v3/joined_rooms")
    return data.get("joined_rooms", [])


def get_room_name(room_id):
    """Get the display name for a room."""
    # Check aliases first
    for alias, rid in ROOM_ALIASES.items():
        if rid == room_id:
            return alias
    try:
        data = matrix_get(f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id)}/state/m.room.name")
        return data.get("name", room_id)
    except:
        return room_id


def short_sender(sender):
    """Extract short username from full Matrix ID."""
    return sender.split(":")[0].lstrip("@") if ":" in sender else sender


# ─── Message Fetching ───────────────────────────────────────────────────────

def fetch_messages(room_id, limit=50, since_minutes=120):
    """Fetch recent messages from a room, newest first."""
    params = {"dir": "b", "limit": str(limit)}
    data = matrix_get(f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id)}/messages", params)
    
    events = data.get("chunk", [])
    
    # Filter by time if requested
    if since_minutes:
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp() * 1000
        events = [e for e in events if e.get("origin_server_ts", 0) >= cutoff_ts]
    
    return events


def fetch_reactions_for(room_id, event_id):
    """Fetch reactions for a specific event using relations API."""
    try:
        data = matrix_get(
            f"/_matrix/client/v1/rooms/{urllib.parse.quote(room_id)}/relations/{urllib.parse.quote(event_id)}/m.annotation"
        )
        return data.get("chunk", [])
    except:
        # Fallback: scan recent messages for reactions targeting this event
        all_events = fetch_messages(room_id, limit=100, since_minutes=None)
        reactions = []
        for e in all_events:
            if e.get("type") == "m.reaction":
                relates = e.get("content", {}).get("m.relates_to", {})
                if relates.get("event_id") == event_id:
                    reactions.append(e)
        return reactions


# ─── Formatting ─────────────────────────────────────────────────────────────

def format_event(event, compact=False):
    """Format a single event for display."""
    etype = event.get("type", "")
    sender = short_sender(event.get("sender", ""))
    content = event.get("content", {})
    ts = event.get("origin_server_ts", 0)
    event_id = event.get("event_id", "")
    dt = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
    
    if etype == "m.reaction":
        key = content.get("m.relates_to", {}).get("key", "?")
        target = content.get("m.relates_to", {}).get("event_id", "?")[:20]
        if compact:
            return f"{dt} | ⚡ {sender} reacted {key} to {target}"
        return f"  ⚡ {dt} — {sender} reacted {key}\n    └─ on event {target}"
    
    if etype == "m.room.message":
        body = content.get("body", "")
        msgtype = content.get("msgtype", "m.text")
        relates = content.get("m.relates_to", {})
        
        # Skip message edits (show only final version)
        if relates.get("rel_type") == "m.replace":
            return None
        
        # Check if this is a reply
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
        
        type_icon = {"m.text": "💬", "m.notice": "📋", "m.image": "🖼️", "m.emote": "🎭"}.get(msgtype, "📨")
        
        if compact:
            body_short = body[:120].replace("\n", " ")
            reply_marker = " [reply]" if reply_to else ""
            return f"{dt} | {type_icon} {sender}{reply_marker} | {body_short}"
        
        lines = [f"  {type_icon} {dt} — {sender}"]
        if reply_to:
            lines[0] += f"  (reply to {reply_to[:20]})"
        lines.append(f"    {event_id}")
        # Indent message body
        for line in body.split("\n")[:10]:
            lines.append(f"    {line}")
        if body.count("\n") > 10:
            lines.append(f"    ... ({body.count(chr(10)) - 10} more lines)")
        return "\n".join(lines)
    
    return None


def format_events(events, compact=False):
    """Format a list of events for display."""
    # Reverse to show oldest first (chronological)
    events = list(reversed(events))
    
    lines = []
    for event in events:
        formatted = format_event(event, compact=compact)
        if formatted:
            lines.append(formatted)
    return "\n".join(lines) if lines else "(no messages)"


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Read messages from Matrix rooms")
    parser.add_argument("--room", help="Room alias or ID (e.g., 'general', 'drafts')")
    parser.add_argument("--all", action="store_true", help="Check all joined rooms")
    parser.add_argument("--since", type=int, default=120, help="Messages from last N minutes (default: 120)")
    parser.add_argument("--limit", type=int, default=50, help="Max messages to fetch (default: 50)")
    parser.add_argument("--from", dest="from_user", help="Filter to messages from this sender")
    parser.add_argument("--humans-only", action="store_true", help="Exclude bot/agent messages")
    parser.add_argument("--reactions-for", dest="reactions_for", help="Show reactions on a specific event ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--compact", action="store_true", help="One-line-per-message format")
    args = parser.parse_args()
    
    if not args.room and not args.all and not args.reactions_for:
        parser.print_help()
        sys.exit(1)
    
    # Handle reactions-for query
    if args.reactions_for:
        if not args.room:
            print("ERROR: --reactions-for requires --room", file=sys.stderr)
            sys.exit(1)
        room_id = resolve_room(args.room)
        reactions = fetch_reactions_for(room_id, args.reactions_for)
        if args.json:
            print(json.dumps(reactions, indent=2))
        else:
            if not reactions:
                print(f"No reactions found on {args.reactions_for[:20]}")
            else:
                print(f"Reactions on {args.reactions_for[:30]}:")
                for r in reactions:
                    sender = short_sender(r.get("sender", ""))
                    key = r.get("content", {}).get("m.relates_to", {}).get("key", "?")
                    print(f"  {key} — {sender}")
        return
    
    # Determine rooms to check
    if args.all:
        rooms = get_joined_rooms()
    else:
        rooms = [resolve_room(args.room)]
    
    all_results = {}
    
    for room_id in rooms:
        events = fetch_messages(room_id, limit=args.limit, since_minutes=args.since)
        
        # Advance heartbeat watermarks so the heartbeat won't re-report
        # messages we've already seen via manual reads.
        if events:
            max_ts = max(e.get("origin_server_ts", 0) for e in events)
            if max_ts > 0:
                room_name = get_room_name(room_id)
                _advance_watermark(room_name, max_ts)
        
        # Filter by sender
        if args.from_user:
            events = [e for e in events if args.from_user in e.get("sender", "")]
        
        # Filter to humans only
        if args.humans_only:
            events = [e for e in events if e.get("sender", "") not in BOT_USERS]
        
        # Only include rooms that have visible content events (messages + reactions, not edits or state)
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
        # Flatten for JSON output
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
            print(f"\n{'═' * 50}")
            print(f"  📫 {name}  ({visible_count} messages)")
            print(f"{'═' * 50}")
            print(formatted)
            print()


if __name__ == "__main__":
    main()
