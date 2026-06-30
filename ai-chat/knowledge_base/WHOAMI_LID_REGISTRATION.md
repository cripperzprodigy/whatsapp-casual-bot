# Bot Identity & `!whoami` LID Registration

> **ADR-031** | Introduced: 2026-06-30 | Status: Active

## Problem Statement

The bot's phone number in `.env` (e.g., `6587481374`) is **not the same** as its internal WhatsApp LID (e.g., `68728804868116@lid`). These have completely different numeric bases and cannot be matched directly. The bot must **dynamically discover** its own LID at runtime to recognize `@mentions` in group chats.

### The Chicken-and-Egg Problem

```text
.env BOT_NUMBER:    6587481374
WhatsApp LID:       68728804868116@lid
                    ↑ completely different number

Cannot match → bot_known_lids.json stays empty → @mention detection broken
```

The file `data/bot_known_lids.json` stores the bot's known LIDs. Without at least one entry, the bot can never recognize when it's tagged in a group — because it doesn't know its own identity.

### Original Bugs (Two Flaws)

1. **Flaw 1: Owner gate before registration** — `is_owner()` ran BEFORE `register_bot_id()`. If a non-owner sent `@Bot !whoami`, they got "Access Denied" and the LID was never saved. Since the owner might not always be the first to tag the bot, the file stayed empty forever.

2. **Flaw 2: Blind registration of all mentions** — The old code did `for jid in mentioned_jids: register(jid)`. If someone sent `@Bot @OtherUser !whoami`, both JIDs were saved as bot identities — including OtherUser's JID.

## Solution: Self-Identification & Two-Mode Handler

### Key Files

| File | Purpose |
|---|---|
| `app/router_webhook.py` | `!whoami` and `!forget-me` command handlers |
| `app/config.py` | `BotIdentityManager` class — load/save/clear LIDs |
| `data/bot_known_lids.json` | Persistence file (simple JSON array of strings) |
| `app/permissions.py` | `is_owner()` check |

### Self-Identification Strategy

Since we cannot match the `.env` number against LID JIDs (different numeric format), we use **sender exclusion**:

```text
mentioned_jids = ['68728804868116@lid']    ← all mentions in the message
sender_id      = '6512345678@s.whatsapp.net' ← person who sent the message

Step 1: Filter out sender's JID
  bot_jids = [jid for jid in mentioned_jids if jid != sender_id]

Step 2: Whatever remains must be the bot
  bot_jids = ['68728804868116@lid']  ← this is the bot's LID
```

**Edge cases handled:**
- Sender's JID is normalized via `normalize_jid_for_comparison()` before filtering.
- If exclusion removes ALL JIDs (sender tagged themselves), fallback to full `mentioned_jids` list with a warning log.

### Two-Mode Handler

The `!whoami` command operates in two distinct modes depending on whether the bot is already registered:

```text
@Bot !whoami
    │
    ▼
 bot_known_lids.json has entries?
    │
  ┌─YES── Mode A: Status Check ─────────────────────┐
  │  Is sender Owner?                                │
  │  ├─ YES → DM owner with full status details:     │
  │  │         "🤖 Bot Identity Status                │
  │  │          📋 Status: ✅ Registered              │
  │  │          📌 Known LID(s): 68728804868116@lid   │
  │  │          📞 .env BOT_NUMBER: 6587481374"       │
  │  └─ NO  → Silently ignore. No response at all.  │
  └──────────────────────────────────────────────────┘
    │
  ┌─NO─── Mode B: First Registration ───────────────┐
  │  1. Check mentioned_jids not empty               │
  │     └─ Empty → "⚠️ No @mention detected"         │
  │  2. Exclude sender JID → isolate bot's JID       │
  │  3. Save bot JID(s) → bot_known_lids.json        │
  │     (UNCONDITIONAL — before any auth check)       │
  │  4. Is sender Owner?                             │
  │     ├─ YES → DM: "✅ Bot Identity Registered"     │
  │     │         + Group: "✅ Bot identity registered" │
  │     └─ NO  → No response (save happened silently)│
  └──────────────────────────────────────────────────┘
```

### !forget-me (Destructive — Owner Only)

```text
@Bot !forget-me
    │
    ▼
  Is sender Owner?
  ├─ YES → BotIdentityManager.clear_bot_ids()
  │         → "🗑️ Known Bot identities have been cleared."
  └─ NO  → "🚫 Access Denied: !forget-me requires Owner privileges."
```

## BotIdentityManager (app/config.py)

```python
class BotIdentityManager:
    KNOWN_LIDS_FILE = "data/bot_known_lids.json"
    _known_lids_cache: list[str] | None = None

    @classmethod
    def load_known_bot_ids(cls) -> list[str]:
        """Loads and caches LIDs. Creates file if missing."""

    @classmethod
    def register_bot_id(cls, jid: str) -> None:
        """Appends JID if not already present. Uses FileLock for thread safety."""

    @classmethod
    def clear_bot_ids(cls) -> None:
        """Empties the file. Owner-only destructive operation."""

    @classmethod
    def get_bot_number(cls) -> str:
        """Returns the .env BOT_NUMBER (phone number, not LID)."""
```

**Thread safety:** All writes use `FileLock(f"{KNOWN_LIDS_FILE}.lock")` to prevent concurrent corruption.

**Caching:** LIDs are cached in `_known_lids_cache` to avoid repeated file reads. Cache is populated on first load and updated on register/clear.

## Data File Format

`data/bot_known_lids.json`:
```json
[
  "68728804868116@lid"
]
```

Simple JSON array of strings. No schema changes needed.

## How @Mention Detection Uses This

In `router_webhook.py`, the `is_explicitly_tagged()` function checks if any JID in `mentioned_jids` matches a known bot identity:

```python
bot_known_ids = BotIdentityManager.load_known_bot_ids()

# Check if bot is mentioned
for jid in mentioned_jids:
    if jid in bot_known_ids:
        return True  # Bot is tagged!
```

If `bot_known_lids.json` is empty, this check always returns `False`, and the bot never recognizes @mentions. This is why the `!whoami` registration is critical.

## Troubleshooting

### bot_known_lids.json is empty after !whoami
- Check logs for `!whoami: First registration complete` — did the save succeed?
- Check if `mentioned_jids` was populated (logs: `mentioned_jids=[...]`).
- Verify the bot was actually tagged with `@` (not just the word "bot" typed out).
- If running in Docker, ensure `data/` is mounted as a volume so writes persist.

### Bot doesn't recognize @mentions after registration
- Check `data/bot_known_lids.json` has the correct LID.
- The LID format is `<number>@lid` — if it shows `@s.whatsapp.net`, something normalized it incorrectly.
- Try `!forget-me` (owner only) then re-register with `@Bot !whoami`.

### Multiple LIDs registered
- This can happen if the bot's WhatsApp session was re-created (new LID assigned). Both old and new LIDs may exist in the file. This is harmless — the bot checks against all known LIDs.
- To clean up, use `!forget-me` then re-register.

### Non-owner triggered !whoami but nothing happened
- **Mode B (first registration):** The LID WAS saved silently. No response is sent to non-owners. Check the file to confirm.
- **Mode A (already registered):** Non-owners are silently ignored. Only the owner can query status.

### Owner didn't receive DM
- Check that `sender_id` resolves to a valid DM address. The handler appends `@s.whatsapp.net` if the sender ID doesn't already have a JID suffix.
- Check gateway logs for delivery status of the DM.
