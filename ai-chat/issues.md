# Issues


### ISSUE-017: [RESOLVED] SECURITY-001: XXE and Billion Laughs Vulnerability in Deep Crawl
- **Description**: `deep_crawl_service.py` utilized raw `lxml` parsing via BeautifulSoup without disabling entity expansion, rendering it vulnerable to XXE and DoS (Billion Laughs).
- **File References**: `app/services/deep_crawl_service.py`, `requirements.txt`
- **Priority**: CRITICAL
- **Resolution**: Updated to use `defusedxml` and strictly configured (Follow-up threshold tuning: 100MB max payload, 5s timeout, 200 tree depth limits to resolve false positives on heavy SPAs). `lxml` HTMLParser (`resolve_entities=False`, `no_network=True`, etc.). Extensive security test suite added.
### ISSUE-016: [OPEN] Embedding Model Drift Compatibility
- **Description**: No strategy documented for handling embedding model updates in sentence-transformers. New model versions may produce incompatible vectors, breaking existing RAG retrievals.
- **File References**: app/services/ai_memory_engine.py, requirements.txt
- **Priority**: LOW
- **Related ADR**: ADR-035, ADR-038

### ISSUE-015: [OPEN] Session State Persistence Migration Path undocumented
- **Description**: ADR-037 introduced SQLite session state persistence with optimistic locking. No migration strategy documented for existing users with in-memory sessions. Potential data loss or inconsistency during deployment.
- **File References**: app/state.py, ai-chat/decisions.md (ADR-037)
- **Priority**: MEDIUM
- **Related ADR**: ADR-037

### ISSUE-014: [RESOLVED] Error Propagation Gaps Between Gateway and Backend
- **Resolution**: Implemented comprehensive integration test suite (`tests/integration/gateway_backend/`) verifying 500 errors, timeouts, rate limits (429), and malformed responses. All error propagation paths are now formally covered.
- **Description**: No documented error propagation strategy between TypeScript gateway and Python backend under failure scenarios. If Python backend returns 5xx errors or times out, gateway behavior is undefined.
- **File References**: src/bot/handler.ts, app/main.py
- **Priority**: MEDIUM
- **Related ADR**: None (gap identified)

### ISSUE-013: [OPEN] Memory Leak Risk in RAG Ingestion Pipeline
- **Description**: Fire-and-forget asyncio.create_task() calls in RAG ingestion (ADR-030) lack semaphore or backpressure mechanism. Under sustained high throughput, tasks may accumulate faster than thread pool can process embeddings, causing memory growth and event loop saturation.
- **File References**: app/services/ai_memory_engine.py, router_webhook.py (lines 120-165)
- **Priority**: HIGH
- **Related ADR**: ADR-030

### 12. RAG Temporal Decay — Stale Context Retrieved as Current (Resolved — ADR-038)
- **Issue**: RAG retrieval returned all historical messages with no time-weighting, surfacing stale information (e.g., old plans, outdated preferences) as if current, causing hallucinations.
- **Cause**: `_retrieve_rag_context()` performed semantic search over the entire ChromaDB collection with no timestamp filtering. No TTL mechanism existed.
- **Resolution**: Added `RAG_DEFAULT_TTL_DAYS=7` config flag (configurable via `.env`). Standard queries now filter by `timestamp >= cutoff` in ChromaDB. Historical queries (containing "last month", "remember when", etc.) bypass TTL. `_append_history()` now stores `expires_at` and `weight` metadata on every vector document. Fallback handles older ChromaDB versions gracefully. See ADR-038.

### 11. Tool Execution Logs Pollute Conversation History (Resolved — Task 5)
- **Issue**: Tool execution logs were appended directly to the main conversation history, bloating context windows and reducing LLM response quality.
- **Cause**: No isolated scratchpad mechanism existed for tool execution output.
- **Resolution**: Created `app/services/tool_executor.py` with `ToolExecutor` class. All tool logs route to `session_state["tool_scratchpad"]`. The scratchpad is injected as a `<tool_scratchpad>` block in the LLM system prompt only while a tool is active, and cleared on successful resolution. Main conversation history is never polluted.

