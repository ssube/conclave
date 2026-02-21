#!/usr/bin/env bash
set -euo pipefail

# Self-load environment (idempotent — won't override already-set vars)
[[ -f /workspace/.env ]] && set -a && source /workspace/.env 2>/dev/null && set +a || true
[[ -f /workspace/.env.thalis ]] && set -a && source /workspace/.env.thalis 2>/dev/null && set +a || true

# Matrix Send — Post messages, images, and videos to Matrix rooms
# Usage:
#   send.sh <room> "<message>"
#   send.sh <room> --image <path> [--caption "<text>"]
#   send.sh <room> --file <path> [--caption "<text>"]       (alias for --image)
#   send.sh <room> --video <path> [--caption "<text>"]

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOMESERVER="${MATRIX_HOMESERVER_URL:-https://matrix.home.holdmyran.ch}"
ACCESS_TOKEN="${MATRIX_ACCESS_TOKEN:-}"

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "ERROR: MATRIX_ACCESS_TOKEN not set" >&2
  exit 1
fi

# Room alias mappings (matching matrix-read skill)
declare -A ROOM_MAP=(
  [general]="!EOujKPtUOJPbbyBnHr:matrix.home.holdmyran.ch"
  [drafts]="!DTwKgcNMAqKTqCCbyY:matrix.home.holdmyran.ch"
  [published]="!HRUMcHLpGmtWRPMjpz:matrix.home.holdmyran.ch"
  [data]="!AXdouVagECaWEfWlqF:matrix.home.holdmyran.ch"
  [image]="!oGVcqxQeeZWtYNqWIk:matrix.home.holdmyran.ch"
  [calendar]="!xJqiFXNHCVTkaeoIfl:matrix.home.holdmyran.ch"
)

# Resolve room alias to room ID
resolve_room() {
  local room="$1"

  if [[ "$room" =~ ^! ]]; then
    echo "$room"
    return
  fi

  if [[ -n "${ROOM_MAP[$room]:-}" ]]; then
    echo "${ROOM_MAP[$room]}"
    return
  fi

  if [[ "$room" =~ ^# ]]; then
    local encoded
    encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$room', safe=''))")
    local resolve_url="${HOMESERVER}/_matrix/client/v3/directory/room/${encoded}"
    local response
    response=$(curl -s -H "Authorization: Bearer ${ACCESS_TOKEN}" "$resolve_url")
    local room_id
    room_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('room_id', ''))" 2>/dev/null || echo "")
    if [[ -n "$room_id" ]]; then
      echo "$room_id"
      return
    fi
  fi

  echo "ERROR: Unknown room '$room'. Known aliases: ${!ROOM_MAP[*]}" >&2
  exit 1
}

# Detect MIME type from file extension
detect_mime() {
  local ext="${1##*.}"
  ext="${ext,,}"
  case "$ext" in
    png)       echo "image/png" ;;
    jpg|jpeg)  echo "image/jpeg" ;;
    gif)       echo "image/gif" ;;
    webp)      echo "image/webp" ;;
    mp4)       echo "video/mp4" ;;
    webm)      echo "video/webm" ;;
    mov)       echo "video/quicktime" ;;
    mkv)       echo "video/x-matroska" ;;
    avi)       echo "video/x-msvideo" ;;
    *)         echo "application/octet-stream" ;;
  esac
}

# Rate limit config
MAX_RETRIES="${MATRIX_MAX_RETRIES:-5}"
DEFAULT_RETRY_WAIT=5  # seconds, if server doesn't specify retry_after_ms

