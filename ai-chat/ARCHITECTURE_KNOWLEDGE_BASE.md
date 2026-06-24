# WhatsApp Casual Bot — Architecture Knowledge Base

> **Last Updated:** 2026-06-24
> **Branch:** `feature/wabot-v2`
> **Purpose:** Single source of truth for system architecture, data flows, critical decisions, and known issues.

---

## 1. High-Level Architecture

The system uses a **dual-runtime architecture** — a Node.js gateway manages the unstable WhatsApp Web WebSocket connection, while a Python FastAPI backend handles all business logic, AI routing, and database state.

```
┌──────────────────┐     ┌──────────────────────────────┐     ┌──────────────────────────┐
│  WhatsApp App    │     │  Node.js Gateway             │     │  Python FastAPI Backend  │
│  (User's Phone)  │◄───►│  whatsapp-service/           │◄───►│  app/                    │
│                  │     │  ├─ index.js (bootstrap)     │     │  ├─ router_webhook.py    │
│  [Linked Device] │     │  ├─ src/client.js            │     │  ├─ commands.py          │
│                  │     │  ├─ src/events.js            │     │  ├─ ai_client.py         │
│  [QR Auth]       │     │  ├─ src/recovery.js          │     │  ├─ translation.py       │
│                  │     │  ├─ src/queue.js             │     │  ├─ contact_sync.py      │
│                  │     │  ├─ src/state.js             │     │  ├─ permissions.py       │
│                  │     │  ├─ src/utils/jid.js         │     │  └─ whatsapp_gateway.py  │
│                  │     │  ├─ src/utils/session.js     │     │                          │
│                  │     │  └─ src/routes/              │     │  ┌─ SQLite (bot.db)      │
│                  │     │     ├─ qr.js                 │     │  ├─ RAG vector DBs       │
│                  │     │     ├─ status.js             │     │  └─ profile.json per chat│
│                  │     │     ├─ send.js               │     │                          │
│                  │     │     ├─ group.js              │     │  ┌─ ChromaDB (per user)  │
│                  │     │     └─ session.js            │     │                          │
│                  │     └──────────────────────────────┘     └──────────────────────────┘
└──────────────────┘                                          ┌──────────────────────┐
                                                                │  Local / Cloud LLM   │
                                                                │  (LM Studio/OpenAI)  │
                                                                └──────────────────────┘
```

---

## 2. Service Communication — WISP Protocol

The **WhatsApp Inter-Service Protocol (WISP)** governs communication between the Node.js gateway and Python backend.

### Gateway States
| State | Description |
|-------|-------------|
| `CONNECTED` | Normal operation, messages sent immediately |
| `RECOVERING` | Session recovery in progress, messages queued (HTTP 202) |
| `DISCONNECTED` | No active session, requires QR scan (HTTP 503) |

### HTTP Status Codes
| Code | Meaning | Action |
|------|---------|--------|
| 200 | Message sent successfully | None |
| 202 | Queued for recovery | User sees delayed reply |
| 503 | Session corrupt / requires QR | User notified, admin must rescan |

### Key Schemas
```python
# OutboundMessageRequest (Python → Node.js)
class OutboundMessageRequest(BaseModel):
    number: str          # chat_id (JID format)
    textMessage: dict    # {"text": "..."}
    options?: dict       # {"quoted": "..."} for reply quoting

# DeliveryResponse (Node.js → Python)
class DeliveryResponse(BaseModel):
    status: str
    message_id: Optional[str]
    error_code: Optional[str]
    requires_qr: Optional[bool]
    recovery_tier: Optional[int]
```

---

## 3. Message Processing Flow

### 3.1 Inbound Webhook (Full Lifecycle)