### 10. Session State Race Conditions and Loss on Restart (Resolved — ADR-037)
- **Issue**: Critical per-session fields (current_tool, typing_state) were in-memory only, lost on process restart. Concurrent coroutines updating the same chat state could corrupt it silently.
- **Cause**: Session state stored in plain Python dicts with no persistence, no versioning, and no conflict detection.
- **Resolution**: Added `SessionState` SQLAlchemy model to `app/state.py` with optimistic locking via `session_version` counter. `update_session_state_atomic()` returns `False` on version mismatch. `recover_stale_sessions()` resets stuck in-flight sessions on startup. See ADR-037.

### 9. Temporary Files Persist Indefinitely After Request Completion (Resolved — Task 4)
- **Issue**: Audio, image, and PDF temp files created during message processing were never cleaned up, risking disk fill and data leakage.
- **Cause**: No request-scoped cleanup context existed for temporary file management.
- **Resolution**: Created `app/utils/file_utils.py` with `TempFileContext` async context manager. Creates unique per-request directories (`/tmp/bot_{uuid}/`). `__aexit__` uses `shutil.rmtree` unconditionally regardless of success or exception. `cleanup_orphaned_temp_dirs()` removes any `bot_*` dirs older than 1 hour at startup.

### 8. User Preferences Leak Between DM and Group Contexts (Resolved — ADR-036)
- **Issue**: Persona preferences (tone, emoji style) set in a DM could bleed into group chat interactions for the same user, causing formal DM personas to appear in casual group chats.
- **Cause**: Preference storage was not scoped to `(user_id, chat_id)` — a single global file per user allowed cross-context leakage.
- **Resolution**: Implemented a two-tier preference scoping system in `profile_service.py`. PERSONA keys are strictly scoped to `(user_id, chat_id)` — no fallback across contexts. GLOBAL keys (language) use a per-user global fallback. Migration script provided (`scripts/migrate_preferences_scope.py`). See ADR-036.

### 7. RAG Context Isolation Audit (Resolved — No Bug Found)
- **Issue**: Suspected cross-chat context leakage in RAG retrieval — user messages from Group chats potentially appearing in DM queries and vice versa.
- **Cause**: Audit revealed the hypothesis was incorrect. Each `chat_id` already maps to a separate `ChromaDB.PersistentClient` at `./data/contacts/{safe_id}/vector_db/`, providing complete filesystem-level isolation. No `where` clause existed in retrieval queries, but this was inconsequential since each collection is chat-specific.
- **Resolution**: Applied defense-in-depth hardening: extracted duplicated retrieval code into `_retrieve_rag_context()` with an explicit `where={"chat_id": self.chat_id}` filter. Added 6 integration tests in `tests/test_rag_isolation.py` proving isolation across DM↔Group and Group↔Group boundaries. See ADR-035.

### 6. Group AI Language Detection Defaulting to English (Resolved)
- **Issue**: Group chat AI responses always defaulted to English regardless of the user's input language (e.g., Indonesian triggers received English replies).
- **Cause**: `_detect_language()` in `ai_memory_engine.py` had a group-specific early return that bypassed actual language detection, returning the static `default_target_language` setting (defaulting to `'en'`) instead of detecting the incoming message's language.
- **Resolution**: Implemented a 3-tier detection fallback for groups: (1) `langdetect` library on the message text, (2) LLM-based `detect_language()` fallback, (3) group's configured default only as last resort. The system prompt's `Preferred Language` and `Reply ONLY in {lang}` fields now dynamically reflect the detected language.

### 5. `!contacts list` / `!contacts global` / `!contacts export` Architecture Overhaul (Resolved)
- **Issue**: `!contacts global` returned "No contacts found" despite data existing. `!contacts list` showed stale cached data. `!contacts export` overwrote the same file on every run and lacked group name context.
- **Cause**: `!contacts global` read from `data/contacts/*_g_us/profile.json` filesystem paths that were never populated (exports went to `exports/groups/`). `!contacts list` used only the cached `push_name`/`phone_number` from `GroupContactLedger` without live resolution. `!contacts export` used a hardcoded `ledger.csv` filename.
- **Resolution**: All commands now query `GroupContactLedger` DB as canonical data source. `!contacts list` and `!contacts global` perform live WhatsApp network resolution via `resolve_participant_info_batch()` in async background tasks with smart caching (24h TTL). `!contacts global` displays hierarchical output grouped by chat. `!contacts export` uses timestamped filenames and performs an outerjoin with `ChatSettings` for group name enrichment.

