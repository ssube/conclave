#!/usr/bin/env python3
"""
Planka Skill — Manage tasks and projects on the Planka kanban board.

Python rewrite of planka.sh for structured error handling, retry logic,
and reliable JSON parsing without jq piping.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

# ─── Configuration ──────────────────────────────────────────────────────────

PLANKA_URL = os.environ.get("AGENT_PLANKA_URL", "").rstrip("/")
PLANKA_TOKEN = os.environ.get("AGENT_PLANKA_TOKEN", "")

# Configure your board IDs here, or set PLANKA_BOARDS env var as JSON
# Example: export PLANKA_BOARDS='{"main": "123456789", "dev": "987654321"}'
import json as _json
_boards_env = os.environ.get("PLANKA_BOARDS", "")
BOARD_IDS = _json.loads(_boards_env) if _boards_env else {
    "main": "YOUR_BOARD_ID_HERE",
}

DEFAULT_BOARD = os.environ.get("PLANKA_DEFAULT_BOARD", list(BOARD_IDS.keys())[0] if BOARD_IDS else "main")


# ─── API Layer ──────────────────────────────────────────────────────────────

class PlankaError(Exception):
    """Raised when a Planka API call fails."""
    pass


def api_call(method: str, endpoint: str, data: dict | None = None,
             max_retries: int = 3) -> dict:
    """
    Make an authenticated API call to Planka with retry logic.

    Returns parsed JSON response. Raises PlankaError on failure.
    """
    url = f"{PLANKA_URL}/api{endpoint}"
    headers = {
        "Authorization": f"Bearer {PLANKA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.dumps(data).encode() if data else None

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                refresh_token()
                headers["Authorization"] = f"Bearer {PLANKA_TOKEN}"
                continue
            if e.code >= 500 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise PlankaError(f"HTTP {e.code}: {error_body}")
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise PlankaError(f"Connection failed: {e}")
        except json.JSONDecodeError:
            return {}

    raise PlankaError(f"All {max_retries} attempts failed for {method} {endpoint}")


def refresh_token():
    """Refresh the API token using stored credentials."""
    global PLANKA_TOKEN
    username = os.environ.get("AGENT_PLANKA_USER", "")
    password = os.environ.get("AGENT_PLANKA_PASSWORD", "")

    if not username or not password:
        raise PlankaError("Token expired. Set AGENT_PLANKA_USER and AGENT_PLANKA_PASSWORD for auto-refresh.")

    body = json.dumps({"emailOrUsername": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{PLANKA_URL}/api/access-tokens",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            new_token = json.loads(resp.read()).get("item", "")
    except Exception as e:
        raise PlankaError(f"Token refresh failed: {e}")

    if not new_token:
        raise PlankaError("Token refresh returned empty token")

    PLANKA_TOKEN = new_token

    # Update .env if it exists
    env_path = os.environ.get("ENV_FILE", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
        with open(env_path, "w") as f:
            for line in lines:
                if line.startswith("AGENT_PLANKA_TOKEN="):
                    f.write(f"AGENT_PLANKA_TOKEN={new_token}\n")
                else:
                    f.write(line)

    print(f"Token refreshed", file=sys.stderr)


# ─── Board Helpers ──────────────────────────────────────────────────────────

def get_board_data(board_id: str) -> dict:
    """Fetch full board data (lists, cards, labels, etc.)."""
    return api_call("GET", f"/boards/{board_id}")


def get_list_id(board_data: dict, list_name: str) -> str | None:
    """Find a list ID by name (case-insensitive)."""
    for lst in board_data.get("included", {}).get("lists", []):
        if lst["name"].lower() == list_name.lower():
            return lst["id"]
    return None


def get_label_id(board_data: dict, label_name: str) -> str | None:
    """Find a label ID by name (case-insensitive)."""
    for label in board_data.get("included", {}).get("labels", []):
        if label["name"].lower() == label_name.lower():
            return label["id"]
    return None


def next_position(board_data: dict, list_id: str) -> int:
    """Calculate the next card position in a list."""
    positions = [
        card["position"]
        for card in board_data.get("included", {}).get("cards", [])
        if card.get("listId") == list_id
    ]
    return (max(positions) if positions else 0) + 65535


# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_create(board_id: str, args):
    """Create a new card."""
    board_data = get_board_data(board_id)

    list_name = args.list or "backlog"
    list_id = get_list_id(board_data, list_name)
    if not list_id:
        print(f"Error: List not found: {list_name}", file=sys.stderr)
        sys.exit(1)

    pos = next_position(board_data, list_id)
    payload = {"name": args.title, "position": pos, "type": "story"}
    if args.description:
        payload["description"] = args.description

    response = api_call("POST", f"/lists/{list_id}/cards", payload)
    card_id = response.get("item", {}).get("id")

    if not card_id:
        print(f"Error creating card: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)

    # Add labels
    if args.labels:
        for label_name in [l.strip() for l in args.labels.split(",")]:
            label_id = get_label_id(board_data, label_name)
            if label_id:
                api_call("POST", f"/cards/{card_id}/labels", {"labelId": label_id})
            else:
                print(f"Warning: Label not found: {label_name}", file=sys.stderr)

    print(f"Card created successfully")
    print(f"")
    print(f"ID: {card_id}")
    print(f"Title: {args.title}")
    print(f"List: {list_name}")
    if args.labels:
        print(f"Labels: {args.labels}")


def cmd_list(board_id: str, args):
    """List cards on the board."""
    board_data = get_board_data(board_id)
    included = board_data.get("included", {})

    lists = {lst["id"]: lst["name"] for lst in included.get("lists", [])}
    labels = {lbl["id"]: lbl["name"] for lbl in included.get("labels", [])}
    card_labels = {}
    for cl in included.get("cardLabels", []):
        card_labels.setdefault(cl["cardId"], []).append(labels.get(cl["labelId"], "?"))

    cards = []
    for card in included.get("cards", []):
        list_name = lists.get(card.get("listId"), "?")
        card_label_names = card_labels.get(card["id"], [])

        # Apply filters
        if args.list and list_name.lower() != args.list.lower():
            continue
        if args.label and args.label.lower() not in [l.lower() for l in card_label_names]:
            continue

        cards.append({
            "id": card["id"],
            "name": card["name"],
            "list": list_name,
            "labels": card_label_names,
            "position": card.get("position", 0),
        })

    # Sort by list name, then position
    cards.sort(key=lambda c: (c["list"], c["position"]))

    active_board = [k for k, v in BOARD_IDS.items() if v == board_id]
    board_name = active_board[0] if active_board else board_id
    print(f"=== Cards: {board_name} board ===")
    if args.list:
        print(f"Filter: list={args.list}")
    if args.label:
        print(f"Filter: label={args.label}")
    print()

    if not cards:
        print("No cards found.")
        return

    for card in cards:
        label_str = ", ".join(card["labels"]) if card["labels"] else "None"
        print(f"[{card['list']}] {card['name']}")
        print(f"  ID: {card['id']}")
        print(f"  Labels: {label_str}")
        print()


def cmd_get(board_id: str, args):
    """Get detailed card info including comments and tasks."""
    response = api_call("GET", f"/cards/{args.card_id}")
    card = response.get("item")
    included = response.get("included", {})

    if not card:
        print(f"Error: Card not found: {args.card_id}", file=sys.stderr)
        sys.exit(1)

    label_names = [lbl["name"] for lbl in included.get("labels", [])]
    tasks = included.get("tasks", [])

    print("=== Card Details ===")
    print()
    print(f"ID: {card['id']}")
    print(f"Title: {card['name']}")
    print(f"Description: {card.get('description') or 'None'}")
    print(f"Created: {card.get('createdAt', 'Unknown')}")
    print(f"Due Date: {card.get('dueDate') or 'None'}")
    print(f"Labels: {', '.join(label_names) if label_names else 'None'}")

    if tasks:
        print()
        print("Tasks:")
        for task in tasks:
            mark = "x" if task.get("isCompleted") else " "
            print(f"  [{mark}] {task['name']}")

    # Fetch comments
    actions_response = api_call("GET", f"/cards/{args.card_id}/actions")
    items = actions_response.get("items", [])
    users = {u["id"]: u.get("name") or u.get("username", "Unknown")
             for u in actions_response.get("included", {}).get("users", [])}

    comments = [a for a in items if a.get("type") == "commentCard"]
    comments.sort(key=lambda c: c.get("createdAt", ""))

    if comments:
        print()
        print(f"Comments ({len(comments)}):")
        for comment in comments:
            author = users.get(comment.get("userId"), "Unknown")
            date = comment.get("createdAt", "")[:10]
            text = comment.get("data", {}).get("text", "")
            print(f"  [{date}] {author}: {text}")


def cmd_comment(board_id: str, args):
    """Add a comment to a card."""
    response = api_call("POST", f"/cards/{args.card_id}/comment-actions",
                        {"text": args.text})
    comment_id = response.get("item", {}).get("id")

    if not comment_id:
        print(f"Error creating comment: {json.dumps(response)}", file=sys.stderr)
        sys.exit(1)

    print(f"Comment added to card {args.card_id}")
    print(f"Comment ID: {comment_id}")


def cmd_move(board_id: str, args):
    """Move a card to another list."""
    card_response = api_call("GET", f"/cards/{args.card_id}")
    card_board_id = card_response.get("item", {}).get("boardId")

    if not card_board_id:
        print(f"Error: Card not found: {args.card_id}", file=sys.stderr)
        sys.exit(1)

    board_data = get_board_data(card_board_id)
    list_id = get_list_id(board_data, args.list)
    if not list_id:
        print(f"Error: List not found: {args.list}", file=sys.stderr)
        sys.exit(1)

    pos = next_position(board_data, list_id)
    api_call("PATCH", f"/cards/{args.card_id}", {"listId": list_id, "position": pos})
    print(f"Card moved to: {args.list}")


def cmd_complete(board_id: str, args):
    """Mark a card as complete (move to done)."""
    card_response = api_call("GET", f"/cards/{args.card_id}")
    card_board_id = card_response.get("item", {}).get("boardId")

    if not card_board_id:
        print(f"Error: Card not found: {args.card_id}", file=sys.stderr)
        sys.exit(1)

    board_data = get_board_data(card_board_id)
    list_id = get_list_id(board_data, "done")
    if not list_id:
        print(f"Error: 'done' list not found in board", file=sys.stderr)
        sys.exit(1)

    pos = next_position(board_data, list_id)
    api_call("PATCH", f"/cards/{args.card_id}", {"listId": list_id, "position": pos})
    print("Card marked as complete")


def cmd_update(board_id: str, args):
    """Update card properties."""
    card_response = api_call("GET", f"/cards/{args.card_id}")
    card_board_id = card_response.get("item", {}).get("boardId")

    if not card_board_id:
        print(f"Error: Card not found: {args.card_id}", file=sys.stderr)
        sys.exit(1)

    # Update title/description
    payload = {}
    if args.title:
        payload["name"] = args.title
    if args.description:
        payload["description"] = args.description
    if payload:
        api_call("PATCH", f"/cards/{args.card_id}", payload)

    # Add label
    if args.add_label:
        board_data = get_board_data(card_board_id)
        label_id = get_label_id(board_data, args.add_label)
        if label_id:
            api_call("POST", f"/cards/{args.card_id}/labels", {"labelId": label_id})
        else:
            print(f"Warning: Label not found: {args.add_label}", file=sys.stderr)

    # Remove label
    if args.remove_label:
        board_data = get_board_data(card_board_id)
        label_id = get_label_id(board_data, args.remove_label)
        if label_id:
            card_data = api_call("GET", f"/cards/{args.card_id}")
            for cl in card_data.get("included", {}).get("cardLabels", []):
                if cl.get("labelId") == label_id:
                    api_call("DELETE", f"/card-labels/{cl['id']}")
                    break

    print(f"Card updated: {args.card_id}")


def cmd_delete(board_id: str, args):
    """Delete a card."""
    api_call("DELETE", f"/cards/{args.card_id}")
    print(f"Card deleted: {args.card_id}")


def cmd_boards(board_id: str, args):
    """Show all known boards."""
    print("=== Boards ===")
    print()
    for name, bid in sorted(BOARD_IDS.items()):
        marker = " (active)" if bid == board_id else ""
        print(f"  {name}: {bid}{marker}")


def cmd_labels(board_id: str, args):
    """List labels for the active board."""
    board_data = get_board_data(board_id)
    print(f"=== Labels ===")
    print()
    for label in board_data.get("included", {}).get("labels", []):
        print(f"  {label['name']} (color: {label.get('color', 'none')})")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Planka kanban board management")
    parser.add_argument("--board", default=os.environ.get("PLANKA_BOARD", DEFAULT_BOARD),
                        choices=list(BOARD_IDS.keys()) if BOARD_IDS else None,
                        help=f"Board to operate on (default: {DEFAULT_BOARD})")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # create
    p_create = subparsers.add_parser("create", help="Create a new card")
    p_create.add_argument("--title", required=True, help="Card title")
    p_create.add_argument("--description", default="", help="Card description")
    p_create.add_argument("--list", default=None, help="Target list (default: backlog)")
    p_create.add_argument("--labels", default="", help="Comma-separated label names")

    # list
    p_list = subparsers.add_parser("list", help="List cards on the board")
    p_list.add_argument("--list", default="", help="Filter by list name")
    p_list.add_argument("--label", default="", help="Filter by label name")

    # get
    p_get = subparsers.add_parser("get", help="Get card details")
    p_get.add_argument("card_id", help="Card ID")

    # comment
    p_comment = subparsers.add_parser("comment", help="Add a comment to a card")
    p_comment.add_argument("card_id", help="Card ID")
    p_comment.add_argument("--text", required=True, help="Comment text")

    # move
    p_move = subparsers.add_parser("move", help="Move card to another list")
    p_move.add_argument("card_id", help="Card ID")
    p_move.add_argument("--list", required=True, help="Target list name")

    # complete
    p_complete = subparsers.add_parser("complete", help="Mark card as done")
    p_complete.add_argument("card_id", help="Card ID")

    # update
    p_update = subparsers.add_parser("update", help="Update card properties")
    p_update.add_argument("card_id", help="Card ID")
    p_update.add_argument("--title", default="", help="New title")
    p_update.add_argument("--description", default="", help="New description")
    p_update.add_argument("--add-label", default="", help="Label to add")
    p_update.add_argument("--remove-label", default="", help="Label to remove")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a card")
    p_delete.add_argument("card_id", help="Card ID")

    # boards
    subparsers.add_parser("boards", help="Show available boards")

    # labels
    subparsers.add_parser("labels", help="List labels for active board")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Validate config
    if not PLANKA_URL:
        print("Error: AGENT_PLANKA_URL environment variable not set", file=sys.stderr)
        sys.exit(1)
    if not PLANKA_TOKEN:
        # Try auto-login
        try:
            refresh_token()
        except PlankaError:
            print("Error: AGENT_PLANKA_TOKEN not set and auto-login failed (set AGENT_PLANKA_USER and AGENT_PLANKA_PASSWORD)", file=sys.stderr)
            sys.exit(1)

    board_id = BOARD_IDS[args.board]

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "get": cmd_get,
        "comment": cmd_comment,
        "move": cmd_move,
        "complete": cmd_complete,
        "update": cmd_update,
        "delete": cmd_delete,
        "boards": cmd_boards,
        "labels": cmd_labels,
    }

    try:
        commands[args.command](board_id, args)
    except PlankaError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