# Check if a response is a rate limit error — returns 0 (true) if rate-limited
is_rate_limited() {
  local response="$1"
  echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('errcode') == 'M_LIMIT_EXCEEDED':
        ms = d.get('retry_after_ms', ${DEFAULT_RETRY_WAIT}000)
        print(max(1, (ms + 999) // 1000))  # ceil to seconds, min 1s
        sys.exit(0)
except: pass
sys.exit(1)
" 2>/dev/null
}

# Upload a file to Matrix media repo — prints mxc:// URI
# Retries on rate limit with server-specified backoff
upload_media() {
  local filepath="$1"
  local content_type="$2"
  local filename
  filename=$(basename "$filepath")

  local encoded_filename
  encoded_filename=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$filename")

  local attempt=0
  while (( attempt < MAX_RETRIES )); do
    local response
    response=$(curl -s -X POST \
      "${HOMESERVER}/_matrix/media/v3/upload?filename=${encoded_filename}" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H "Content-Type: ${content_type}" \
      --data-binary "@${filepath}")

    local mxc_uri
    mxc_uri=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('content_uri', ''))" 2>/dev/null || echo "")

    if [[ -n "$mxc_uri" ]]; then
      echo "$mxc_uri"
      return 0
    fi

    # Check for rate limit
    local wait_secs
    wait_secs=$(echo "$response" | is_rate_limited) || {
      # Not rate-limited — genuine error
      echo "ERROR: Upload failed: $response" >&2
      return 1
    }

    attempt=$((attempt + 1))
    echo "⏳ Rate limited on upload. Waiting ${wait_secs}s before retry ${attempt}/${MAX_RETRIES}..." >&2
    sleep "$wait_secs"
  done

  echo "ERROR: Upload failed after ${MAX_RETRIES} retries (rate limited)" >&2
  return 1
}

# Send a Matrix event — prints event ID
# Retries on rate limit with server-specified backoff
send_event() {
  local room_id="$1"
  local payload="$2"

  local url="${HOMESERVER}/_matrix/client/v3/rooms/${room_id}/send/m.room.message"

  local attempt=0
  while (( attempt < MAX_RETRIES )); do
    local response
    response=$(curl -s -X POST "$url" \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$payload")

    local event_id
    event_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('event_id', ''))" 2>/dev/null || echo "")

    if [[ -n "$event_id" ]]; then
      echo "✅ Sent. Event ID: $event_id"
      return 0
    fi

    # Check for rate limit
    local wait_secs
    wait_secs=$(echo "$response" | is_rate_limited) || {
      # Not rate-limited — genuine error
      echo "❌ Failed: $response" >&2
      exit 1
    }

    attempt=$((attempt + 1))
    echo "⏳ Rate limited on send. Waiting ${wait_secs}s before retry ${attempt}/${MAX_RETRIES}..." >&2
    sleep "$wait_secs"
  done

  echo "❌ Failed after ${MAX_RETRIES} retries (rate limited)" >&2
  exit 1
}

# Send a text message
send_text() {
  local room_id="$1"
  local message="$2"

  local payload
  payload=$(python3 -c "
import json, sys
print(json.dumps({'msgtype': 'm.text', 'body': sys.argv[1]}))
" "$message")

  send_event "$room_id" "$payload"
}

# Send an image
# body = filename (with extension) — required for inline rendering
# Caption sent as separate text message if provided
send_image() {
  local room_id="$1"
  local filepath="$2"
  local caption="${3:-}"

  if [[ ! -f "$filepath" ]]; then
    echo "ERROR: File not found: $filepath" >&2
    exit 1
  fi

  local filename
  filename=$(basename "$filepath")
  local content_type
  content_type=$(detect_mime "$filepath")
  local filesize
  filesize=$(stat -c%s "$filepath")

  echo "Uploading $filename..." >&2
  local mxc_uri
  mxc_uri=$(upload_media "$filepath" "$content_type") || exit 1

  local payload
  payload=$(python3 -c "
import json, sys
print(json.dumps({
    'msgtype': 'm.image',
    'body': sys.argv[1],
    'url': sys.argv[2],
    'info': {
        'mimetype': sys.argv[3],
        'size': int(sys.argv[4]),
    }
}))
" "$filename" "$mxc_uri" "$content_type" "$filesize")

  # Send caption first if provided
  if [[ -n "$caption" ]]; then
    send_text "$room_id" "$caption"
  fi

  send_event "$room_id" "$payload"
}

# Send a video
# body = filename (with extension) — required for inline rendering
# Caption sent as separate text message if provided
send_video() {
  local room_id="$1"
  local filepath="$2"
  local caption="${3:-}"

  if [[ ! -f "$filepath" ]]; then
    echo "ERROR: File not found: $filepath" >&2
    exit 1
  fi

  local filename
  filename=$(basename "$filepath")
  local content_type
  content_type=$(detect_mime "$filepath")
  local filesize
  filesize=$(stat -c%s "$filepath")

  echo "Uploading $filename..." >&2
  local mxc_uri
  mxc_uri=$(upload_media "$filepath" "$content_type") || exit 1

  local payload
  payload=$(python3 -c "
import json, sys
print(json.dumps({
    'msgtype': 'm.video',
    'body': sys.argv[1],
    'url': sys.argv[2],
    'info': {
        'mimetype': sys.argv[3],
        'size': int(sys.argv[4]),
    }
}))
" "$filename" "$mxc_uri" "$content_type" "$filesize")

  # Send caption first if provided
  if [[ -n "$caption" ]]; then
    send_text "$room_id" "$caption"
  fi

  send_event "$room_id" "$payload"
}

# Send a batch of images with pacing to avoid rate limits
# Usage: send_batch <room_id> <delay_seconds> <file1> [caption1] <file2> [caption2] ...
send_batch() {
  local room_id="$1"
  local delay="$2"
  shift 2

  local count=0
  local total=0
  local files=()
  local captions=()

  # Parse file/caption pairs from remaining args
  while [[ $# -gt 0 ]]; do
    files+=("$1")
    captions+=("${2:-}")
    total=$((total + 1))
    shift
    [[ $# -gt 0 ]] && shift || true
  done

  echo "📤 Sending batch: ${total} images with ${delay}s pacing" >&2

  for i in "${!files[@]}"; do
    local filepath="${files[$i]}"
    local caption="${captions[$i]}"
    count=$((count + 1))

    if [[ ! -f "$filepath" ]]; then
      echo "  ⚠️ Skipping missing file: $filepath" >&2
      continue
    fi

    local filename
    filename=$(basename "$filepath")
    echo "  [${count}/${total}] ${filename}" >&2

    # Detect if image or video
    local mime
    mime=$(detect_mime "$filepath")
    if [[ "$mime" == video/* ]]; then
      send_video "$room_id" "$filepath" "$caption"
    else
      send_image "$room_id" "$filepath" "$caption"
    fi

    # Pace between sends (skip delay after last item)
    if (( count < total )); then
      echo "  ⏳ Waiting ${delay}s..." >&2
      sleep "$delay"
    fi
  done

  echo "✅ Batch complete: ${count}/${total} sent" >&2
}


# --- Argument parsing ---
usage() {
  cat >&2 <<EOF
Usage:
  send.sh <room> "<message>"
  send.sh <room> --image <path> [--caption "<text>"]
  send.sh <room> --file <path> [--caption "<text>"]        (alias for --image)
  send.sh <room> --video <path> [--caption "<text>"]
  send.sh <room> --batch <delay_secs> --image <path1> [--caption "<text>"] --image <path2> ...

Rooms: ${!ROOM_MAP[*]}
Also accepts full room IDs (!xxx:server) or Matrix aliases (#room:server).

Options:
  --image <path>        Send an image (png, jpg, gif, webp)
  --file <path>         Alias for --image (auto-detects image vs video by extension)
  --video <path>        Send a video (mp4, webm, mov, mkv, avi)
  --caption "<text>"    Optional caption sent before the media
  --batch <seconds>     Batch mode: send multiple images with delay between each
                        Pair each --image/--video/--file with an optional --caption
EOF
  exit 1
}

if [[ $# -lt 2 ]]; then
  usage
fi

room_input="$1"
shift

room_id=$(resolve_room "$room_input")

# Simple case: no flags = text message
if [[ "$1" != "--image" && "$1" != "--video" && "$1" != "--batch" && "$1" != "--file" ]]; then
  # Guard: if it looks like an unknown flag, error instead of sending "--flag" as text
  if [[ "$1" == --* ]]; then
    echo "ERROR: Unknown flag '$1'. Use --image, --video, --file, or --batch." >&2
    usage
  fi
  send_text "$room_id" "$1"
  exit 0
fi

# Check for batch mode
if [[ "$1" == "--batch" ]]; then
  batch_delay="$2"
  shift 2

  # Collect file/caption pairs
  batch_args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --image|--video|--file)
        batch_args+=("$2" "")  # placeholder caption
        # Check if next arg is --caption
        shift 2
        if [[ $# -gt 0 && "$1" == "--caption" ]]; then
          # Replace the empty caption we just added
          batch_args[-1]="$2"
          shift 2
        fi
        ;;
      *) echo "ERROR: In batch mode, expected --image, --video, or --file, got: $1" >&2; usage ;;
    esac
  done

  send_batch "$room_id" "$batch_delay" "${batch_args[@]}"
  exit 0
fi

# Single media mode — flag-based parsing
media_type=""
media_path=""
caption=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) media_type="image"; media_path="$2"; shift 2 ;;
    --file)
      # Auto-detect: if it's a video extension, treat as video; otherwise image
      media_path="$2"
      mime_check=$(detect_mime "$media_path")
      if [[ "$mime_check" == video/* ]]; then
        media_type="video"
      else
        media_type="image"
      fi
      shift 2
      ;;
    --video)  media_type="video"; media_path="$2"; shift 2 ;;
    --caption) caption="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$media_type" || -z "$media_path" ]]; then
  usage
fi

case "$media_type" in
  image) send_image "$room_id" "$media_path" "$caption" ;;
  video) send_video "$room_id" "$media_path" "$caption" ;;
esac