### 4. Contact Resolution Stability (Resolved)
- **Issue**: `!resolve` and `!contacts global` commands experienced random crashes and corrupted JSON reads, while active gateway queries failed with 404s.
- **Cause**: Race conditions occurred when aggregating `profile.json` files simultaneously. Gateway queries failed because the `/participant/info` endpoint was missing.
- **Resolution**: Migrated to `GroupContactLedger` database queries (eliminating filesystem race conditions). Implemented `POST /participant/info/batch` endpoint on the Node.js gateway for batched resolution (chunks of 10). Legacy single-contact `/contact/info` route (`whatsapp-service/src/routes/contact.js`) has been deleted. Smart cache (`data/contact_resolution_cache.json`) with 24h TTL prevents redundant gateway calls.

### 3. Agentic Search & Deep Crawl Configuration Sync Mismatch (Resolved)
- **Issue**: The `!s` command reported "Agentic search is disabled" despite `ENABLE_AGENTIC_SEARCH=True` in `.env`.
- **Cause**: The `!s` command and the `!config toggle agentic_search` logic were relying on the SQLite-based `FeatureFlagService.is_enabled` instead of checking the loaded application settings (`app_settings.enable_agentic_search`). This effectively ignored the `.env` settings.
- **Resolution**: Intercepted `"agentic_search"` in the `!config toggle` command to mutate `app_settings.enable_agentic_search` and persist it via `persist_global_config`. Updated `!s` to read directly from `getattr(app_settings, "enable_agentic_search")`. Additionally, `extra="forbid"` was added to Pydantic `Settings` to catch future `.env` typos causing validation errors.

