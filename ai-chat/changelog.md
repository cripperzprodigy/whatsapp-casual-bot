# Changelog

### Global Search Kill Switch — SEARCH-GATE-001 - 2026-07-02
- **New Config Flag**: Added `SEARCH_ENABLED=True` to `app/config.py` Settings class. Global control for all web search features (DM, Group, Commands).
- **Helper Function**: Created `is_search_enabled()` in `app/utils/search_intent.py`. Replaces scattered gate checks throughout codebase.
- **DM Search Gate**: Added gate check in `router_webhook.py` DM handler before `detect_search_intent()`. Rejects with: `"⚠️ Web search is currently disabled by administration."`.
- **Command Search Gates**: Added gate checks in `commands.py` for both `!s` (agentic) and `!sc` (deep crawl) commands. Early rejection before expensive API calls.
- **Config Sync**: Updated `.env.example` with comprehensive "WEB SEARCH & DEEP CRAWL CONFIGURATION" section. Consolidated `SEARCH_ENABLED`, `LLM_SEARCH_TIMEOUT`, `GROUP_SEARCH_COOLDOWN`, and all related search configs with clear comments and defaults.
- **Documentation**: Updated `ai-chat/knowledge_base/WEB_SEARCH_PROTOCOL.md` with new "Global Search Disable (SEARCH-GATE-001)" section explaining configuration, use cases, and implementation details.
- **Test Coverage**: Created `tests/test_search_gates.py` with 30+ tests covering gate functionality, config loading, `.env.example` synchronization, and documentation updates.
- **Unified Gates**: All three search entry points (DM natural language, Group mentions, Commands) now check the same global flag. Single point of control prevents bypass scenarios.

### Config Cleanup & Documentation Fixes - 2026-07-02
- **Dead Config Variables Removed**: Removed `CRAWL_TOTAL_TIMEOUT`, `CHATTY_SEARCH_TIMEOUT_SECONDS`, and `deep_crawl_timeout_seconds` from `config.py` and `.env.example`.
- **Config Rename**: Renamed the legacy `crawl_timeout_seconds` to `CRAWL_CONNECTION_TIMEOUT` to unify the naming standard across the `config.py` definitions and consuming services (`deep_crawl_service.py`, `agentic_search_service.py`, `commands.py`).
- **Comment Fix**: Corrected a stale doc comment in `search_intent.py` regarding the number of capture groups inside the regex compilation strings.

### Search Fixes - SEARCH-FIX-004 - 2026-07-02
- **Timeout Wiring**: Added `LLM_SEARCH_TIMEOUT` config with default=90s. Wired explicit timeout routing from `config.py` through `router_webhook.py`, `deep_crawl_service.py` to the underlying `ask_llm` OpenAI client, ensuring that complex multi-site deep crawls have adequate time for synthesis without hard aborts.
- **Query Extraction Fix**: Refactored regex patterns in `search_intent.py` to use capture groups `()` isolating the target query instead of including trigger words (e.g. "search the web for X" now extracts just "X"). Updated feedback string to cleanly state `Searching for: X...` without redundancy.
- **Group Search Mentions (GROUP-SEARCH-001)**: Enabled natural language search in group chats exclusively via bot mentions (e.g. `@CasualBot search for X`). Implemented strict rate limiting per group (default 60s cooldown, configurable via `GROUP_SEARCH_COOLDOWN`) and robust query cleaning to discard trigger phrases.

> For historical entries prior to 2026-06-25, see changelog_archive.md


### Natural Language Web Search + Time-Aware Synthesis — ADR-042 (WEB-SEARCH-FIX-001) - 2026-07-02
- **Natural intent detection**: New `app/utils/search_intent.py` with `detect_search_intent()` matching 10+ natural language patterns ("search for X", "look up Y", "google Z", "what are the latest X", "can you find X", etc.). Start-anchored regex prevents false positives ("I looked for my keys" ≠ search).
- **Search-then-reply flow**: `router_webhook.py` DM handler intercepts search intent BEFORE the Chatty LLM call, routes to `DeepCrawlService`, AWAITS result (enforced wait), then sends the synthesised answer. 15-second timeout guard with graceful fallback message.
- **Time-aware synthesis**: `DeepCrawlService._synthesize()` now prepends `[SYSTEM TIME: {UTC}]` to every LLM prompt, enabling correct resolution of "latest", "recent", "yesterday" queries.
- **Tests**: 23 new tests in `tests/test_web_search_flow.py` — all 116 tests pass.

### Config Sync: .env.example & Documentation Audit — CONFIG-FIX-003 - 2026-07-02
- **Added to `.env.example`**: `ENABLE_RAG_INGESTION`, `RAG_TOP_K`, `RAG_DEFAULT_TTL_DAYS`, `MEMORY_IMMEDIATE_BUFFER_SIZE`, `MEMORY_RECENCY_ALPHA`, `CHATTY_SEARCH_DEFAULT`, `ENFORCE_WHITELIST`, `BOT_IDENTITY_CACHE_TTL`.
- **Updated**: `CHATTY_ENABLED_LANGUAGES` changed from `en,id,ms` → `en,id,ms,zh` in both `.env.example` and `app/config.py` (aligns with ADR-039 Chinese support).
- **README.md**: RAG config table expanded from 4 to 8 rows — now includes `MEMORY_IMMEDIATE_BUFFER_SIZE`, `MEMORY_RECENCY_ALPHA`, `CHATTY_SEARCH_DEFAULT`, `CHATTY_ENABLED_LANGUAGES`.
- **Audit result**: All `app/config.py` Settings fields are now present in `.env.example`. Zero undocumented env vars. No `os.getenv()` usage found in codebase — all config goes through Pydantic Settings.