```
[Incoming WhatsApp Message]
        │
        ▼
webhook_webhook() [router_webhook.py:476]
        │
        ├── POST /webhook/whatsapp
        ├── Validates WhatsAppWebhookPayload schema
        └── asyncio.create_task(process_message(payload))
            │
            ▼
        process_message() [router_webhook.py:295]
            │
            ├── 1. Create SessionLocal()
            ├── 2. Extract chat_id, sender_id, sender_name
            ├── 3. System Domain Guard Rail (drop @broadcast, @newsletter, @lid)
            ├── 4. Whitelist check (ENFORCE_WHITELIST)
            ├── 5. Get chat_settings from DB
            ├── 6. Group metadata fetch (if new group)
            ├── 7. Contact sync (passive update)
            ├── 8. Self-message check (drop if fromMe)
            ├── 9. Extract text & mentioned_jids
            ├── 10. Add to message buffer
            ├── 11. Handle media (decode base64 → temp file)
            ├── 12. Read user profile (profile.json)
            │
            ├── 13. COMMAND CHECK: text.strip().startswith("!")
            │   ├── YES → handle_command(text, chat_id, sender_id, db)
            │   │              └── return (exits immediately)
            │   └── NO → continue to domain split
            │
            ├── 14. DOMAIN SPLIT
            │   ├── is_dm = not chat_id.endswith("@g.us")
            │   │
            │   ├── IF DM → _handle_dm_message()
            │   │   ├── Always invoke Chatty (no translation)
            │   │   ├── Create AIMemoryEngine
            │   │   ├── Cancel pending tasks
            │   │   ├── engine.process_message(generate_reply=True)
            │   │   └── Send AI reply or fallback message
            │   │
            │   └── IF GROUP → _handle_group_message()
            │       ├── Check explicit mention (@bot, @number, native @)
            │       ├── Check frequency trigger
            │       ├── IF trigger + explicit → Path A (immediate inline reply)
            │       ├── IF trigger + no mention → Path B (delayed background task)
            │       └── IF no trigger → Save to RAG (silent observer)
            │           └── Run auto-translation if enabled
            │
            └── finally:
                ├── Delete temp media file
                └── Close DB session
```

### 3.2 Command Processing Flow

```
handle_command(text, chat_id, sender_id, db) [commands.py:117]
        │
        ├── Parse command: parts = text.strip().split()
        ├── Get chat_settings, user_role, is_group_chat
        │
        ├── IF !help → _build_help_text(role, is_group_chat) → send_text_message()
        ├── IF !auto → Toggle auto-translate (admin only)
        ├── IF !target → Set target language (admin only)
        ├── IF !ignore → Manage ignore list (admin only)
        ├── IF !t → Translate text (public)
        ├── IF !summary → Summarize message buffer (public)
        ├── IF !task → CRUD tasks (public)
        ├── IF !note → CRUD notes (public)
        ├── IF !broadcast → Send to all chats (admin only)
        ├── IF !stats → System stats (admin only)
        ├── IF !export → Export contact ledger (admin only)
        ├── IF !ping → Send "pong"
        ├── IF !owner → Manage owner roles (owner only)
        ├── IF !admin → Manage admin roles (owner only)
        ├── IF !shutdown/!restart → Shutdown bot (owner only)
        ├── IF !claim_ownership → try_claim_ownership(db, sender_id) (DM only, no owner exists)
        ├── IF !search → LLM-based search answer (public)
        ├── IF !pm → Batch PM service (admin/owner only)
        ├── IF !contacts → Contact list/ledger (admin only)
        ├── IF !chatty → Toggle chatty mode (admin in groups, public in DMs)
        ├── IF !chatty_freq → Set frequency (admin only, groups)
        ├── IF !chatty_burst → Set burst count (admin only, groups)
        ├── IF !chatty_delay → Set delay min/max (admin only, groups)
        ├── IF !chatty_mode → Set debounce/throttle (admin only, groups)
        ├── IF !chatty_status → Show chatty status (public)
        ├── IF !lang → Set/reset language preference (DM only)
        ├── IF !a → General AI query (public)
        └── ELSE → "Unknown command" response
```

### 3.3 Chatty RAG Memory Flow (DMs)

