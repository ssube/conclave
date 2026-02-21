# Verification Patterns

Existence ≠ Implementation. Four levels of verification:

1. **Exists** — File/post/record is present
2. **Substantive** — Content is real, not placeholder
3. **Wired** — Connected to the rest of the system
4. **Functional** — Actually works when invoked

Levels 1-3 can be checked programmatically. Level 4 often requires human verification.

## Platform Posting

### After posting to any platform:

```bash
# Level 1: Script completed without error
echo $?  # 0 = success

# Level 2: Response contains expected data
# Post ID, URL, or confirmation message in output

# Level 3: Post is accessible
curl -sf "$POST_URL" | head -5  # Returns content, not 404

# Level 4: Post looks correct (human check)
# Image displayed, text formatted, tags applied
```

### Stub detection for posts:
- Script returned 0 but output is empty
- Post URL returns 404 or redirect to login
- Image not attached (text-only when image was intended)
- Wrong account or wrong platform

## Data Ingestion

```bash
# Level 1: Ingest script completed
echo $?

# Level 2: Data changed
sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM metrics WHERE date = date('now')"
# Should return > 0

# Level 3: Values are substantive
sqlite3 "$DB_PATH" "SELECT SUM(value) FROM metrics WHERE date = date('now')"
# Should be > 0, close to previous day

# Level 4: Trends make sense (human judgment)
# Values don't jump 10x overnight, counters didn't go negative
```

## Image Generation

```bash
# Level 1: Output file exists
[ -f "$OUTPUT_PATH" ] && echo "EXISTS"

# Level 2: File is a valid image with reasonable size
file "$OUTPUT_PATH"  # Should say PNG/JPEG
stat -c %s "$OUTPUT_PATH"  # Should be > 50KB for a real image

# Level 3: Image has expected dimensions
identify "$OUTPUT_PATH"  # Width x Height match request

# Level 4: Image looks good (human curation)
```

## Session Refresh

```bash
# Level 1: Refresh script completed
echo $?

# Level 2: Cookie file updated
stat -c %Y "$COOKIE_FILE"  # Modified time is recent

# Level 3: Session actually works
# Try a lightweight authenticated API call
curl -sf --cookie "$COOKIE_FILE" "$PLATFORM_URL/api/me" | head -5

# Level 4: Full posting workflow succeeds
```

## The Verification Gate

Before claiming ANY task complete:

1. IDENTIFY what command proves the claim
2. RUN the command (fresh, not cached)
3. READ the full output
4. VERIFY output confirms the claim
5. ONLY THEN claim completion

**Evidence before assertions, always.**