## Legacy Issues
- [CLOSED] MENTION DETECTION FALLBACK: Mention detection in `router_webhook.py` failed when WhatsApp supplied `@lid` identifiers instead of `@s.whatsapp.net` numbers in the `mentioned_jids` array if they didn't numerically match the configured `BOT_NUMBER`. Fixed by implementing a text-based fallback check using a case-insensitive regex pattern (`@BotName` or `@BotNumber`), and explicitly fetching the bot's `pushname` via the Node.js gateway to augment the `BotIdentityManager`.
- [CLOSED] BOT IDENTITY AUTO-SYNC: The dynamic BotIdentityManager correctly identified mismatches between `.env` and the WhatsApp Gateway but left `.env` in a stale state, requiring manual restarts and degraded mode failure risks. Fixed by implementing `AUTO_SYNC_BOT_NUMBER` for file-locked automatic `.env` syncs and hot-reloading configurations, along with a `!botid` diagnostic command.
- [CLOSED] GROUP MENTION SILENT FAILURE: Bot failed to respond to `@mentions` in group chats because the static `BOT_NUMBER` from `.env` was being compared strictly against the runtime `mentionedJids` array (which often contains unhydrated `@lid` identifiers). Fixed by implementing `BotIdentityManager` with dynamic detection via Node.js `/whatsapp/bot-identity` and enhanced `is_explicitly_tagged()` logic that normalizes all formats to bare numeric strings prior to equality checks.
- [CLOSED] DM-LID-PIPELINE: DM commands from `@lid` addresses were failing silently because the router treated them as non-conversational system domains and explicitly dropped them. Fixed by adjusting the domain guard rail to accept `@lid` identifiers for private chats and adding `normalize_chat_id` helper for unified processing.
- [CLOSED] DM ALL MESSAGES FAIL (BackgroundTasks + async mismatch): `background_tasks.add_task(process_message, payload)` in `whatsapp_webhook()` does NOT properly execute async functions. FastAPI's `BackgroundTasks.add_task()` wraps coroutines in a regular callable, so the coroutine is never awaited and silently does nothing. Every DM message — including commands — was dropped without error. Fixed by replacing with `asyncio.create_task(process_message(payload))`.
- [CLOSED] DM-COMMAND-FALLTHROUGH: DM commands (!claim_ownership, !chatty, !lang, etc.) were failing silently and falling through to the AI Chatty engine because the command prefix check was brittle against leading whitespace. Fixed by implementing `text.strip().startswith("!")` in `router_webhook.py` and strictly documenting the early return pattern that prevents fall-through to `_handle_dm_message()`.
- [CLOSED] CLAIM-OWNERSHIP-DM-SILENT-FAIL: Resolved a multi-layer failure cascade where `!claim_ownership` silently failed in DMs. Fixed by persisting `CLAIM_OWNERSHIP_ENABLED` to the DB, adding a 202 QUEUED warning in the gateway, resolving local variable shadowing in `commands.py`, and updating the handler to return explicit success/failure feedback to the user.
- [CLOSED] Gateway Session Fails to Persist: Resolved bug where manual QR scans were required on every restart despite LocalAuth configured. Fixed by making `SESSION_PATH` absolute, updating docker-compose with a named volume, and restricting Tier 3 aggressive session purges.
- [CLOSED] State Marker Disappearing: fixed by fixing realpath logic and introducing cleanup function
- [CLOSED] Silent LLM Translation Failure: fixed by adding robust checks for empty choices/content and detailed logging in ai_client.py
- [CLOSED] Translation Token Issues: Token limit was too low for reasoning models and caused failures. Resolved by increasing limits and implementing intelligent retries on length exhaustions.
- [CLOSED] Translation Silent Failure: Root cause identified as prompt bloat triggering meta-analysis and low token limits causing early stops. Fixed via strict constraint prompting and dynamically scaled max_tokens_override on retries.
- [CLOSED] Silent Failure on Slang Input: !t bg treated as Bulgarian instead of slang. Fixed by implementing strict validation whitelist for language codes.
- [CLOSED] Chatty Feature Failure: Empty String Match logic fixed in config and webhook
- [CLOSED] Chatty Status Crash: Fixed shadowing bug in commands.py where local settings overrode global app.config settings causing AttributeError.
- [CLOSED] Chatty Default Bypass: Fixed router_webhook.py where missing profile entries incorrectly fell back to False instead of respecting CHATTY_DEFAULT for DMs.
- [CLOSED] Chatty DM/Group failures: Replaced greedy substring match with robust regex boundaries and implicit DM tagging.
- [CLOSED] @bot Mention Immediate Response Failure: Explicit @bot mentions in groups were dispatched as fire-and-forget asyncio background tasks (even with delay=0.0), causing race conditions and silent failures. Fixed by implementing a dual-path architecture where Path A (explicit mentions) awaits the LLM reply inline within the same request cycle, while Path B (frequency triggers) continues using the delayed background task system.
- [CLOSED] Chatty Mention vs Auto-Translation Conflict: @bot messages could trigger both a chatty AI response and auto-translation, causing duplicate messages. Three leak paths identified: (1) exception in chatty try/except falling through, (2) non-triggered chatty saving to RAG then falling through, (3) chatty disabled with translation enabled. Fixed by adding an `is_explicitly_tagged` guard before the auto-translation block, and later enhanced by scanning the native WhatsApp `mentionedJid` array to correctly detect UI `@` tags that don't match the regex.
- [CLOSED] Chatty-Translation Mutual Exclusion: Messages evaluated by Chatty are now marked with `message_consumed_by_chatty` so auto-translation is strictly skipped for that same webhook event, even if Chatty decides not to reply.
- [CLOSED] Explicit Mentions Ignored: Bot failed to respond to direct mentions if the group's default chatty status was disabled because the `chatty_status` gate prematurely blocked execution. Fixed by evaluating explicit mentions first and using them to bypass the negative status gate.
- [CLOSED] Non-Conversational Domain Spam: Webhook router classified payloads from `status@broadcast`, `@newsletter`, and `@lid` as Direct Messages because they lacked the `@g.us` group suffix. This caused Chatty and Auto-Translate to instantly trigger and attempt to reply to Status updates and Channels, potentially crashing the gateway or generating spam. Fixed by implementing a strict System Domain Guard Rail at the top of the webhook router to instantly drop these non-conversational domains.
- [CLOSED] System Instability Bundle (7 Bugs): Resolved race conditions in delayed task management, fixed routing crashes on `BOT_NUMBER=None`, added fallback error messaging for unrecognized commands, updated default Docker Gateway URLs, and introduced `ENFORCE_WHITELIST` flag to prevent silent failures on unauthorized chats.
- [CLOSED] Monolithic Message Handler Conflict: DMs and Group chats shared the same conditional tree, leading to translation leaks in DMs, suppression of chatty from group constraints, and complexity in maintenance. Fixed by implementing Decision #7: Strict Message Domain Separation. router_webhook.py was split into `_handle_dm_message` and `_handle_group_message` which exclusively handle their respective logic domains.
- [CLOSED] Missing BOT_NUMBER Silent Failure: Optional BOT_NUMBER could cause app to silently fail to detect mentions. Fixed by changing BOT_NUMBER to a strictly typed, fully validated required field that raises a ValueError on startup if missing.
- [CLOSED] DM Chatty Silent Failure: When the LLM endpoint was unreachable or returned an error, the DM handler silently swallowed the exception and the user received no response at all. Fixed by adding a user-visible fallback message ("⚠️ I received your message but couldn't generate a response right now") and logging the full exception trace.
- [CLOSED] Embedding Model Event Loop Blocking: The SentenceTransformer model was lazily loaded on the first message, causing a synchronous 10-60 second blocking call inside the asyncio event loop. This caused the first DM or Group message to timeout or deadlock the FastAPI background task. Fixed by eagerly preloading the model at module import time during server startup.
- [CLOSED] WhatsApp Gateway 500 Error - Session Corruption: The Node.js WhatsApp-Web.js gateway was returning HTTP 500 errors on all `sendMessage` calls because the WhatsApp client appeared connected but the session was corrupt. Fixed by adding comprehensive logging, connection status metrics, and an auto-recovery process which removes the corrupted session directory and prompts for a QR rescan. Also added validation for incoming JIDs to safely handle `@g.us` vs `@c.us` messages.
- [CLOSED] No LID Session Corruption: Specific session corruption errors like "No LID for user" indicate that Puppeteer's execution context is corrupted or has lost sync with the WhatsApp backend, but does not necessarily mean the `.wwebjs_auth` session files are permanently broken. Previously, this triggered an overly aggressive full session deletion (requiring a manual QR scan). Fixed by implementing Graceful Session Recovery with a 3-tier escalation strategy: Tier 1 reloads Puppeteer, Tier 2 reinitializes the client, and Tier 3 (Nuclear) deletes the session only as a last resort. This drastically reduces downtime and prevents cascading failure loops on transient errors.
- [CLOSED] DM commands (!claim_ownership) fail silently or crash with TypeError: Cannot read properties of undefined (reading 'getChat'). Fixed by implementing WISP protocol (Decision #9). Gateway now pre-flights session validity and queues commands (HTTP 202) instead of crashing, or returns HTTP 503 on unrecoverable session corruption.
- [CLOSED] Gateway Session Fails to Persist: Resolved bug where manual QR scans were required on every restart despite LocalAuth configured. Fixed by making `SESSION_PATH` absolute, updating docker-compose with a named volume, and restricting Tier 3 aggressive session purges. Also added Docker auto-installation and library pre-loading for improved startup stability.
- [CLOSED] Zombie Retry Infinite Loop & Session Race Condition: After Tier 1/2 recovery, the node gateway immediately processed the queue before Puppeteer's internal stores were fully hydrated, triggering continuous `getChat` undefined crashes and infinite loop retries. Fixed by introducing a global `isSettling` 4.5-second cooldown delay post-recovery and explicit queue serialization with a 500ms debounce.
- [CLOSED] Persistent Chrome Zombies Blocking Restart: `kill_process_on_port` left headless Chrome processes alive which maintained file locks on `.wwebjs_auth`. Fixed by adding targeted `pkill -9 -f "chrome.*--user-data-dir"` statements in `start.sh` cleanup traps.


- [CLOSED] GATEWAY DETACHED FRAME CRASH: When sending a DM, a "No LID for user" error incorrectly triggered the `isSessionCorruptionError` check, forcing a tier 1 recovery. The synchronous retry loop then attempted to reuse a detached frame, crashing the process. Fixed by removing "No LID" from `isSessionCorruptionError`, catching `getChatById` failures, and pushing failed messages to `recoveryMessageQueue` with HTTP 202 (Queued).
- [CLOSED] NO LID DM SEND FAILURE: DM routing failed when WhatsApp lacked `@c.us` LID mapping for users only seen in groups. Fixed by implementing `resolveWhatsAppId()` in `src/utils/jid.js` using `client.getNumberId(rawPhone)` to retrieve fully-qualified LIDs for private messages.
- [CLOSED] STALE CODE ARTIFACTS: Refactoring left behind obsolete code. Resolved by sweeping for stale `.bak`, `.old`, `.temp` files, removing dead code comments, and creating a stricter standard for immediate cleanup in `ai-chat/SOP.md`.
- [CLOSED] NO LID / MIGRATION FALLBACK: Catch `getNumberId` returning null on known valid JIDs due to LID account migration, allowing the send to proceed using the original ID.

- Issue: `ModuleNotFoundError: No module named 'duckduckgo_search'` on startup.
  - Resolution: Replaced `ddgs` with `duckduckgo-search` in `requirements.txt`.

- Issue: `!whoami` and explicit tags failing to detect `@bot` mentions if `bot_number` is missing.
  - Resolution: Updated `is_explicitly_tagged` to continue evaluating `@bot` pattern and `bot_name` if `bot_number` is None, and fixed literal bare number search with regex word boundaries `\b`.

- Issue: Bot replies failed to natively quote original messages.
  - Resolution: Updated `resolve_quote_id` to prepend `false_` to `serialized_id` as required by `whatsapp-web.js` WISP schema.
- Issue: `!s` (Agentic Search) returned 3 identical sets of search results back-to-back and timed out on local LLMs.
  - Resolution: Implemented deduplication across iterations using `seen_urls`, prevented the loop from continuing if the refined query was identical, and increased Agentic orchestration timeouts (e.g., synthesis to 60s, global to 120s).
- [CLOSED] !search command returning "No results found" for server errors instead of indicating a failure. Fixed by catching all exceptions with full traceback logging and displaying a generic service error instead.
- [CLOSED] Chatty not quoting @bot messages. Fixed by ensuring `quoted_msg_id` maps to the explicitly triggered original message correctly per ADR-022.
- [CLOSED] Chatty not responding to reply-to-bot contexts. Fixed by updating the message payload parser and `extract_context` logic to reliably handle the mapped data, effectively resolving the missing `quotedMessage` bugs.
- [CLOSED] GROUP REPLY PARTICIPANT ATTRIBUTION: `quoted_participant` parameter was accepted by `send_text_message()` but never serialized into the HTTP payload sent to the Node.js gateway. The Node.js gateway's `sendText` endpoint also lacked extraction and usage of `quotedParticipant` in `sendOptions`. Additionally, Chatty group replies passed `None` instead of `msg_key.participant`. Fixed end-to-end across `whatsapp_gateway.py`, `send.js`, and `router_webhook.py`. WISP protocol schema updated to document the new field.
- [CLOSED] SHORT TEXT LANGUAGE DETECTION (ms/id): `langdetect` misidentified short Malay/Indonesian texts (< 20 chars) as Finnish (`fi`), Tagalog (`tl`), or English (`en`), causing auto-translation to silently skip. Fixed by adding a keyword-based heuristic (`COMMON_MS_ID_WORDS`) that bypasses `langdetect` for short texts and overrides known false positives. See ADR-027.
- [CLOSED] DM CHATTY QUOTE BUBBLES: DM chatty replies incorrectly included `quotedMsgId` in the payload, causing WhatsApp to show unwanted "Replying to [User]" quote bubbles. DMs should chat naturally. Fixed by forcing `quoted_msg_id=None` in `_handle_dm_message()`.
- [CLOSED] LID REGISTRY AUTO-CREATION: `bot_known_lids.json` was never created on first access, causing `load_known_bot_ids()` to always return an empty list and preventing `!whoami` registrations from persisting correctly on fresh deployments. Fixed by writing an empty JSON array on first access. Also improved `!whoami` to register all mentioned JIDs instead of only the first.
- [CLOSED] UNNECESSARY EN/ID/MS TRANSLATION: Auto-translation was triggering between English, Indonesian, and Malay — languages that users in multilingual groups consider mutually intelligible. `GLOBAL_IGNORED_LANGUAGES` defaulted to empty, so no language was ever skipped at the ignore-list layer. `TRANSLATION_EQUIVALENT_LANGS` only covered `id,ms`, not `en`. Fixed by implementing the EN/ID/MS Linguistic Sphere policy (ADR-028): `GLOBAL_IGNORED_LANGUAGES` now defaults to `"en,id,ms"`, the keyword heuristic returns `None` (skip) immediately for ms/id, and `langdetect` results are checked against the ignored set before translation proceeds.
- [CLOSED] HARDCODED TRANSLATION KEYWORDS: Skip keywords were embedded in `translation.py` as `COMMON_MS_ID_WORDS`, preventing easy community expansion. Fixed by externalizing to `data/translation_skip_keywords.txt` with comment support and cached loading. See ADR-029.
- [CLOSED] MISSING GLOBAL TRANSLATION TOGGLE: No Owner-only command existed to enable/disable auto-translation globally at runtime. Fixed by adding `!globaltrans on|off` with persistence to `data/global_config.json`.
- [CLOSED] ENV EXAMPLE MISALIGNMENT: `.env.example` had `GLOBAL_AUTO_TRANSLATE=True` while code defaulted to `False`, and `GLOBAL_IGNORED_LANGUAGES=en,id` while code used `en,id,ms`. Fixed all defaults to match code.
- [CLOSED] WHOAMI LID REGISTRATION BLOCKED BY OWNER CHECK: `!whoami` had two flaws: (1) `is_owner()` ran before `register_bot_id()`, so non-owners got "Access Denied" and the LID was never saved, and (2) it registered ALL `mentioned_jids` blindly without self-identification. Fixed by: excluding sender's JID from `mentioned_jids` to isolate the bot's JID, registering unconditionally before auth check, sending owner a DM with full details, and giving non-owners a group confirmation. This resolves the permanent empty `bot_known_lids.json` that broke all @mention detection.
- [CLOSED] DUPLICATE FALLBACK MESSAGES IN `!s` COMMAND: When OpenRouter API returned 500, `execute_iterative_search()` only caught `asyncio.TimeoutError` — other exceptions (e.g., `TranslationError`) propagated to `commands.py`, where the caller's `except` block sent a second error message. Fixed by adding a catch-all `except Exception` in `execute_iterative_search()` that guarantees it always returns a string, never raises. Added SOP rule: "Single-Response Contract" for service functions.
- [CLOSED] !pm COMMAND SILENT DROP: The `!pm` command handler had a de-indentation error where the `send_text_message` call was nested inside the `else` branch of the target JID formatter. If a user provided a number without the `@` prefix, the message was never sent. Fixed by de-indenting the send block in `commands.py`.
- [CLOSED] GROUP PATH A `send_long_message` SOP VIOLATION: Path A (explicit mentions / tags) for group chats was using `send_text_message` for AI replies, violating the SOP requirement to use chunking for potentially long text. Fixed by replacing `send_text_message` with `send_long_message` in `router_webhook.py`.
- [CLOSED] DELAYED CHATTY REPLY MISSING QUOTES: The `_delayed_chatty_reply` function (Path B) received `msg_id` and `participant` parameters but never passed them to `send_long_message`, resulting in missing message attribution in group chats. Fixed by explicitly passing `quoted_msg_id` and `quoted_participant` to `send_long_message`.
- [CLOSED] STALE PRE-LOAD IMPORTS IN start.sh: `start.sh` attempted `from app.translation import TranslationService` and `from app.ai_client import AIClient` — both classes removed during refactoring. The try/except silently swallowed the ImportError but modules never warmed up. Fixed by replacing with `import app.translation` and `import app.ai_client`.