```
_handle_dm_message() [router_webhook.py:122]
        │
        ├── Create AIMemoryEngine(chat_id, sender_name, profile)
        ├── Cancel pending_chatty_tasks[chat_id]
        │
        ├── engine.process_message(text, media_path, generate_reply=True)
        │   │
        │   ├── 1. Language detection (langdetect)
        │   ├── 2. Media analysis (PDF extraction / vision)
        │   ├── 3. Vector embedding (ChromaDB)
        │   ├── 4. RAG retrieval (top 5 similar messages)
        │   ├── 5. Prompt construction (profile + memory + RAG)
        │   └── 6. LLM generation (ai_client.ask_llm)
        │
        └── Send reply or fallback message
```

---

## 4. Core Modules

### 4.1 Python Backend (`app/`)

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, startup events, DB init, owner bootstrap |
| `router_webhook.py` | Webhook handler, message processing, DM/group routing |
| `router_system.py` | System endpoints (`/health`, `/`) |
| `commands.py` | All `!` command handlers (1100+ lines) |
| `ai_client.py` | Unified LLM client (local/cloud via AsyncOpenAI) |
| `translation.py` | Auto-translation with 6 fast-path guards |
| `contact_sync.py` | Isolated Ledger pattern for per-group rosters |
| `permissions.py` | Owner/Admin role management, `!claim_ownership` |
| `whatsapp_gateway.py` | HTTP client for Node.js gateway API |
| `config.py` | Pydantic settings (all `.env` variables) |
| `state.py` | SQLAlchemy models, DB session management |

### 4.2 Node.js Gateway (`whatsapp-service/`)

| File | Purpose |
|------|---------|
| `index.js` | Entry point, Express server, QR serving |
| `src/client.js` | Client factory, `initClient()`, lock-heal logic |
| `src/events.js` | `registerEvents()` — qr, ready, auth_failure, message |
| `src/recovery.js` | Tiered recovery (Tier 1/2/3), `isSessionCorruptionError()` |
| `src/queue.js` | `recoveryMessageQueue`, `processMessageQueue()`, `isSettling` |
| `src/state.js` | Shared state (`isConnected`, `qrCodeData`, metrics) |
| `src/utils/jid.js` | `normalizeJid()`, `resolveWhatsAppId()`, `isGroupJid()` |
| `src/utils/session.js` | `validateSessionPath()`, `getSessionState()`, `purgeLock()` |
| `src/routes/qr.js` | GET `/whatsapp/qr` |
| `src/routes/status.js` | GET `/whatsapp/recovery-status` |
| `src/routes/send.js` | POST `/message/sendText` |
| `src/routes/group.js` | GET `/group/findGroupInfos` |
| `src/routes/session.js` | POST `/whatsapp/reset-session` |

### 4.3 Services (`app/services/`)

| File | Purpose |
|------|---------|
| `ai_memory_engine.py` | RAG memory engine (ChromaDB, sentence-transformers) |
| `profile_service.py` | Atomic profile read/write with `filelock` |

---

## 5. Database Schema

### 5.1 Tables (`app/state.py`)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `chat_settings` | `chat_id` | Per-chat config (auto-translate, target lang, ignored langs) |
| `group_contact_ledger` | `chat_id` + `jid` | Isolated Ledger — per-group contact rosters |
| `tasks` | `id` | Task management |
| `notes` | `id` | Note management |
| `message_buffer` | `id` | Rolling window of recent messages (default 200) |
| `global_settings` | `key` | Global config overrides |
| `bot_admins` | `user_id` | Owner/Admin roles |

### 5.2 File-Based State

| Path | Purpose |
|------|---------|
| `./data/contacts/{chat_id}/profile.json` | Per-chat chatty settings, lang pref, summary, counters |
| `./data/contacts/{chat_id}/chat_history.jsonl` | Append-only message log |
| `./data/contacts/{chat_id}/vector_db/chroma.sqlite3` | ChromaDB vector store |
| `./data/contacts/{chat_id}/media/` | Downloaded media files |
| `./data/config.json` | Global dynamic config |
| `.wwebjs_auth/` | WhatsApp session storage (Node.js) |
| `.bot_ready_state` | Deployment state marker |