### Chatty Time Awareness & Web Search Integration — ADR-041 - 2026-07-02
- **Always-on time**: `_build_time_context()` injects `[CURRENT TIME]` with `Asia/Singapore` zone (stdlib `zoneinfo`). LLM answers "what day/time is it?" accurately.
- **Auto web search trigger**: `_should_trigger_search()` keyword matcher + `_build_search_tools_section()` injecting `[TOOLS]` when user asks for real-time info. Keywords: "latest", "news", "weather", "stock", "search the web", etc.
- **New config**: `CHATTY_SEARCH_DEFAULT=True` (via `.env`). Per-chat toggle: `!chatty search on|off`.
- **!help updated**: `!chatty search <on|off>` added to admin commands section.

### Language Mirroring Protocol — ADR-039 (LOC-MIRROR-001) - 2026-07-02

**New file: `app/utils/lang_detect.py`**
- `detect_language(text, fallback='en')`: LRU-cached (maxsize=1024), CJK-aware probability detection. Uses `langdetect.detect_langs()` for confidence-level access rather than single-result `detect()`.
- `language_name(code)`: Maps supported codes to human-readable names for LLM prompt injection.
- `build_language_enforcement_block(lang_code)`: Returns a `[CRITICAL LANGUAGE RULE]` system prompt section placed **above** RAG context to prevent English-context drift.
- CJK-aware length guard: each ideograph counts as 3 effective units, preventing short Chinese phrases (e.g. "你好，谢谢") from incorrectly falling back to English.
- `_is_likely_ms_id()`: Merged heuristic using external `data/translation_skip_keywords.txt` **unioned** with built-in `_CORE_MS_ID_WORDS` (covers greetings absent from the curated file). 40% token-ratio threshold.
- False-positive reclassification: Tagalog (tl), Finnish (fi), Somali (so), Swahili (sw) etc. are reclassified to 'ms' when the keyword heuristic confirms Malay/Indonesian content.
- Chinese variant normalisation: zh-cn, zh-tw, zh-hk → 'zh' (unified code for all variants).
- Fallback to 'en' for all unsupported languages (Polish, Japanese, Arabic, Russian, etc.).

**Modified: `app/services/ai_memory_engine.py`**
- Imports `mirror_detect_language`, `build_language_enforcement_block`, `MIRROR_SUPPORTED_LANGS` from `app/utils/lang_detect`.
- `_detect_language()` fully rewritten: fast-path uses `mirror_detect_language()` (LRU-cached, synchronous), DM profile `preferred_language` override honoured, LLM-based detection retained as last resort only.
- `process_message()`: injects `build_language_enforcement_block(lang)` above `[CONTEXT MEMORY]` in system prompt. Added translation instruction for RAG context in different language.
- `generate_delayed_reply()`: same enforcement block injected (delayed-reply path).

**Modified: `app/router_webhook.py`**
- Imports `mirror_detect_language` from `app/utils/lang_detect`.
- `_handle_dm_message()`: logs detected language at `INFO` level for observability: `[LangMirror] DM chat=... detected_lang='...'`.

**New test file: `tests/test_language_mirroring.py`** — 40 tests, all pass.
- English, Indonesian, Malay, Chinese detection accuracy.
- Chinese variant normalisation (zh-cn, zh-tw, zh-hk).
- Short text fallback, CJK-aware effective length.
- Unsupported language fallback (Polish, Japanese, Arabic).
- Code-switching handling.
- LRU cache behaviour.
- `language_name()` mapping.
- `build_language_enforcement_block()` prompt correctness.
- Language enforcement block positioned above RAG context.
- RAG translation instruction present.
- False-positive reclassification metadata.
- Multi-turn language drift prevention.

**Modified: `tests/conftest.py`** — updated langdetect stub strategy to import the real package when installed (required for test_language_mirroring.py). Falls back to minimal stub only when langdetect is not installed.

