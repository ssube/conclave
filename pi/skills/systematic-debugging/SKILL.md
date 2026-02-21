---
name: systematic-debugging
description: >-
  Systematic 4-phase debugging process for any technical issue. Use when encountering bugs,
  test failures, unexpected behavior, Playwright errors, API failures, ComfyUI issues,
  session expirations, or infrastructure problems. Finds root cause before attempting fixes.
---

# Systematic Debugging

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Iron Law: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

Adapted from obra/superpowers.

## When to Use

Use for ANY technical issue:
- Playwright posting failures (session expired, element not found)
- API errors (rate limits, auth failures, unexpected responses)
- ComfyUI generation failures (model not found, OOM, workflow errors)
- Infrastructure issues (ChromaDB down, SQLite locked, disk full)
- Build/deploy failures (Hugo, Cloudflare)
- Data anomalies (metrics that don't make sense)

**Use ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work

## The Four Phases

Complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

BEFORE attempting ANY fix:

1. **Read error messages carefully**
   - Full stack traces, not just the last line
   - Error codes, HTTP status codes
   - File paths and line numbers
   - Don't skip warnings

2. **Reproduce consistently**
   - Can you trigger it reliably?
   - Same error every time, or intermittent?
   - If intermittent → gather more data, don't guess

3. **Check recent changes**
   - `git log --oneline -10`
   - Were env vars changed? Sessions rotated? APIs updated?
   - Did a platform deploy an update? (Search web if suspected)

4. **Trace the data flow** (for multi-component systems)
   ```
   For EACH component boundary:
     - Log what enters the component
     - Log what exits the component
     - Verify environment/config at each layer
   ```
   Example: Playwright posting → Session cookie → HTTP request → Platform API
   Which layer fails?

### Phase 2: Pattern Analysis

1. **Find working examples** — Same skill worked yesterday? Different platform works?
2. **Compare** — What's different between working and broken state?
3. **Check dependencies** — Platform API changed? Cookie format different? Rate limit hit?
4. **Read the source** — Don't guess what a script does. Read it.

### Phase 3: Hypothesis and Testing

1. **Form single hypothesis** — "I think X causes Y because Z"
2. **Test minimally** — Smallest possible change. ONE variable.
3. **Verify** — Did it work? Yes → Phase 4. No → new hypothesis.
4. **Don't stack fixes** — Multiple fixes at once = can't isolate what worked.

### Phase 4: Implementation

1. **Fix the root cause, not the symptom**
2. **Verify the fix** — Run the actual operation, not just the script
3. **Check for side effects** — Other skills still working?
4. **Document if novel** — Save to ChromaDB notes for future sessions

## Escalation: The 3-Fix Rule

If 3 fixes have failed:

**STOP. Question the architecture.**

Symptoms of an architectural problem:
- Each fix reveals new problems in different places
- Fixes require "massive refactoring"
- Each fix creates new symptoms elsewhere

At this point: escalate to your team lead — don't attempt fix #4 alone.

## Common Failure Patterns

| Symptom | Likely Root Cause | Investigation |
|---------|------------------|---------------|
| Playwright timeout | Session expired | Check cookie file age, try session refresh |
| Playwright element not found | Platform UI changed | Screenshot the page, compare to expected |
| API 401/403 | Token expired or revoked | Check env var, try manual curl |
| API 429 | Rate limited | Check last request time, add backoff |
| ComfyUI connection refused | Server not running | Check container status |
| ComfyUI OOM | Model too large | Check GPU memory, reduce batch size |
| SQLite locked | Concurrent access | Check for running processes |
| ChromaDB timeout | Server overloaded | Check container health |
| Hugo build fail | Template error | Read the actual error, usually line numbers |
| Cloudflare deploy fail | Build output too large | Check output size |

## Red Flags — STOP and Return to Phase 1

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Add multiple changes, run tests"

## Quick Reference

| Phase | Do | Get |
|-------|----|----|
| 1. Root Cause | Read errors, reproduce, check changes, trace flow | Understanding of WHAT and WHY |
| 2. Pattern | Find working examples, compare, read source | Identify differences |
| 3. Hypothesis | Form theory, test minimally | Confirmed or new hypothesis |
| 4. Implementation | Fix root cause, verify, document | Bug resolved |