---

## 6. Key Architectural Decisions

### Decision #7: Strict Message Domain Separation
- **Problem:** Tangled DM/Group logic in `router_webhook.py`
- **Decision:** Split into `_handle_dm_message()` and `_handle_group_message()`
- **Consequence:** Auto-translation disabled for DMs; DMs always invoke Chatty

### Decision #9: WISP Protocol (WhatsApp Inter-Service Protocol)
- **Problem:** Implicit crashes and state desync between services
- **Decision:** Strict Pydantic schemas, 3 gateway states, 202/503 status codes
- **Consequence:** Absolute state visibility, prevents silent crashes

### Decision #10: `getNumberId()` for LID-safe DM Sending
- **Problem:** "No LID for user" errors on DM routing
- **Decision:** Use `client.getNumberId(rawPhone)` to resolve LID before sending
- **Consequence:** Eliminates unnecessary retry loops

### Decision #11: Immediate Cleanup During Refactoring
- **Problem:** Dead code accumulation increases cognitive load
- **Decision:** Remove artifacts immediately during refactoring (no batching)
- **Consequence:** High repository hygiene

### Decision #12: Always Await Async Functions
- **Problem:** `is_owner` referenced as variable instead of awaited
- **Decision:** Always explicitly await async functions
- **Consequence:** Prevents silent failures from coroutine truthy evaluation

### Decision #13: Use `asyncio.create_task()` for Background Work
- **Problem:** `BackgroundTasks.add_task()` does NOT execute async functions
- **Decision:** Use `asyncio.create_task()` directly for fire-and-forget async
- **Consequence:** Prevents entire class of "silent message loss" bugs

---

## 7. Critical Known Issues (All Resolved)

| Issue | Status | Resolution |
|-------|--------|------------|
| Gateway Session Fails to Persist | ✅ Closed | Absolute `SESSION_PATH`, Docker named volume |
| State Marker Disappearing | ✅ Closed | Fixed realpath logic |
| Silent LLM Translation Failure | ✅ Closed | Robust checks for empty choices/content |
| Translation Token Issues | ✅ Closed | Increased to 8192, intelligent retries |
| Silent Failure on Slang Input | ✅ Closed | Strict ISO code whitelist |
| Chatty Feature Failure | ✅ Closed | Empty string match logic fix |
| Chatty Status Crash | ✅ Closed | Variable shadowing fix |
| Chatty Default Bypass | ✅ Closed | Default to `CHATTY_DEFAULT` for DMs |
| Chatty DM/Group failures | ✅ Closed | Robust regex boundaries, implicit DM tagging |
| @bot Mention Immediate Response | ✅ Closed | Dual-path architecture (Path A inline, Path B delayed) |
| Chatty Mention vs Translation | ✅ Closed | `is_explicitly_tagged` guard before translation |
| Chatty-Translation Mutual Exclusion | ✅ Closed | `message_consumed_by_chatty` flag |
| Explicit Mentions Ignored | ✅ Closed | Evaluate mentions before negative status gate |
| Non-Conversational Domain Spam | ✅ Closed | System Domain Guard Rail |
| System Instability Bundle (7 bugs) | ✅ Closed | Race conditions, BOT_NUMBER, fallback messages |
| Monolithic Message Handler | ✅ Closed | Decision #7: Domain separation |
| Missing BOT_NUMBER | ✅ Closed | Required field with startup ValueError |
| DM Chatty Silent Failure | ✅ Closed | User-visible fallback message |
| Embedding Model Event Loop Blocking | ✅ Closed | Eager module-level preload |
| WhatsApp Gateway 500 Error | ✅ Closed | Auto-recovery, detailed logging |
| No LID Session Corruption | ✅ Closed | Tiered recovery (1/2/3) |
| DM commands fail silently | ✅ Closed | WISP protocol, HTTP 202 queuing |
| Zombie Retry Infinite Loop | ✅ Closed | 4.5s settling delay, queue serialization |
| Chrome Zombies Blocking Restart | ✅ Closed | `pkill` in cleanup traps |
| DM Command Silent Failure (is_owner) | ✅ Closed | Proper `await is_owner()` + GroupContactLedger checks |
| **ALL DM Messages Fail Silently** | ✅ Closed | `BackgroundTasks.add_task()` → `asyncio.create_task()` |