### Hybrid Context Strategy (Immediate Buffer & Recency Boost) — ADR-040 (RAG-FIX-003) - 2026-07-02
- **Bug**: The Chatty AI engine failed short-term recall ("What did I just say?" / "What is my name?") because it relied 100% on RAG retrieval, which would return semantically similar but stale messages from weeks ago instead of the immediately preceding exchange.
- **Root causes**: (1) No raw short-term message history was injected into the LLM prompt. (2) Vector similarity ignored temporal recency. (3) DM ingestion was fire-and-forget, so the latest message might not be embedded yet.
- **Fix — Immediate Buffer**: Added `_build_immediate_buffer()` to `AIMemoryEngine` — reads the last N messages (configurable: `MEMORY_IMMEDIATE_BUFFER_SIZE`, default 5) from `.jsonl` history and injects them as `<immediate_context>...</immediate_context>` in the system prompt, positioned above `[CONTEXT MEMORY]`. Prompt includes PRIORITY instruction directing the LLM to trust the buffer for recent-event questions.
- **Fix — Recency-Weighted Re-Ranking**: Added `_rerank_by_recency()` — applies time-decay multiplier `final_score = similarity / (1 + alpha * days_since_msg)` with configurable `MEMORY_RECENCY_ALPHA` (default 0.5). Recent messages now outrank stale semantic matches.
- **Fix — Synchronous DM Ingestion**: Changed DM ingestion from `asyncio.create_task()` (fire-and-forget) to `await asyncio.wait_for(..., timeout=2.0)` in `_handle_dm_message()`. Group chats retain fire-and-forget.
- **New config flags**: `MEMORY_IMMEDIATE_BUFFER_SIZE=5`, `MEMORY_RECENCY_ALPHA=0.5` in `.env`.
- **Tests**: 11 new tests in `tests/test_rag_recency.py`. Full suite: 93/93 pass.
- **Related ADR**: ADR-040.
- **Bug**: Traditional Chinese text (e.g., `繁體字測試`) consistently misclassified as Korean (`ko`) by `langdetect` with ~100% confidence. Caused the bot to reply in English instead of Chinese for HK/TW/MY users.
- **Root cause**: Probabilistic n-gram models confuse CJK Unified Ideographs between Chinese and Korean Hanja. Short WhatsApp messages lack sufficient context for statistical disambiguation.
- **Fix**: Added `detect_cjk_heuristics()` in `app/utils/lang_detect.py` — a deterministic O(n) pre-filter using Unicode character-range counts for Hangul (U+AC00–D7AF), Kana (U+3040–30FF), and CJK Ideographs (U+4E00–9FFF, U+3400–4DBF). Priority: Hangul > 5% → `ko`, Kana > 5% → `ja`, CJK > 50% → `zh`. Falls through to `langdetect` when no script dominates. Integrated as step 1.5 in `detect_language()`, BEFORE the keyword heuristic.
- **Tests**: 12 new tests in `TestCJKHeuristics` (52 total, all pass). Covers Traditional/Simplified Chinese, Korean Hangul, Japanese Kana+Kanji, mixed CJK/Latin, English bypass, and full integration pipeline.
- **Documentation**: New KB file `LANGUAGE_DETECTION_STRATEGIES.md` documents Option B (implemented) and Option C / rejected (fasttext dual-model verification) with algorithm details, Unicode ranges, threshold rationale, and full test coverage matrix.
- **Related**: ADR-039 Appendix B, ISSUE-019 (below).
- **Coverage**: Simulated Node.js gateway requests utilizing robust Python mocks for text, image, command, and group interactions.
- **Error Propagation**: Hardened backend error handling validation for 500s, 429s, network timeouts, and JSON failures.
- **CI/CD**: Introduced `.github/workflows/integration-tests.yml` to automatically execute the suite on GitHub Actions.
- **Tests Created**: `test_message_flow.py`, `test_error_propagation.py`, `test_session_consistency.py`, `test_rag_tool_integration.py`.

### Deep Crawl Security Hardening (SECURITY-001 & SECURITY-002) - 2026-07-02
- **Thresholds**: Adjusted Deep Crawl limits to 100MB/200-depth to support modern SPAs while maintaining XXE protection with a 5s timeout.
- **Security**: Hardened the `deep_crawl_service.py` HTML parser against XML External Entity (XXE) and Billion Laughs DoS attacks.
- **Dependency**: Integrated `defusedxml` alongside `lxml` for secured XML parsing wrappers.
- **Constraints**: Imposed strict limits: `resolve_entities=False`, `no_network=True`, a 5MB payload size limit, and rapid parsing timeouts.
- **Tests Created**: Added `tests/test_security_deep_crawl.py` suite comprising over 10 tests confirming explicit blocking of XXE payloads, malicious SVG vectors, and nested entities.

## 2026-07-02 - DEBUG-LEAD Audit Review
Reviewed
Secondary agent branch audit of feature/wabot-v3.1
Validated 8 findings, corrected 3 assessments, identified 4 missing findings
Added
Issues 13-16 for memory leaks, error propagation, migration path, embedding drift
Corrected prioritization framework for next sprint
Fixed
AGENT_REGISTRY.md duplication and timestamp resolution (pending)
changelog.md archival strategy defined (pending)
SOP.md language purism placeholder resolved (pending)

### Isolation Fixes: Snapshot Context, Preference Scoping, Session Durability, Temp Hygiene, Tool Scratchpad, RAG TTL — ADR-036/037/038 (2026-07-02)

