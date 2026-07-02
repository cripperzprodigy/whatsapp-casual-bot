# Preference Scoping — Per-(user_id, chat_id) Persona Isolation

> **ADR Reference:** ADR-036 (2026-07-02)
> **Status:** Active
> **Files:** `app/services/profile_service.py`, `scripts/migrate_preferences_scope.py`

---

## Overview

User preferences are divided into two tiers with different isolation guarantees:

| Tier | Keys | Storage | Isolation |
|------|------|---------|-----------|
| **PERSONA** | `tone`, `emoji_style`, `persona`, `system_prompt` | `./data/prefs/{user}/{chat}.json` | Strictly scoped to `(user_id, chat_id)`. A DM persona **never** appears in a group lookup. |
| **GLOBAL** | `preferred_language`, `lang_pref` | `./data/prefs/{user}/global.json` | Per-user global. Visible everywhere unless overridden by a scoped entry. |

---

## Fallback Chain

```
get_effective_preference(user_id, chat_id, key)
        │
        ├─► 1. Read scoped file:  ./data/prefs/{safe_user}/{safe_chat}.json
        │         └─ Found? → return value
        │
        ├─► 2. PERSONA key?
        │         └─ YES → return default  (no cross-chat bleed — stop here)
        │
        └─► 3. GLOBAL key?
                  └─ Read global file: ./data/prefs/{safe_user}/global.json
                        └─ Found? → return value
                        └─ Not found? → return default
```

---

## Storage Layout

```
./data/
└── prefs/
    └── {safe_user_id}/             ← user_id with @ and . replaced by _
        ├── global.json             ← GLOBAL keys (language, etc.)
        ├── {safe_dm_chat_id}.json  ← PERSONA keys for DM context
        └── {safe_group_id}.json    ← PERSONA keys for this specific group
```

`safe_id = jid.replace('@', '_').replace('.', '_')`

---

## API Reference

```python
from app.services.profile_service import (
    read_scoped_preferences,     # Read all scoped prefs for (user, chat)
    write_scoped_preference,     # Write one key for (user, chat)
    get_effective_preference,    # Effective value with fallback chain
    PERSONA_PREFERENCE_KEYS,     # frozenset of persona keys
    GLOBAL_PREFERENCE_KEYS,      # frozenset of global keys
)

# Set tone for user in a specific group (persona — scoped)
write_scoped_preference("user@s.whatsapp.net", "group@g.us", "tone", "formal")

# Set language globally (global key — stored in global.json)
write_scoped_preference("user@s.whatsapp.net", "user@s.whatsapp.net", "preferred_language", "id")

# Lookup — group does NOT see DM tone
tone = get_effective_preference("user@s.whatsapp.net", "group@g.us", "tone", default=None)
# → None  (no persona bleed from DM)

# Lookup — group DOES see global language
lang = get_effective_preference("user@s.whatsapp.net", "group@g.us", "preferred_language")
# → "id"  (falls back to global.json)
```

---

## Migration

Existing `profile.json` data from DM contacts is migrated into the new `global.json` format.

```bash
# Dry-run: preview what would be migrated
python -m scripts.migrate_preferences_scope --dry-run

# Migrate all DM profiles
python -m scripts.migrate_preferences_scope

# Migrate a single chat
python -m scripts.migrate_preferences_scope --chat-id "user@s.whatsapp.net"
```

The script is **idempotent** — safe to run multiple times. Group profiles are skipped (they are group-scoped by default). Existing scoped entries take precedence; old profile.json data does not overwrite already-migrated values.

---

## Persona Leak Prevention — Example

```
User sets tone="casual" in DM  →  ./data/prefs/user_s_whatsapp_net/user_s_whatsapp_net.json
                                   {"tone": "casual"}

User sends message in Group    →  get_effective_preference(user, group, "tone")
                                   Step 1: group scoped file → not found
                                   Step 2: PERSONA key → STOP (return default=None)
                                   Result: None  ✅ no leak
```