---

## 8. Configuration Cascade

### Auto-Translation
```
Chat Setting (per-chat)
  → None? → Global Settings (.env)
    → None? → Disabled
```

### Target Language
```
Chat Setting (per-chat)
  → None? → Global Settings (.env)
    → None? → "en" (default)
```

### Ignored Languages
```
Chat Setting (per-chat)
  → None? → Global Settings (.env)
    → None? → Empty (translate all)
```

### Chatty Status
```
DM: CHATTY_DEFAULT (.env)
Group: CHATTY_GROUP_DEFAULT (.env)
  → profile.json overrides per-chat
```

---

## 9. Deployment Architecture

### start.sh Pipeline
```
check_ready_state()
  → .bot_ready_state exists? → Verify Python binary → Skip to start_services()
  → NO → continue

install_system_deps()
  → apt-get update
  → Install: nodejs, npm, ffmpeg, Puppeteer deps

find_or_install_python()
  → python3.12 available? → Use system
  → NO → Compile from source → $HOME/.local/bin/python3.12

verify_python()
  → command -v python3.12
  → sys.version_info == (3, 12)
  → import sqlite3
  → import venv

create_venv_and_deps()
  → venv/bin/python exists? → Skip
  → pip install -r requirements.txt (if requirements.txt newer than marker)

start_services()
  → Kill zombie chrome/chromium processes
  → npm install (whatsapp-service)
  → Start Node.js gateway (port 3000)
  → Start Python FastAPI (port 8000)
```

### Docker
```yaml
# docker-compose.yml
services:
  python-app:
    volumes:
      - whatsapp_session:/app/.wwebjs_auth  # Named volume for session persistence
  node-gateway:
    volumes:
      - whatsapp_session:/app/.wwebjs_auth

volumes:
  whatsapp_session:
```

---

## 10. Security Model

### Permission Hierarchy
| Role | Commands |
|------|----------|
| **Public** | `!a`, `!search`, `!summary`, `!ping`, `!help`, `!t`, `!chatty on/off`, `!chatty_status`, `!lang set/reset` (DM) |
| **Admin** | All public + `!auto`, `!target`, `!ignore`, `!contacts list`, `!pm group`, `!export ledger`, `!broadcast`, `!stats`, `!chatty_freq/burst/delay/mode` (groups) |
| **Owner** | All admin + `!contacts global`, `!pm global/flood`, `!owner grant/revoke/transfer/list`, `!admin grant/revoke/list`, `!shutdown`, `!restart` |

### Bootstrap Owner
1. Check `BOT_OWNER_ID` env var → auto-create if set
2. Check `!claim_ownership` in DM (only if no owner exists)
3. Persist to `bot_admins` table

---

## 11. Error Handling Patterns

### LLM Token Exhaustion
```python
try:
    response = await ask_llm(prompt)
except TokenExhaustedError:
    max_tokens *= 1.5  # Increase tokens
    retry_count += 1
    if retry_count < 3:
        return await ask_llm(prompt)  # Retry
    raise TranslationError("Translation failed after retries")
```

### Gateway Recovery
```python
# HTTP 202 Queued → Log warning, user sees delayed reply
# HTTP 503 NOT_READY → Abort retry, queue message
# HTTP 503 SESSION_CORRUPT → Trigger Tier 1/2/3 recovery
# HTTP 500 → Retry with exponential backoff (2s, 4s, 8s)
```

### Profile JSON Atomicity
```python
from filelock import FileLock

lock_path = f"{profile_path}.lock"
with FileLock(lock_path):
    profile = read_profile(chat_id)
    profile["chatty_status"] = status
    write_profile(chat_id, profile)
```