**Task 1 — Snapshot Context / Summary Staleness Fix** (`app/services/ai_memory_engine.py`)
- Added `_read_recent_messages_snapshot()` method that captures the exact recent-message window (up to `MAX_CONTEXT_MESSAGES`) at the moment a request begins processing, returning `(messages, snapshot_timestamp)`.
- Modified `_update_summary()` to accept optional `snapshot_messages` and `context_timestamp` parameters. When a snapshot is provided, summary generation uses that exact message window instead of re-reading the file — ensuring summary and RAG retrieval operate on the same temporal slice of history.
- Added `[CONTEXT DRIFT]` warning log when `snapshot_timestamp` vs `context_timestamp` diverge by more than 30 seconds, surfacing race conditions under high concurrency.
- Updated `process_message()` and `generate_delayed_reply()` to call `_read_recent_messages_snapshot()` before RAG retrieval and pass the snapshot to `_update_summary()`.

**Task 2 — Group-Specific User Preferences** (`app/services/profile_service.py`, `scripts/migrate_preferences_scope.py`)
- Added `PERSONA_PREFERENCE_KEYS` and `GLOBAL_PREFERENCE_KEYS` frozensets defining the scoping policy: persona keys (`tone`, `emoji_style`, `persona`, `system_prompt`) are scoped to `(user_id, chat_id)` tuples; global keys (`preferred_language`, `lang_pref`) fall back to user-level global storage.
- Added `_get_scoped_pref_path(user_id, chat_id)` and `_get_global_pref_path(user_id)` path helpers. Storage layout: `./data/prefs/{safe_user_id}/{safe_chat_id}.json` (scoped) and `./data/prefs/{safe_user_id}/global.json` (global).
- Added `read_scoped_preferences(user_id, chat_id)`, `write_scoped_preference(user_id, chat_id, key, value)`, and `get_effective_preference(user_id, chat_id, key, default)` — the full preference scoping API.
- Created `scripts/migrate_preferences_scope.py`: idempotent migration script that copies existing DM `profile.json` data into the new `global.json` format. Supports `--dry-run` and `--chat-id` flags. Run via `python -m scripts.migrate_preferences_scope`.

**Task 3 — Session State Durability & Optimistic Locking** (`app/state.py`)
- Added `SessionState` SQLAlchemy model (`session_state` table) with `chat_id` PK, `current_tool`, `typing_state`, `tool_scratchpad` (JSON), `session_version` (optimistic lock etag), `is_processing`, and `last_active` columns. Auto-created via `Base.metadata.create_all()` — backward compatible with existing DBs.
- Added `get_or_create_session_state(db, chat_id)` helper.
- Added `update_session_state_atomic(db, chat_id, updates, expected_version)`: increments `session_version` on success; returns `False` on version mismatch (concurrent write detected) without raising.
- Added `recover_stale_sessions(db, stale_age_seconds=300)`: resets sessions stuck in `is_processing=True` state whose `last_active` is older than the threshold. Called automatically in `init_db()` on every startup.

**Task 4 — Temp File Hygiene** (`app/utils/file_utils.py`)
- Created `TempFileContext` async context manager. Creates a unique per-request directory at `<tmpdir>/bot_{uuid}/{prefix}/`. `__aexit__` aggressively wipes the entire `bot_{uuid}` root via `shutil.rmtree`, unconditionally (success or exception).
- Created `cleanup_orphaned_temp_dirs(max_age_seconds=3600)` async function for startup hygiene: removes any `/tmp/bot_*` directories older than the threshold.

**Task 5 — Tool Execution Scratchpad Isolation** (`app/services/tool_executor.py`)
- Created `ToolExecutor` class with `log_to_scratchpad()`, `get_scratchpad_prompt()`, `clear_scratchpad()`, and `is_tool_active()` methods.
- Tool logs append to `session_state["tool_scratchpad"]` (never `conversation_history`), keeping the main history clean.
- `get_scratchpad_prompt()` returns a `<tool_scratchpad>` block for LLM injection only when a tool is active; returns `""` otherwise.
- `execute(tool_name)` async context manager: sets `current_tool`, logs TOOL START/DONE, and clears the scratchpad on success. On exception, preserves the scratchpad for retry/debugging and re-raises.

**Task 6 — RAG Temporal Decay** (`app/services/ai_memory_engine.py`, `app/config.py`)
- Added `RAG_DEFAULT_TTL_DAYS: int = 7` to `app/config.py`. Set to `0` to disable TTL filtering. Fully configurable via `.env` — no magic numbers (SOP compliant).
- Added `_is_historical_query(text)` module-level helper: returns `True` for queries containing temporal keywords like "last month", "remember when", "you mentioned", etc.
- Updated `_retrieve_rag_context()`: standard queries add a `{"$and": [chat_id filter, timestamp >= cutoff]}` ChromaDB where clause; historical queries bypass TTL. On filter failure (older ChromaDB versions), automatically falls back to chat_id-only filter.
- Updated `_append_history()` to include `expires_at` (epoch seconds) and `weight` (float) in every ChromaDB document metadata for future re-ranking and purge support.

