# Web Search Protocol (WEB-SEARCH-FIX-001 / ADR-042)

> **ADR Reference:** ADR-042 (2026-07-02)
> **Files:** `app/utils/search_intent.py`, `app/services/deep_crawl_service.py`, `app/router_webhook.py`

---

## Overview

The web search system supports both explicit commands and natural language triggers:

| Input Type | Example | Flow |
|-----------|---------|------|
| Explicit command | `!sc FIFA results` | → `commands.py` → `DeepCrawlService` |
| Explicit command | `!s FIFA results` | → `commands.py` → `AgenticSearchOrchestrator` |
| Natural language | `search for FIFA results` | → `search_intent.py` → `DeepCrawlService` |
| Natural language | `look up the weather` | → `search_intent.py` → `DeepCrawlService` |

---

## Natural Language Intent Patterns

`detect_search_intent(text)` in `app/utils/search_intent.py` matches these patterns:

| Pattern | Example trigger |
|---------|----------------|
| `^search (for)? X` | "search for FIFA results" |
| `^look (up\|for) X` | "look up the news" |
| `^google X` | "google weather Singapore" |
| `^find X` | "find the latest scores" |
| `^what's the latest X` | "what are the latest updates?" |
| `^what are the recent X` | "what are the recent developments?" |
| `^check X` | "check the news" |
| `^can you search (for)? X` | "can you search for Python docs?" |
| `^can you look up X` | "can you look up the time?" |
| `^can you find X` | "can you find recent articles?" |
| `^search the web for X` | "search the web for AI trends" |
| `^look up online X` | "look up online the score" |

*Note: All regex patterns use a specific Capture Group 1 to extract ONLY the targeted query (X) while discarding the trigger prefix words. E.g., "search the web for batam news" extracts strictly "batam news".*

### False Positive Exclusions

These inputs do NOT trigger search:
- `"find my keys"` — possessive "my/your/his/her"
- `"I looked for my phone"` — past tense
- `"I searched for hours"` — past tense
- `"find it"` / `"find out"` — pronoun object

---

## Time-Aware Synthesis (ADR-042)

Every `DeepCrawlService._synthesize()` call now injects:

```
[SYSTEM TIME: 2026-07-02 12:00 UTC]
Interpret 'latest', 'recent', 'yesterday', 'today' relative to this time.
```

This enables the LLM to:
- Understand `"latest news"` = published within the last 24 hours
- Understand `"yesterday's results"` = 2026-07-01
- Avoid hallucinating dates when context mentions "this week"

---

## Enforced Search-Then-Reply Flow

```
DM Message: "look up latest FIFA results"
        │
        ├─► detect_search_intent() → (True, "latest FIFA results")
        │
        ├─► deep_crawl_enabled AND CHATTY_SEARCH_DEFAULT?
        │         YES ↓
        │
        ├─► await asyncio.wait_for(
        │       DeepCrawlService.search_and_crawl("latest FIFA results"),
        │       timeout=settings.LLM_SEARCH_TIMEOUT (90s)
        │   )
        │
        ├─► Search result returned → send_long_message(result)
        │
        └─► return  ← Chatty LLM call is SKIPPED

DM Message: "what's the weather like?" (no intent)
        │
        └─► Falls through to Chatty engine (standard AI reply)
```

---

## Tuning

| Setting | Default | Effect |
|---------|---------|--------|
| `CHATTY_SEARCH_DEFAULT` | `True` | Enable/disable natural language search in Chatty |
| `DEEP_CRAWL_ENABLED` | `True` | Enable/disable deep crawl globally |
| `DEEP_CRAWL_MAX_URLS` | `5` | URLs crawled per query |
| `LLM_SEARCH_TIMEOUT` | `90` | LLM Timeout for Search Synthesis (seconds) |
| `CRAWL_TIMEOUT_SECONDS` | `15` | Per-URL fetch timeout |
| `MAX_TOTAL_CONTEXT_CHARS` | `15000` | Max context sent to LLM |

---

## Global Search Disable (SEARCH-GATE-001)

The `SEARCH_ENABLED` flag provides a "kill switch" to completely disable all web search features across the entire bot:

**Configuration:**
```env
# In .env file
SEARCH_ENABLED=False  # Disables ALL search (DM, Group, Commands)
SEARCH_ENABLED=True   # Enables search (default)
```