---

## 12. RAG Memory Architecture

### Directory Isolation
```
./data/contacts/{chat_id}/
├── profile.json          # chatty_status, lang_pref, summary, counters
├── chat_history.jsonl    # Append-only log
├── vector_db/
│   └── chroma.sqlite3    # ChromaDB persistent store
└── media/
    └── {timestamp}_{filename}  # Downloaded media
```

### RAG Pipeline
```
1. Language detection (langdetect)
2. Media analysis (PDF via pdfplumber / Vision via LLM)
3. Vector embedding (sentence-transformers → ChromaDB)
4. RAG retrieval (top 5 similar messages)
5. Prompt construction (profile + rolling summary + RAG context)
6. LLM generation (ai_client.ask_llm)
7. Rolling summary update (every 5 messages)
```

### Privacy Guarantees
- Vector embeddings generated **locally** (not sent to cloud)
- All user data isolated in `./data/contacts/{id}/`
- No external API calls for vector operations
- Media stored locally, not uploaded

---

## 13. Translation Architecture

### 6 Fast-Path Guards (in order)
```
1. Length check: text < 4 chars → SKIP
2. Emoji density: > 80% non-alphanumeric → SKIP
3. Confidence: langdetect < 0.70 → SKIP
4. Exact match: detected == target → SKIP
5. Equivalence: both in id/ms set → SKIP
6. Ignore list: detected in ignored → SKIP
```

### Semantic Chunking
```
Text > TRANSLATION_CHUNK_SIZE
  → Split by paragraphs
  → Last sentence of chunk N → prefix for chunk N+1
  → Maintains pronoun/tone continuity
```

### Token Exhaustion Retry
```
finish_reason == "length"
  → max_tokens *= 1.5
  → Retry up to 2 times
  → Return MSG_TRANSLATION_ERROR if all fail
```

---

## 14. Gateway Auto-Recovery Strategy

### Tiered Recovery
| Tier | Action | When |
|------|--------|------|
| **Tier 1** | Puppeteer page reload | First attempt, transient errors |
| **Tier 2** | Client reinitialization (preserve `.wwebjs_auth`) | Tier 1 fails |
| **Tier 3** | Nuclear purge (`fs.rmSync` session dir) | Tier 2 fails, prompt QR scan |

### Error Pattern Matching
```javascript
// Session corruption patterns:
"No LID for user" → Non-fatal, fallback to original JID
"session corrupt" → Tier 1 recovery
"invalid session" → Tier 1 recovery
"ExecutionContext" → Tier 1 recovery
"getChat undefined" → Queue message, return 202
```

### Settling Period
```javascript
// Post-recovery cooldown
isSettling = true
setTimeout(() => { isSettling = false }, RECOVERY_SETTLE_TIME_MS) // 4500ms

// During settling: messages return 202 (queued)
// After settling: process recoveryMessageQueue with 500ms debounce
```

---

## 15. JID Normalization

### Node.js Gateway Adapter Pattern
```
Inbound (Node.js → Python):
  @c.us → @s.whatsapp.net
  @lid → @s.whatsapp.net
  @g.us → @g.us (unchanged)

Outbound (Python → Node.js):
  @s.whatsapp.net → @c.us
  @g.us → @g.us (unchanged)
```

### LID Resolution for DMs
```javascript
// GetNumberId resolution (jid.js)
function resolveWhatsAppId(rawPhone) {
    if (rawPhone.includes('@')) return rawPhone; // Already qualified
    const numberId = client.getNumberId(rawPhone);
    if (numberId) return numberId.id; // Return fully-qualified LID
    return rawPhone + '@c.us'; // Fallback
}
```

---

## 16. Rate Limiting

```python
# /webhook/whatsapp: WEBHOOK_RATE_LIMIT (default: 60/min per IP)
# System/health endpoints: exempt
# slowapi Limiter with get_remote_address key function
```

---

*This document should be updated whenever major architectural changes occur. See `ai-chat/PROJECT_HISTORY.md` for detailed change log.*