**Task 7 — Tests** (`tests/test_isolation_fixes.py`)
- 25 new tests across 6 test classes:
  - `TestSnapshotContext`: snapshot capture, summary uses snapshot, snapshot passed to _update_summary, context drift warning.
  - `TestPreferenceScoping`: DM persona not visible in group, global language visible in group, scoped pref overrides global.
  - `TestSessionDurability`: create row, optimistic lock success, conflict detection, stale session recovery, fresh session not reset.
  - `TestTempFileHygiene`: dir deleted on success, dir deleted on exception, no-prefix variant, orphan cleanup, recent dirs preserved.
  - `TestToolScratchpad`: tool log not in history, empty prompt, prompt contains logs, clear, success clears, error preserves, history export clean.
  - `TestRAGTemporalDecay`: TTL filter applied, historical query bypasses TTL, TTL=0 disables filter, metadata includes expires_at, edge cases.

### RAG Context Isolation — Defense-in-Depth Hardening — ADR-035 (2026-07-02)
- **Audit finding**: Per-chat filesystem isolation via separate `ChromaDB.PersistentClient` directories already prevents cross-chat context leakage. No live bug exists.
- **New `_retrieve_rag_context()` method** (`app/services/ai_memory_engine.py`): Extracted and consolidated duplicated RAG retrieval logic from `process_message()` and `generate_delayed_reply()` into a single reusable async method. Eliminates ~40 lines of code duplication.
- **Defense-in-depth `where` clause**: `_retrieve_rag_context()` now filters by `where={"chat_id": self.chat_id}` in ChromaDB queries. This is a no-op in the current per-chat-db architecture but guards against future collection consolidation accidentally breaking isolation.
- **New isolation test suite** (`tests/test_rag_isolation.py`): 6 integration tests proving cross-chat isolation boundaries:
  - Scenario A: Group 1 → Group 2 (same user) → No results
  - Scenario B: Group → DM → No results
  - Scenario C: DM → Same DM → Results found
  - Scenario D: Group → Same Group → Results found
  - Scenario E: Verifies `where` clause is passed to ChromaDB
  - Scenario F: Verifies filesystem path uniqueness across chat types
- **Updated `RAG_MEMORY_ENGINE.md`**: Added Context Isolation Architecture section with dual-layer defense diagram and isolation guarantee matrix.

### Activated RAG Ingestion Pipeline — ADR-030 (2026-07-01)
- **New `ingest_message()` method** (`app/services/ai_memory_engine.py`): Public async entry point for fire-and-forget message ingestion. Writes to `.jsonl` conversation history synchronously (required for `generate_delayed_reply()` continuity), then schedules an async ChromaDB embedding write via `asyncio.create_task()` → `_rag_ingest_async()` → `asyncio.to_thread()`. Context isolation is guaranteed by scoping all writes to `self.chat_id`.
- **New `_rag_ingest_async()` method**: Non-blocking ChromaDB write helper that runs `SentenceTransformer.encode()` and `collection.add()` in Python's thread pool via `asyncio.to_thread()`, preventing the previously synchronous embedding calls from blocking the FastAPI event loop.
- **Async RAG retrieval**: Both `process_message()` and `generate_delayed_reply()` now execute `collection.count()`, `encode()`, and `collection.query()` via `asyncio.to_thread()`. This eliminates the blocking call that previously stalled the event loop during every chatty response.
- **`skip_user_ingestion` parameter on `process_message()`**: When `True`, the method skips the `_append_history("user", ...)` call. This prevents double-ingestion when `ingest_message()` has already written the message (called via `asyncio.create_task()` in the router).
- **`ENABLE_RAG_INGESTION` config flag** (`app/config.py`): Master toggle (default: `True`). When `False`, ChromaDB writes are suppressed across all code paths. `.jsonl` writes are unaffected — conversation history is always preserved for session continuity.
- **`RAG_TOP_K` config** (`app/config.py`): Replaces the hardcoded `min(5, count)` in both retrieval calls. Default: `5`. Configurable via `.env`.
- **Updated CONTEXT MEMORY system prompt**: Both `process_message()` and `generate_delayed_reply()` now use an explicit `[CONTEXT MEMORY]` section with an INSTRUCTION clause ("If the user refers to previous topics, use the information above to answer accurately") replacing the generic `[Long Term Memory (RAG)]` label.
- **router_webhook.py — Active ingestion at all four message entry points**:
  - `_handle_dm_message()`: `asyncio.create_task(engine.ingest_message(text, ..., message_type="dm"))` before `process_message(..., skip_user_ingestion=True)`.
  - `_handle_group_message()` Path A (explicit mention): `asyncio.create_task(engine.ingest_message(..., message_type="group"))` before `process_message(..., skip_user_ingestion=True)`.
  - `_handle_group_message()` Path B (frequency trigger): `asyncio.create_task(engine.ingest_message(...))` replaces the blocking `await engine.process_message(generate_reply=False)`.
  - `_handle_group_message()` Silent Observer: `asyncio.create_task(engine.ingest_message(...))` replaces the blocking `await engine.process_message(generate_reply=False)`.
