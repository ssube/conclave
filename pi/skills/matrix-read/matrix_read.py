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

# ─── Room Aliases ───────────────────────────────────────────────────────────

_SERVER_NAME = os.environ.get("MATRIX_SERVER_NAME", os.environ.get("AGENT_MATRIX_SERVER_NAME", "conclave.local"))

ROOM_ALIASES = {
    "home": f"#home:{_SERVER_NAME}",
}

# Known bot/agent user IDs (for --humans-only filtering)
_AGENT_USER = os.environ.get("CONCLAVE_AGENT_USER", os.environ.get("AGENT_MATRIX_USER", "pi"))
BOT_USERS = {
    f"@{_AGENT_USER}:{_SERVER_NAME}",
}

# ─── Matrix API Helpers ─────────────────────────────────────────────────────

_cached_token = None

def _login_for_token(homeserver):
    """Login with AGENT_MATRIX_USER/PASSWORD to get an access token."""
    user = os.environ.get("AGENT_MATRIX_USER", "")
    password = os.environ.get("AGENT_MATRIX_PASSWORD", "")
    if not user or not password:
        return ""
    payload = json.dumps({"type": "m.login.password", "user": user, "password": password}).encode()
    req = urllib.request.Request(
        f"{homeserver}/_matrix/client/v3/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("access_token", "")
    except Exception:
        return ""

def matrix_get(path, params=None):
    """Make an authenticated GET request to the Matrix API."""
    global _cached_token
    homeserver = os.environ.get("MATRIX_HOMESERVER_URL", os.environ.get("AGENT_MATRIX_URL", "http://127.0.0.1:8008")).rstrip("/")
    token = os.environ.get("MATRIX_ACCESS_TOKEN", "") or _cached_token or ""

    # Auto-login if no token available
    if not token:
        token = _login_for_token(homeserver)
        if token:
            _cached_token = token

    if not homeserver or not token:
        print("ERROR: No Matrix credentials available. Set MATRIX_ACCESS_TOKEN or AGENT_MATRIX_USER/PASSWORD", file=sys.stderr)
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
      - Internal IDs: !abc123:server
      - Shortnames: home (or any key in ROOM_ALIASES)
      - Full alias format: #home:server (resolved via Matrix directory API)
    """
    if room_str.startswith("!"):
        return room_str
    if room_str in ROOM_ALIASES:
        # Aliases starting with # need to be resolved via the directory API
        alias = ROOM_ALIASES[room_str]
        if alias.startswith("#"):
            return _resolve_alias(alias)
        return alias

    # If it looks like a full alias (#room:server), resolve via API
    if room_str.startswith("#"):
        return _resolve_alias(room_str)

    # Try as an alias with server name appended
    full_alias = f"#{room_str}:{_SERVER_NAME}"
    try:
        return _resolve_alias(full_alias)
    except SystemExit:
        pass

    print(f"ERROR: Unknown room '{room_str}'. Known: {', '.join(ROOM_ALIASES.keys())}", file=sys.stderr)
    sys.exit(1)


def _resolve_alias(alias):
    """Resolve a Matrix room alias to a room ID via the directory API."""
    encoded = urllib.parse.quote(alias)
    data = matrix_get(f"/_matrix/client/v3/directory/room/{encoded}")
    room_id = data.get("room_id")
    if not room_id:
        print(f"ERROR: Could not resolve alias '{alias}'", file=sys.stderr)
        sys.exit(1)
    return room_id


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
