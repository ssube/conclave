---
name: matrix-send
description: >-
  Send messages, images, and videos to Matrix rooms. Use when posting updates to channels, sharing images or video, sending notifications, reporting progress, or communicating via Matrix during autonomous sessions.
---

# Matrix Send

Send messages and media to Matrix rooms. Use the Pi `send` tool for text messages. For images/video, use the send.sh script or curl to the Matrix API.

## Pi Send Tool (Preferred for Text)

The Pi runtime has a built-in `send` tool — use it for plain text. You need the internal room ID (resolve aliases first via the Matrix directory API or use `matrix_read.py`).

## Room Aliases

| Alias | Resolved As |
|-------|-------------|
| `home` | `#home:<MATRIX_SERVER_NAME>` |

Aliases are resolved via the Matrix directory API. Any room alias (`#room:server`) or internal room ID (`!id:server`) can also be used directly.

## Environment

- `MATRIX_HOMESERVER_URL` — Homeserver base URL (falls back to `AGENT_MATRIX_URL`, default `http://127.0.0.1:8008`)
- `MATRIX_ACCESS_TOKEN` — Bot access token
- `MATRIX_SERVER_NAME` — Matrix server name for alias resolution (falls back to `AGENT_MATRIX_SERVER_NAME`)

## Send Text via curl

```bash
curl -sf -X PUT \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"msgtype": "m.text", "body": "Hello"}' \
  "${MATRIX_HOMESERVER_URL}/_matrix/client/v3/rooms/ROOM_ID/send/m.room.message/$(date +%s%N)"
```

The txnId (last path segment) must be unique per request — `date +%s%N` works.

## Send Image / Video via send.sh

The `send.sh` script handles upload + send in one step:

```bash
# Send an image
bash {baseDir}/send.sh <room> --file /path/to/image.png

# Send an image with caption (caption sent as separate text message before the image)
bash {baseDir}/send.sh <room> --file /path/to/image.png --caption "Description here"

# Send a video (auto-detected by extension, or use --video explicitly)
bash {baseDir}/send.sh <room> --file /path/to/video.mp4

# Batch: multiple images with pacing
bash {baseDir}/send.sh <room> --batch 3 \
  --file /path/to/img1.png --caption "First" \
  --file /path/to/img2.png --caption "Second"
```

**Flags:** `--file` auto-detects image vs video by extension. `--image` and `--video` also work as explicit alternatives.

## Send Image / Video via curl (manual)

### Step 1: Upload media

```bash
MXC_URL=$(curl -sf -X POST \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: image/png" \
  --data-binary @/path/to/image.png \
  "${MATRIX_HOMESERVER_URL}/_matrix/media/v3/upload?filename=image.png" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['content_uri'])")
```

### Step 2: Send image event

```bash
curl -sf -X PUT \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"msgtype\": \"m.image\", \"body\": \"image.png\", \"url\": \"$MXC_URL\"}" \
  "${MATRIX_HOMESERVER_URL}/_matrix/client/v3/rooms/ROOM_ID/send/m.room.message/$(date +%s%N)"
```

For video: use `Content-Type: video/mp4` on upload and `msgtype: "m.video"` on send.

## Formatted Messages (HTML)

```bash
curl -sf -X PUT \
  -H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"msgtype": "m.text", "body": "**Bold** text", "format": "org.matrix.custom.html", "formatted_body": "<b>Bold</b> text"}' \
  "${MATRIX_HOMESERVER_URL}/_matrix/client/v3/rooms/ROOM_ID/send/m.room.message/$(date +%s%N)"
```