- **Backfill script** (`scripts/backfill_rag.py`): One-shot script to ingest historical messages from SQLite `message_buffer` into ChromaDB. Run via `python -m scripts.backfill_rag [--limit N] [--chat-id ID] [--dry-run]`. Processes oldest-first, yields after every row to keep the event loop responsive.
- **Unit tests** (`tests/test_rag_ingestion.py`): 7 tests covering `.jsonl` write always happens, ChromaDB suppressed when `ENABLE_RAG_INGESTION=False`, `skip_user_ingestion` prevents double-write, context isolation via separate `vector_db_path` per chat, and `RAG_TOP_K` is respected in `n_results`.
- **ai-chat governance**: ADR-030 added to `decisions.md`. Agent registered in `AGENT_REGISTRY.md`.


### Fixed
- **Search Robustness**: Fixed `!search` to properly log errors with full stack traces (`exc_info=True`) while sending generic fallback messages to end users to not leak infrastructure info.
- **Agentic Search**: Updated `!s` command response when disabled to include instructions for the owner on how to toggle the feature (`!config toggle agentic_search on`).
- **Chatty Quoting Restoration**: Fixed `quoted_msg_id` logic to ensure compliance with ADR-022. Direct mentions and threaded replies now quote the user's message correctly, while unprompted responses gracefully fall back to natural conversation flow (no quote).
- **Reply Context Mapping**: Fixed webhook parser logic dropping threaded conversations by robustly ensuring missing dictionaries are mapped over for string-only formats during WhatsApp native replies.

### Fixed (Group Reply Participant Attribution)
- **End-to-End `quotedParticipant` Fix**: The `quoted_participant` parameter in `send_text_message()` was accepted but silently dropped — never serialized into the HTTP payload to the Node.js gateway. Fixed across three layers:
  1. **Python Gateway** (`whatsapp_gateway.py`): Now includes `quotedParticipant` in the outbound JSON payload when a valid participant JID is provided.
  2. **Node.js Gateway** (`send.js`): Now extracts `quotedParticipant` from the request body and passes it into `sendOptions.quotedParticipant` for `whatsapp-web.js`.
  3. **Router Webhook** (`router_webhook.py`): Chatty group replies (explicit mentions/tags) now pass `msg_key.participant` instead of `None`, ensuring proper sender attribution. DM replies correctly remain `None`.
- **WISP Protocol Schema Update**: Updated `WISP_PROTOCOL.md` to document the new `quotedParticipant` field in the `OutboundMessageRequest` schema.

### Documentation (Group Reply Participant Attribution)
- **Governance Updates**: Completed AI-Chat governance documentation for the `quotedParticipant` fix to prevent regressions and maintain protocol consistency:
  - `CHATTY_FEATURE.md`: Added "Group Chat Requirements" section detailing the necessity of `quotedParticipant`.
  - `SOP.md`: Enforced a mandatory group message attribution rule in Section 4.2.
  - `decisions.md`: Authored ADR-026 formally documenting the architectural decision.
  - `ARCHITECTURE.md`: Added an ASCII flow diagram depicting explicit `quotedParticipant` routing.
  - `README.md`: Updated the summary feature list with links to the Chatty documentation.

### Fixed (Language Detection, Mention Resolution, DM Reply Behavior)
- **Short-Text Language Detection Heuristic (ADR-027)**: `langdetect` was misidentifying short Malay/Indonesian texts (< 20 chars) as Finnish, Tagalog, or English, causing auto-translation to silently skip. Added a keyword-based heuristic (`COMMON_MS_ID_WORDS` set of ~80 words) that bypasses `langdetect` for short texts when ≥ 50% of tokens match. Also added a false-positive guard that overrides `langdetect` results of `fi`/`tl`/`so`/`sw`/`hr`/`ro` when keyword evidence is strong.
- **DM Reply Quoting Removed**: DM chatty replies were incorrectly passing `quoted_msg_id` from the original message, causing WhatsApp to show "Replying to [User]" quote bubbles in DMs. DMs should chat naturally without quoting. Fixed by forcing `quoted_msg_id=None` in `_handle_dm_message()`. Group replies remain unchanged.
- **`!whoami` Multi-JID Registration**: The `!whoami` handler now registers ALL JIDs in the `mentioned_jids` array (not just the first), improving coverage for multi-device environments.
- **LID Registry Auto-Creation**: `BotIdentityManager.load_known_bot_ids()` now creates `data/bot_known_lids.json` with an empty array on first access, ensuring the file always exists after startup.
- **Mention Detection Logging**: Enhanced `is_explicitly_tagged()` with a debug dump of `mentioned_jids` vs `known_ids` for traceability when mention checks fail.
- **Documentation**: Created `ai-chat/knowledge_base/LANGUAGE_DETECTION.md` detailing the hybrid detection algorithm. Added ADR-027, updated SOP, issues, and README.

