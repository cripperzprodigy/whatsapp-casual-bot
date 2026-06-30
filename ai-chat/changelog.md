# Changelog
- **JID Normalization (Reply Context Fix)**: `app/router_webhook.py` now leverages a unified `normalize_jid` utility to safely strip `@c.us` and `@lid` suffixes during comparison. This ensures `ReplyContext=True` correctly triggers when a user quotes the bot's message, enabling contextual threaded responses.
- **Node.js Configurable Memory Cache (Visual Quoting Fix)**: Implemented `.env` driven settings for the internal `whatsapp-service` event listener (`WHATSAPP_CACHE_MAX_SIZE=5000` and `WHATSAPP_CACHE_TTL_SECONDS=300`). Combined with immediate synchronous caching on the `client.on('message')` hook, this entirely prevents the "Resolved quote ID: None" race condition on fast replies, guaranteeing flawless visual quoting.
- **Node.js Gateway Options Validation**: Fixed a bug where `whatsapp-service` was passing an empty/undefined `sendOptions` object to `client.sendMessage`, which triggered `400 Bad Request` downstream when trying to send plain text messages. The `sendMessage` wrapper now strictly omits options if none are required.
- **Node.js Gateway Payload Schema Alignment**: Added a payload adapter inside `/message/sendText` to correctly unpack the Python gateway's `{"to": "...", "message": "...", "quotedMsgId": "..."}` schema into the internal node variables, repairing a silent mismatch.
- **Global Map Cache for Quote IDs**: Upgraded the `whatsapp-web.js` event listener to intercept all incoming messages and cache `shortId -> serializedId` mapping in memory (with a max capacity of 1000 to prevent leaks). This replaces the slow and unreliable `fetchMessages` approach for quote ID resolution, resulting in instant `O(1)` ID translation.
- **Serialized ID Resolution (Quote Fix)**: Added an internal Node.js API endpoint (`/message/resolve-quote-id`) that converts short message keys (e.g. `3EB0...`) extracted by Python into the strictly valid `{chatId}_{messageId}` format expected by `whatsapp-web.js` for quoting. This comprehensively eliminates all `400 Bad Request` errors caused by ID format mismatches during quoted replies.
- **Visual Quoting for Tags**: The bot now aggressively utilizes WhatsApp's native visual quoting mechanism (via `quoted_msg_id`) not only when responding to Threaded Replies, but also when replying to explicit `@mention` Tags, providing better UX in busy groups.
- **Node.js Gateway Validation (400 Bad Request)**: Resolved a critical edge case where `whatsapp_gateway.py` was generating a payload with invalid empty `quotedMsgId` keys, causing the strict Node.js backend to drop perfectly generated LLM texts. Payload bounds and `isinstance` checking have been fully implemented along with debug tracing.
- **LLM Timeout Config**: Added `LLM_TIMEOUT_SECONDS` (default: 180s) to `app/config.py` and `.env.example` to ensure local LLMs with high latency do not trigger premature HTTP read timeouts before WhatsApp can fetch and attach the context.
- **JID Normalizer Helper**: Added a direct `normalize_jid` helper in `extract_context` to safely strip domain suffixes for robust `is_reply_to_bot` detection.
- **Explicit QuotedMsgId Routing**: Completely standardized the `quoted_msg_id` naming convention from the router down to `whatsapp_gateway.py`'s payload generation to ensure Node.js correctly receives the parameter for visual quoting.
- **Empty Context on Tag/Reply**: Resolved an issue where tagging or replying to the bot constructed a context introduction string ("User said:") but failed to actually concatenate the message content. `router_webhook.py` now passes the fully built sentence (e.g., "User @Name tagged you... and said: '{message}'") directly into `process_message`.
- **Auto-Translation Scope Fix**: Resolved a `NameError` crash where `is_explicit_mention` was missing in scope for the auto-translation suppression logic.
- **Native Reply Quoting**: The bot now correctly passes the `quoted_msg_id` back to the WhatsApp Gateway, meaning its responses to threaded conversations will visually quote the user's message in the chat interface.
- **LLM API Response Format Fix**: Fixed an issue in `ai_client.py` where passing `{"type": "json_object"}` caused HTTP 400 errors with strict LLM providers during background summary generation. Switched to `{"type": "text"}`.
- **Decoupled Trigger Logic**: Completely refactored `router_webhook.py` to evaluate explicit tags (`TAG`) and quoted replies (`REPLY`) as independent trigger reasons. This resolves the bug where replies were suppressed if the user forgot to also @tag the bot.
- **Threaded Conversation Trigger Isolation**: Fixed an edge case where a message containing both an explicit `@mention` and a quoted reply caused ambiguous or lost context. `router_webhook.py` now explicitly categorizes triggers as `explicit_tag`, `reply_thread`, or `explicit_tag_and_reply`, ensuring the LLM receives the most descriptive context possible without false overwrites.
- **Threaded Conversation Injection Fix**: Resolved a routing logic error where the webhook router discarded reply context and failed to prioritize threaded conversations. Updated `AIMemoryEngine` to directly inject the context instruction string immediately before the user's message payload in the Chatty engine (`User is replying to your previous message: '{context}' "{message}"`), significantly improving the LLM's multi-turn comprehension.
- **Threaded Conversation Support**: The AI chatty engine is now context-aware when users explicitly reply to its messages. The `router_webhook.py` parses `quotedMessage` contexts from the WhatsApp payload, validates that the quoted sender matches the bot's identity (using `BotIdentityManager`), and seamlessly passes this context to `AIMemoryEngine`. The engine directly injects the parent message into the system prompt, resolving the "isolated event" behavior in busy group chats while preventing malicious spoofing.
- **Owner-Registered Bot Identity (LIDs)**: Implemented a secure, owner-only registration mechanism for dynamic LID learning. Added `!whoami` and `!forget-me` commands. The bot now securely persists learned LIDs to `data/bot_known_lids.json` and checks this file during group mention detection. This solves silent group chat mention failures caused by WhatsApp's multi-device LID protocol without requiring complex background resolution services.
- **Mention Detection Fallback**: Enhanced `@mention` detection logic in `router_webhook.py` to handle scenarios where WhatsApp issues unhydrated `@lid` JIDs or caches stale contacts. The logic now actively fetches the bot's display name (`pushname`) via the Node.js gateway and caches it in the `BotIdentityManager`. If the strict JID array match fails, it falls back to a case-insensitive regex search in the message text looking for `@BotName` or `@BotNumber`, resolving silent group chat mention failures. Added debug logging for mention source attribution.
- **Bot Identity Auto-Sync Mechanism**: Added `BotIdentityManager.sync_bot_number_to_env()` and startup validation hooks to automatically detect mismatches between the `.env` file and the WhatsApp gateway identity. Introduced `AUTO_SYNC_BOT_NUMBER` environment variable to allow atomic, file-locked rewrites of `.env` on mismatch, alongside a `safe_reload_settings()` mechanism to invalidate caches and seamlessly apply new settings. Also added `!botid` command for diagnostic reporting.
- **Recovery Settling Period & Race Condition Fix**: Added a 5-second `RECOVERY_SETTLE_TIME_MS` cooldown post-recovery in `whatsapp-service/index.js`. Incoming message requests during this period receive a 202 Queued response to prevent race conditions where the JavaScript context exists but the internal Puppeteer chat map is empty. Also added robust error boundaries around `client.sendMessage` to catch `getChat` undefined errors, aborting the retry loop immediately and returning a 503 instead of crashing the Node gateway or triggering redundant tier recoveries.
- **Puppeteer Lock File Sanitization**: Fixed persistent "Browser Already Running" error on restart by expanding `start.sh` lock file cleanup to handle `SingletonLock`, `.lock`, and `Crashpad` artifacts. Added a 2-second delay after process killing to allow OS file handle release. Also added proactive lock removal in the `cleanup()` shutdown handler to prevent stale locks from forming in the first place.
- **WISP Protocol Implementation**: Implemented the WhatsApp Inter-Service Protocol (Decision #9) between the Node.js Gateway and Python Backend. Added strict Pydantic schemas, state visibility (CONNECTED, RECOVERING, DISCONNECTED), and robust handling of `SESSION_CORRUPT` via 202 Queued and 503 HTTP status codes. Resolved the `getChat undefined` crash with a `validateSession()` pre-flight check.
- **Dynamic Bot Identity Detection**: Added runtime detection of the bot's own WhatsApp number via a new `GET /whatsapp/bot-identity` endpoint on the Node.js gateway and a TTL-cached `BotIdentityManager` in Python. Replaced all fragile static `BOT_NUMBER` references with this dynamic detection to fix a silent failure where the bot would not respond to group `@mentions` due to JID mismatches between `.env` and WhatsApp's internal multi-device identifiers (LIDs). Also enhanced `is_explicitly_tagged()` to normalize all JID formats (`@c.us`, `@lid`, `@s.whatsapp.net`) prior to equality checks.
- **DM LID Pipeline Fix**: Fixed a bug where DM commands from users appearing as Multi-Device LIDs (`@lid`) were explicitly dropped by the webhook router as non-conversational system domains. Added logic to correctly accept `@lid` suffixes for private chats and implemented a `normalize_chat_id` helper, restoring command access for unhydrated multi-device accounts.
- **DM Command Fallthrough Fix**: Fixed a silent failure bug where DM commands (e.g., `!claim_ownership`, `!chatty`) with leading whitespace were bypassing the command router and falling through to the AI Chatty engine. Implemented robust prefix matching (`text.strip().startswith("!")`) and strictly documented the early return pattern in `router_webhook.py` that prevents domain fall-through.
- **Graceful Session Recovery Implementation**: Overhauled the Node.js WhatsApp gateway recovery strategy to use a tiered approach (Tier 1: Puppeteer Restart, Tier 2: Client Reinitialization, Tier 3: Session Deletion) to gracefully handle "No LID for user" errors and other transient corruption states without unnecessarily requiring manual QR rescans. Also added an exponential backoff retry mechanism inside the Python gateway to handle `requires_qr: false` responses.
- **Enhanced WhatsApp Gateway Auto-Recovery**: Upgraded the Node.js WhatsApp gateway `/message/sendText` endpoint to detect session corruption errors (e.g., "No LID for user") and trigger immediate session purge and auto-recovery, bypassing the standard 3-failure threshold. This guarantees self-healing and prevents persistent 500 errors when the internal IndexedDB cache loses sync with WhatsApp's servers.
- **Loosened Whitelist Guardrails**: Adjusted `ENFORCE_WHITELIST` logic to be more permissive in development environments (`LOG_LEVEL="DEBUG"` or `ENV="development"`), gracefully logging rather than hard-dropping messages, simplifying developer testing.
- **Linked Device (@lid) JID Normalization**: Extended the Node.js gateway's JID normalization to handle `@lid` suffixes (linked device messages) in addition to `@c.us` suffixes. Legitimate messages from secondary devices connected to the primary WhatsApp account are now normalized to `@s.whatsapp.net`, preventing them from being incorrectly blocked by the Python system domain guard rail. Ensures mention detection works correctly for `@` tags from linked devices by normalizing the `mentionedJid` array.
- Refactor: Implemented Strict Message Domain Separation (Decision #7). Split router logic into `_handle_dm_message` and `_handle_group_message`. Enforced strict `BOT_NUMBER` validation on startup.
- start.sh: added cleanup trap to safely preserve .bot_ready_state on SIGINT
- app/ai_client.py: Enhanced LLM parsing robustness to log raw local model responses on empty content/missing choices.
- **Translation Token Fix**: Increased default token limit to 8192 for high context models, implemented automatic retry mechanism for token exhaustion, and created structured LLM responses for precise finish reason detection.
- **Translation Optimizations**: Reverted LLMResponse to strict custom exceptions (TokenExhaustedError, TranslationError), unified !t commands into a single resolution pipeline, and enforced a highly strict translation prompt to prevent reasoning loops.
- **Translation Parsing**: Refactored command parsing to explicitly whitelist target language codes. Slang words of length 2 no longer incorrectly hijack the target_lang parameter.
- **Dynamic Constraints**: Externalized hardcoded token limits, character truncations, and conversation history slicers to environment variables (MAX_CONTEXT_MESSAGES, MAX_INPUT_LENGTH_CHARS) to fully support high-context models.
- Implemented context-aware chunked translation for extremely long messages to prevent data loss or silent failures when hitting token limits.
- Fixed router_webhook.py Chatty trigger logic where an empty BOT_NUMBER caused all messages to be treated as mentions.
- **Chatty Debounce & Throttle**: Introduced human-like random delays before the bot replies in Chatty mode. Replaced immediate execution with asyncio tasks that can be debounced (reset timer on new message) or throttled (strict wait).
- **Chatty Config Overhaul**: Fully externalized frequency, burst, delay limits, and delay modes to .env. Added commands '!chatty_delay' and '!chatty_mode' for granular per-chat control.
- Fixed bug where !chatty_status crashed due to shadowing of global settings by local ChatSettings models.
- Fixed bug where Chatty webhook trigger incorrectly defaulted to False instead of respecting the global CHATTY_DEFAULT setting for DMs.
- Fixed Chatty trigger: enabled implicit DM mentions, normalized group tags, prevented partial number false positives.
- **Chatty Dual-Path Architecture**: Fixed @bot mention not replying immediately. Explicit mentions now bypass the background task system entirely — the LLM reply is generated and sent inline within the same HTTP request cycle (Path A). Frequency-based triggers continue using the delayed background task system (Path B).
- **Translation Suppression on Mention**: Added guard rail before auto-translation to skip translating messages explicitly directed at the bot (@bot or @number). Prevents duplicate responses when chatty and translation both fire, and avoids translating direct bot commands.
- **Chatty-Translation Mutual Exclusion**: Introduced a `message_consumed_by_chatty` flow-control flag in `router_webhook.py` so any message evaluated by Chatty is excluded from auto-translation, even if Chatty decides not to reply.
- **Native Mention Detection**: Upgraded explicit tag detection to extract and check WhatsApp's native `mentionedJid` array from incoming webhooks. Ensures that when users tag the bot via the `@` UI, it accurately triggers the Chatty immediate reply path and correctly suppresses auto-translation, even if the text regex doesn't match the bot's raw phone number.
- **Explicit Mention Override**: Fixed a bug where the bot ignored explicit mentions if `CHATTY_GROUP_DEFAULT` was false. Explicit mentions now take strict precedence and immediately trigger Path A (Immediate Reply), overriding negative default chatty settings without incrementing normal chatter frequency counters.
- **Gateway Session Corruption Detection**: Narrowed `isSessionCorruptionError` matching to strictly catch specific Puppeteer crashes, preventing over-broad matching that was triggering false-positive recovery loops.
- **Tier 1 Recovery Overhaul**: Replaced aggressive `page.reload()` in Tier 1 recovery with a non-destructive 5-second soft wait, avoiding transient Puppeteer instability caused by rapid reloads.
- **Queue Synchronization**: Refactored `processMessageQueue` to use a snapshot drain (`splice`) instead of iterating over the live array, preventing mid-loop mutations and array bounds errors during rapid asynchronous requeuing.
- **Robust Mention Detection**: Overhauled `is_explicitly_tagged` and `is_bot_mentioned` in `router_webhook.py` to fix truncated regex matching and ensure groups correctly enforce explicit mentions before triggering AI responses.
- **Webhook Media Memory Safety**: Added strict `try...finally` resource management in `router_webhook.py` using Python's `tempfile` module to ensure temporary decoded media files are guaranteed to be unlinked after processing, preventing disk bloat.
- **Fix: WhatsApp LID Migration Fallback in jid.js**: Added graceful degradation for `client.getNumberId()` null responses caused by WhatsApp's LID migration. Valid JIDs derived from incoming webhooks now fallback to the original JID instead of throwing `NUMBER_NOT_ON_WHATSAPP` errors, ensuring users with newer LID accounts can still receive bot replies and complete the `!claim_ownership` flow. (Note: The `try...catch` block was further tightened to isolate only the `getNumberId` call to ensure fallbacks trigger correctly if the API throws an explicit error).
- **Persistent Ownership Claim Verification**: Refactored `CLAIM_OWNERSHIP_ENABLED` in `permissions.py` from a runtime-only global to a persistent database-backed check. It now dynamically counts active owners and ensures environments with `BOT_OWNER_ID` do not accidentally leak the claim flow upon restart.
- **Gateway QUEUED Response Traceability**: Added a specific `logger.warning` to `send_text_message` in `whatsapp_gateway.py` when it encounters an HTTP 202 status. This explicitly informs administrators that a command response (like for `!claim_ownership`) has been queued for recovery and may not reach the user immediately.
- **Variable Shadowing Resolution in Commands**: Renamed the local `settings` variable to `chat_settings` within `handle_command` in `commands.py` to prevent unintentional shadowing of the module-level `app_settings` and guarantee safe lookup properties.
- **Enhanced Claim Ownership Feedback**: Updated the `!claim_ownership` handler in `commands.py` to return the new explicitly detailed and celebratory success response along with tighter edge-case denials, and refactored the `!help` menu logic to properly use the new DB-backed `is_claim_ownership_available` function.
- **Node.js JID Normalization Adapter**: Refactored the `whatsapp-service/index.js` gateway to automatically translate `whatsapp-web.js`'s unofficial `@c.us` JID suffixes to the official `@s.whatsapp.net` suffix on inbound payloads, and translate them back on outbound requests. This fully isolates domain suffix fragility, natively restoring broken group admin "Active Sweep" detection and private messaging commands without requiring Python logic modifications.
- **Non-Conversational Domain Guard Rail**: Added a strict system domain guard rail to the top of the webhook router. This prevents WhatsApp Status updates (`@broadcast`), Channels (`@newsletter`), and internal device syncs (`@lid`) from being misclassified as Direct Messages and incorrectly triggering AI Chatty responses or Auto-Translations.
- **System Stability & Configuration Refactors**: Merged `fix-7-critical-bugs` hotfix which resolved root mention parsing fallbacks, prevented task execution race conditions, improved translation density guard rails, safely handled missing `BOT_NUMBER` configs, and introduced the `ENFORCE_WHITELIST` toggle.
- **Comprehensive Routing Debug Logs**: Added `logger.info` trace points at every critical routing decision: Domain Split (DM vs Group), DM handler entry/exit with LLM status, Group handler mention detection with `mentioned_jids` array dump, trigger evaluation, and auto-translation skip/proceed decisions.
- **DM Silent Failure Fix**: DM handler now sends a user-visible fallback message ("⚠️ I received your message but couldn't generate a response") when the LLM returns None or throws an exception, instead of silently swallowing the failure.
- **Embedding Model Startup Preload**: Moved SentenceTransformer model loading from lazy first-message initialization to eager module-level preload. Prevents a 10-60 second synchronous blocking call from deadlocking the asyncio event loop on the first incoming message.
- **WhatsApp Gateway Fixes**: Added detailed error logging, metrics, auto-recovery for corrupted sessions, payload validation with JID checks (`@c.us` and `@g.us`), timeout wrapped send messages, and created a script `test-whatsapp-gateway.sh` to monitor gateway connectivity.
- **Session Persistence**: Converted WhatsApp session path from relative to absolute using `path.resolve(__dirname, '.wwebjs_auth')`, preventing session "loss" after restarts when working directory changes.
- **Docker Installation**: Added automatic Docker Engine installation to `start.sh` with preflight checks, daemon verification, and user group configuration.
- **Startup Stability**: Implemented aggressive library pre-loading sequence for Python (semantic models, FastAPI, httpx) and Node.js (whatsapp-web.js) to prevent race conditions during initialization.
- **Session Validation**: Added `validateSessionPath()` function to distinguish between "no session", "empty session", and "valid session" states with appropriate logging.
- **Recovery and Persistence Optimizations**: Fixed rate limit check timing in whatsapp-service/index.js, improved docker setup feedback and added pre-load summary in start.sh, and added test case for Docker volume persistence.
- **Process Lifecycle Improvements**: Enhanced start.sh to aggressively handle orphaned processes using port checking, safely sanitize Puppeteer locks before startup, and gracefully handle signals for clean termination.
- **Gateway Session Persistence Fix**: Resolved an issue where sessions failed to persist across service restarts by standardizing the `SESSION_PATH` as an absolute path in `whatsapp-service/index.js`. Improved Tier 3 recovery logic to wait 30 seconds before deletion and strictly track an hourly deletion limit to prevent cascading failures. Additionally, integrated a named Docker volume (`whatsapp_session`) to guarantee state retention across container recreations.
- **Codebase Hygiene & Cleanup**: Conducted a thorough codebase sweep to remove stale backup files and dead code. Cleaned up `whatsapp-service/src/recovery.js` by stripping out obsolete "No LID" error check comments, deduplicated entries in `ai-chat/changelog.md`, and added strict rules to `ai-chat/SOP.md` mandating immediate deletion of dead code and artifacts upon refactoring. Verified Node.js syntax and Python test suite execution post-cleanup.
- **CRITICAL Fix: ALL DM Messages Fail Silently (BackgroundTasks + async mismatch)**: `background_tasks.add_task(process_message, payload)` in `whatsapp_webhook()` does NOT properly execute async functions. FastAPI's `BackgroundTasks.add_task()` wraps coroutines in a regular callable, so the coroutine is never awaited and silently does nothing. Every DM message — including commands — was dropped without error. Fixed by replacing with `asyncio.create_task(process_message(payload))`.
- **Fix: WhatsApp LID Migration Fallback in jid.js**: Updated `resolveWhatsAppId` to gracefully fallback to the original JID if `getNumberId()` returns null for input strings that already contain an '@' sign. This fixes the issue where valid users with migrated LID accounts were falsely rejected as "NUMBER_NOT_ON_WHATSAPP".
- **Fix: DM Command Silent Failure (Undefined Variable Scope)**: `!chatty_delay` and `!chatty_mode` referenced `is_owner` as a variable instead of awaiting the async function, and `is_group_admin` was undefined in scope. Added proper group admin checks with `GroupContactLedger` queries and fixed `is_owner` to `await is_owner(db, sender_id)`.

### Fixed Visual Quoting and Reply Detection in Group Chats
- **Issue**: The bot failed to visually quote messages when addressed via a reply, and failed to recognize when a user directly replied to it in group chats due to suffix mismatch.
- **Resolution**:
  1. Extracted and fixed JSON parsing of the quote ID in `app/whatsapp_gateway.py` within a new `resolve_quote_id` method. The script correctly parses `{ "success": true, "serializedId": "..." }` and prepends `_INCOMING_MSG_PREFIX` (`"false_"`) before sending to `whatsapp-web.js`.
  2. Updated `normalize_jid_for_comparison` in `app/router_webhook.py` to robustly strip all potential suffixes by splitting at `@` and handling linked devices (e.g., `@lid`, `@c.us`, `@g.us_...`), correctly returning the pure numeric identifier for accurate comparison.
- **Files Modified**: `app/whatsapp_gateway.py`, `app/router_webhook.py`

### Fixed Quoted Message Extraction in Webhook Payload
- **Issue**: The Python backend was failing to detect a user's reply (`ReplyContext=False`) because the Node.js gateway was not forwarding quoted message context in the webhook payload.
- **Resolution**:
  - Updated `whatsapp-service/src/events.js` to correctly detect `msg.hasQuotedMsg`.
  - Added logic to fetch `getQuotedMessage()` and append `quotedMessage` and `participant` info dynamically to the `contextInfo` inside the outgoing webhook payload, restoring Python's ability to trigger `ReplyContext=True`.

### Implemented Hybrid Search Service
- **Issue**: The `!search` command lacked live web access to retrieve relevant up-to-date data.
- **Resolution**: Implemented a robust `HybridSearchService` supporting:
  - Primary Provider: SearXNG.
  - Fallback Provider: DuckDuckGo (using `ddgs` library).
  - Offloaded DuckDuckGo to an async thread using `asyncio.to_thread` to maintain non-blocking I/O in the main event loop.

- Fixed WhatsApp native visual quoting bug by prefixing `false_` to the resolved gateway `serialized_id` in `whatsapp_gateway.py`.
- Fixed Agentic Search (`!s`) returning duplicate identical search results by implementing `seen_urls` deduplication and breaking the iteration loop if the gap analysis proposes the exact same query.
- Increased Agentic Search timeouts significantly (14s -> 120s global) to support slower local LLMs like LM Studio on laptops.

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

### Fixed
- **Fix**: Contact resolution stability & permissions. Addressed async mismatches, added missing `/participant/info` gateway endpoint, introduced `FileLock` for profile reads to fix race conditions, and corrected `!sc` permission inversion.
- **Optimization**: Caching & Batching for Contacts. Added `data/contact_resolution_cache.json` with 24h TTL to skip redundant gateway hits. Implemented `POST /participant/info/batch` in Node.js gateway to process JIDs in batches of 10. `!resolve global` now executes in the background and sends a DM upon completion. Enhanced privacy formatting UX to guide users.

- **Feature**: Active Contact Resolution & `!resolve` command. Owners can now use `!resolve @mention` or `!resolve global` to actively query the gateway and bypass local cache privacy restrictions. `!contacts global` also utilizes this feature.
- **Feature**: Hybrid Display Formatting. Contact lists now gracefully handle WhatsApp privacy limits, displaying real numbers when available and providing a summary of hidden numbers.
- **Feature**: Role-based Help Menu dynamically filters commands based on the user's role (User, Admin, Owner) and adds inline permission hints.
- **Fix**: `!contacts global` now aggregates and deduplicates contacts across all groups by scanning filesystem profiles.
- **Fix**: `!sc` (Deep Crawl Search) is now public when enabled; toggle remains owner-only.
- **Change**: `!export ledger` renamed to `!contacts export` and secured as an Owner-Only command.
- **Fix**: Agentic Search config mapping & Settings fields. Resolves the mismatch between `FeatureFlagService` and `app_settings` for `.env` integration.
- **Fix**: Config sync and removal of hardcoded search/crawl values.
- **Bug Fix**: Added missing `Settings` fields for Deep Crawl & Agentic Search (e.g. `search_max_results`, `deep_crawl_timeout_seconds`, etc.) in lowercase formatting. Fixed Pydantic `ValidationError` ("Extra inputs are not permitted") on startup by properly defining these fields in `app/config.py`.
- **Externalized Configuration**: Moved hardcoded timeout, context limit, and iteration magic numbers from `deep_crawl_service.py` and `agentic_search_service.py` to `.env`.
- **New `.env` Variables**: Added `LLM_TIMEOUT_SECONDS`, `CRAWL_TIMEOUT_SECONDS`, `DEEP_CRAWL_MAX_URLS`, `MAX_TOTAL_CONTEXT_CHARS`, `AGENTIC_MAX_ITERATIONS`, `SEARCH_RESULTS_PER_QUERY`, `OPENROUTER_RATE_LIMIT_DELAY`, and `FALLBACK_TO_SNIPPETS`.
- **Validation**: Added Pydantic `Field` bounds checking and `model_validator` clamping in `config.py` to ensure bot handles invalid env values gracefully.
- **Documentation**: Added `ai-chat/knowledge_base/CONFIGURATION_GUIDE.md` detailing the new variables.

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