**Affected Entry Points:**
When `SEARCH_ENABLED=False`, the bot rejects search requests from:
1. **DM Natural Language**: `"search for X"`, `"look up Y"` → returns `"⚠️ Web search is currently disabled by administration."`
2. **Group Mentions**: `"@Bot search for X"` → returns same message
3. **Explicit Commands**: `!sc <query>`, `!s <query>` → returns same message

**Use Cases:**
- **Temporary Maintenance**: Set to `False` while updating search backend
- **Rate Limiting**: Disable search if API quota exceeded
- **Cost Control**: Set to `False` to prevent expensive API calls during high traffic
- **Security**: Block search if a vulnerability in crawling is discovered

**Implementation Details:**
- Gate check function `is_search_enabled()` in `app/utils/search_intent.py`
- Gate is checked **before** expensive operations (API calls, LLM synthesis)
- Rejection message is friendly and non-technical
- Admins can toggle via `.env` file + restart (or integrate with dynamic config system)

---

## Group Chat Mention-Triggered Search (GROUP-SEARCH-001)

Natural language search is disabled by default in groups to prevent spam on casual conversation (e.g. "let's search for a restaurant"). It can only be triggered via an explicit bot mention.

**Rules:**
1. **Mention Requirement**: The message must contain `@BotName` (case-insensitive).
2. **Query Cleaning**: The mention itself and conversational trigger phrases ("can you", "please") are stripped using `clean_query()` before the query reaches the search engine.
3. **Rate Limiting**: To prevent API abuse, group searches are restricted to one search per `GROUP_SEARCH_COOLDOWN` (default 60s) per group chat. If triggered while on cooldown, the bot replies with a ⏳ warning.

**Examples:**
- ✅ `"@CasualBot search for Batam news"` → Cleans to `"Batam news"`, executes search.
- ✅ `"hey @CasualBot can you look up f1 results"` → Cleans to `"f1 results"`, executes search.
- ❌ `"search for Batam news"` → Ignored (no mention).
- ❌ `"I saw a search result on Google"` → Ignored (no mention, false positive).

---

## Runtime Toggling (ADMIN-TOGGLE-002)

The Owner can independently toggle Agentic Search (`!s`) and Deep Crawl Search (`!sc`) at runtime without restarting the bot. State persists across restarts.

**Hierarchy:**
```
┌─ SEARCH_ENABLED env var (Hard Kill Switch)
│  ├─ False → All search blocked regardless of runtime toggles
│  └─ True → Check runtime state (soft toggles)
│     ├─ agentic_enabled → Controls !s command
│     └─ deep_crawl_enabled → Controls !sc command
```

**Owner Commands:**
```
!admin toggle_agentic   # Flip Agentic Search (!s) on/off
!admin toggle_crawl     # Flip Deep Crawl Search (!sc) on/off
```

**Responses:**
- Success: `✅ Agentic Search is now ENABLED/DISABLED.`
- Unauthorized: `🔒 Access Denied: This command requires Owner privileges.`

**Persistence:**
- Runtime state is stored in `.search_state.json` (git-ignored)
- State file format: `{"agentic_enabled": true, "deep_crawl_enabled": true}`
- On startup, toggles are loaded from `.search_state.json`
- If file is corrupted, defaults to all-enabled

**Dynamic Help:**
The `!help` command dynamically shows current status:
```
• !s (Agentic Search): 🟢 ENABLED / 🔴 DISABLED
• !sc (Deep Crawl): 🟢 ENABLED / 🔴 DISABLED
  └─ Status controlled by owner via !admin toggle_*
```

**Security:**
- Only users in `OWNER_IDS` config (comma-separated) can toggle
- Non-owners attempting to use `!admin toggle_*` receive "Access Denied" and state does NOT change
- Example config: `OWNER_IDS=1234567890@s.whatsapp.net,9876543210@s.whatsapp.net`

**Use Cases:**
- **Resource Management**: Disable Deep Crawl during high server load, keep Agentic Search enabled for quick queries
- **Cost Control**: Disable expensive feature, enable cheaper alternative
- **Testing**: Toggle features on/off without restarting bot
- **Debugging**: Isolate issues by disabling specific search type