### Refactored (EN/ID/MS Linguistic Sphere — ADR-028)
- **Linguistic Sphere Policy**: Re-architected auto-translation to treat English, Indonesian, and Malay as a single shared language group. No translation ever occurs between these three languages. Only truly foreign languages (Arabic, Chinese, Japanese, French, etc.) trigger translation.
- **`GLOBAL_IGNORED_LANGUAGES` Default**: Changed from empty string to `"en,id,ms"` — the primary enforcement mechanism. Messages detected as any ignored language return `None` from `detect_language_safe()` immediately.
- **`TRANSLATION_EQUIVALENT_LANGS` Expanded**: Changed from `"id,ms"` to `"en,id,ms"` — ensures all three are treated as mutually equivalent at the equivalence check layer.
- **Keyword Heuristic Early-Exit**: The `_heuristic_ms_id_check()` now triggers an immediate skip (returns `None`) when the detected ms/id is in the ignored set, instead of returning `"ms"` which would proceed to translation.
- **Removed 20-char Limit**: The keyword heuristic now fires on ALL text lengths, not just < 20 chars, providing consistent ms/id detection regardless of message length.
- **Documentation**: Rewrote `LANGUAGE_DETECTION.md` with the sphere policy, updated flow diagram, and edge case table. Added ADR-028. Updated SOP with linguistic sphere rules.
- **Documentation**: Added `SEARXNG_DEPLOYMENT_GUIDE.md` to `knowledge_base/` — a comprehensive Copy-Paste-Deploy guide detailing directory structure, Docker setup, network configuration, and troubleshooting for the Agentic Search SearXNG dependency.

### Added (Deep Crawl Search — `!sc` Command)
- **New Command `!sc <query>`**: Deep research mode that fetches full HTML content from top search results (up to 5 URLs), parses and extracts readable text using BeautifulSoup, aggregates page content, and synthesizes a comprehensive report via the LLM. Goes far beyond snippet-based `!s` for in-depth research queries.
- **Owner Toggle `!sc_toggle on|off`**: Runtime global toggle for the deep crawl feature. Uses `persist_global_config()` for restart-safe state (same pattern as `!globaltrans`).
- **Dual-Layer Configuration**: `DEEP_CRAWL_ENABLED` (`.env` default) + runtime `!sc_toggle` override. Both layers must agree for `!sc` to function.
- **New Service Module**: `app/services/deep_crawl_service.py` — follows Single-Response Contract (always returns `str`, never raises). Uses `asyncio.Semaphore(3)` for bounded concurrency, per-URL timeout, and graceful degradation (falls back to snippet synthesis if all page fetches fail).
- **New Config Variables**: `DEEP_CRAWL_ENABLED` (bool, default: false), `DEEP_CRAWL_MAX_URLS` (int, default: 5), `DEEP_CRAWL_TIMEOUT_SECONDS` (int, default: 10).
- **New Dependency**: `beautifulsoup4` added to `requirements.txt` for HTML parsing (pure Python, no C deps).
- **New LLM Prompt**: `DEEP_CRAWL_SYNTHESIZER_SYSTEM` in `search_prompts.py` — instructs the LLM to produce citation-rich, detailed reports from full page content.
- **Help Menu**: `!sc` shown conditionally when deep crawl is enabled. `!sc_toggle` shown in Owner Commands.

### Hardened (Deep Crawl Search — Security, Stability & Configurable Depth)
- **SSRF Protection**: Added `is_safe_url()` to `deep_crawl_service.py`. Resolves hostnames to IPs and blocks private ranges (10/8, 172.16/12, 192.168/16), loopback (127/8), link-local (169.254/16), multicast, and non-HTTP(S) schemes. All blocked attempts are logged as `SECURITY WARNING`.
- **Dynamic Context Budgeting**: Replaced hardcoded 2000 chars/page with dynamic formula: `15000 // max_urls`. Crawling 5 URLs = 3000 chars each; crawling 20 URLs = 750 chars each. Prevents LLM context overflow.
- **Configurable Crawl Depth**: `DEEP_CRAWL_MAX_URLS` is now validated with `model_validator` clamping (1-20 range), matching the existing `SEARCH_MAX_RESULTS` pattern.
- **Dynamic User Feedback**: ACK message now shows configured URL count and estimated time: "Crawling up to {N} sites... Estimated time: ~{N*timeout}s."
- **`lxml` Parser Upgrade**: Switched BeautifulSoup backend from `html.parser` to `lxml` for ~5x faster HTML parsing. Added `lxml` to `requirements.txt`.
- **`httpx[http2]`**: Upgraded `httpx` to include HTTP/2 support for sites that prefer it.
- **State Persistence**: Toggle state already persists via `data/global_config.json` (established in initial implementation) — verified no additional file needed.


### Added (Hierarchical Auto-Translation Control — ADR-029)
- **External Keyword Dictionary**: Moved hardcoded `COMMON_MS_ID_WORDS` from `translation.py` to `data/translation_skip_keywords.txt`. File supports comments (`#`) and blank lines. 172 keywords loaded at startup with caching.
- **`!globaltrans on|off` Command (Owner-only)**: New command to toggle `GLOBAL_AUTO_TRANSLATE` at runtime. State persists to `data/global_config.json` and survives restarts.
- **Global Config Persistence**: Added `data/global_config.json` mechanism for runtime config overrides. Applied on startup via `_apply_persisted_global_config()`.
- **`.env.example` Alignment**: Fixed `GLOBAL_AUTO_TRANSLATE` default from `True` to `False`, `GLOBAL_IGNORED_LANGUAGES` from `en,id` to `en,id,ms`, `TRANSLATION_EQUIVALENT_LANGS` from `id,ms` to `en,id,ms`. Added `TRANSLATION_SKIP_KEYWORDS_FILE`.
- **Help Menu Restructure**: Translation section now shows all hierarchy commands (`!auto on|off`, `!auto global`, `!target`, `!ignore`). `!globaltrans` added to Owner Commands.
- **Keyword File Loader**: `load_skip_keywords()` in `config.py` reads external file with comment support, returns `frozenset` for O(1) lookup. Cache invalidated on `safe_reload_settings()`.
- **Documentation**: Added ADR-029, updated SOP, LANGUAGE_DETECTION.md, issues.

### Fixed (!whoami LID Registration — Self-Identification)
- **Critical Bug Fix**: `!whoami` had two flaws: (1) `is_owner()` ran before `register_bot_id()`, blocking LID save for non-owners, and (2) it registered ALL `mentioned_jids` blindly without identifying which JID belongs to the bot.
- **Self-Identification**: Since the `.env` phone number (e.g., `6587481374`) has a different numeric base than the WhatsApp LID (e.g., `68728804868116@lid`), we cannot match them directly. Solution: exclude the sender's JID from `mentioned_jids` — whatever remains is the bot's JID. Handles edge case where exclusion removes all JIDs (fallback to full list).
- **Unconditional Persistence**: LID registration happens BEFORE any owner check. This ensures `bot_known_lids.json` is populated even when triggered by non-owners.
- **Owner DM**: Owner receives a DM with full identity details (discovered LIDs, all known LIDs, .env BOT_NUMBER). Non-owners get a group reply confirming internal update.
- **`!forget-me` unchanged**: Remains owner-only since it's destructive.

### Fixed (Duplicate Fallback Messages in `!s` Command)
- **Root Cause**: `execute_iterative_search()` only caught `asyncio.TimeoutError` but not other exceptions (e.g., `TranslationError` from OpenRouter 500). When an uncaught exception propagated to `commands.py`, the caller's `except` block sent an additional error message — producing duplicate messages.
- **Fix**: Added catch-all `except Exception` in `execute_iterative_search()` that guarantees it ALWAYS returns a string, never raises. The caller's `except` block is now a defensive safety net only.
- **Logging**: Added `"Fallback constructed"` and `"Sending single response"` log entries to trace exactly one send per command execution.

### Added (Message Chunking & Sequential Sending)
- **New Module**: `app/utils/message_splitter.py` — Smart text splitting utility with hierarchical boundary detection (paragraphs → sentences → words → hard cut). Each chunk ≤ 2500 chars.
- **`send_long_message()`**: Wrapper around `send_text_message` that auto-chunks long text, adds part headers (`📄 Part 1/3`), and sends sequentially with 1s inter-chunk delay. Short messages (≤ 2500 chars) pass through directly with zero overhead.
- **Integration Points**: `!s` (agentic search), `!search` (results), `!a` (AI ask), DM chatty replies, and group chatty replies now use `send_long_message()`. Short command responses (help, errors, confirmations) remain on `send_text_message` since they're well under the limit.
- **Gateway Timeout Fix**: Increased `httpx.AsyncClient` timeout from default 5s to 15s in `send_text_message()` to prevent `ReadTimeout` on individual chunks.
- **Abort Logic**: If a chunk fails delivery, remaining chunks are aborted and user is notified (`⚠️ Message delivery interrupted at part X/Y`).

### Fixed (!pm Command Silent Drop)
- **Root Cause**: The `!pm` handler had a de-indentation error where the `send_text_message` call was nested inside the `else` branch of the target JID formatter. If a user provided a number without the `@` prefix, the message was never sent.
- **Fix**: De-indented the send block in `commands.py` to function level so that PMs are sent correctly regardless of the `@` prefix logic.

### Fixed (Group Path A `send_long_message` SOP Violation)
- **Root Cause**: Path A (explicit mentions / tags) for group chats was still using `send_text_message` for AI replies, violating the SOP requirement to use chunking for potentially long text, which risks gateway timeouts.
- **Fix**: Replaced `send_text_message` with `send_long_message` for group AI replies in `router_webhook.py`.

### Fixed (Delayed Chatty Reply Missing Quotes)
- **Root Cause**: The `_delayed_chatty_reply` function (Path B) received `msg_id` and `participant` parameters but never passed them to `send_long_message`, resulting in missing message attribution in group chats.
- **Fix**: Updated `_delayed_chatty_reply` to explicitly pass `quoted_msg_id=msg_id` and `quoted_participant=participant` to `send_long_message`, ensuring proper visual quotes for frequency-triggered replies.

### Fixed (Stale Pre-Load Imports in start.sh)
- **Root Cause**: `start.sh` line 370 tried `from app.translation import TranslationService` and line 371 tried `from app.ai_client import AIClient` — both classes were removed during the translation refactoring (function-based `translate_text` replaced `TranslationService`) and AI client refactoring (`ask_llm()` replaced `AIClient`). The try/except swallowed the ImportError, but the modules never actually warmed up.
- **Fix**: Replaced with bare `import app.translation` and `import app.ai_client` which correctly load the modules and their dependencies at startup.
- **Files Modified**: `start.sh`
