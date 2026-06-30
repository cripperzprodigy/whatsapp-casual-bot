# Architectural Decisions

# Key Decisions
## Event-Driven Memory Cache (O(1) Quote ID Translation)
Instead of using slow, IO-blocking calls to `chat.fetchMessages({ limit: 50 })` which regularly failed to locate IDs under load, we've opted for an **Event-Driven Memory Map** cache embedded natively into the Node.js `whatsapp-service/src/events.js` listener. 
Because `whatsapp-web.js` operates asynchronously, we aggressively map and cache incoming `{msg.id.id}` (Short ID) directly to their strictly formatted composite counterparts (`{msg.id.remote}_{msg.id.id}`).
- To prevent Memory Leaks, this `Map()` is strictly bounds-checked using `WHATSAPP_CACHE_MAX_SIZE` (default 5000) and explicitly dropped via `setTimeout` based on `WHATSAPP_CACHE_TTL_SECONDS` (default 300s).
- Resolution calls from Python execute via an O(1) synchronous map lookup over the internal API. If the bot attempts to quote a message that has fallen out of bounds or expired due to TTL, it gracefully abandons the visual quote UI and falls back to plain text to ensure delivery stability.

### Global Event-Driven Cache for WhatsApp Message IDs
**Decision**: In `whatsapp-service/src/events.js`, we intercept `client.on('message')` events and locally cache short message IDs against their full serialized IDs inside a standard `Map()` up to 1000 items. We expose `/message/resolve-quote-id` so Python can do an O(1) lookup.
**Rationale**: `whatsapp-web.js` forces the usage of full serialized IDs (e.g., `false_1234@g.us_3EB0...`) when quoting a message in a reply. The Python backend only possesses the short message ID keys extracted from the webhook payload (`3EB0...`). The initial attempt to resolve this via `chat.fetchMessages({ limit: 50 })` was deemed highly inefficient and unreliable. A rolling LRU Map completely eliminates disk/network lookup time, returning the precise Serialized ID perfectly unless the target message has fallen out of the top 1000 queue (at which point the Python client will gracefully fall back to a non-quoted reply). The internal JSON contract specifies `{"success": true, "serializedId": "..."}`.

## ADR-018 — Threaded Conversation Support & Context Extraction

Date    : 2026-06-25
Status  : Accepted
Context :
  The Chatty engine previously treated all incoming group messages as isolated events, resulting in disjointed replies when users explicitly replied to the bot's own past messages (e.g., saying "That was funny" to a joke). 

Decision :
  Extract `quotedMessage` contexts directly from the incoming Baileys webhook payload. To prevent spoofing (users maliciously framing fake messages as bot replies), we strictly validate the `participant` field of the quoted message against the active `BOT_NUMBER` and registered LIDs in `BotIdentityManager`. The validated parent message is dynamically injected into the AI's `system_prompt`.

Consequences :
  + Seamlessly restores multi-turn conversational awareness in busy group chats.
  + Eliminates spoofing vulnerability by relying on verified identity cache.
  + Operates asynchronously via the webhook router without blocking heavy database tasks.

## ADR-017 — Owner-Registered Bot Identity (LIDs)

Date    : 2026-06-25
Status  : Accepted
Context :
  WhatsApp uses unhydrated Local IDs (`@lid`) in multi-device group chats. The bot's mention detection logic failed because it strictly compared incoming JIDs to the configured phone number. Complex background resolution services were deemed too fragile and slow for the synchronous webhook router.

Decision :
  Implement an Owner-Registered Identity pattern where the bot learns its own runtime identity (LIDs) directly from user interactions. The `!whoami` and `!forget-me` commands allow the bot owner to tag the bot and save the resulting LID directly to persistent storage (`data/bot_known_lids.json`).

Consequences :
  + Solves the silent group chat mention failures securely without network overhead.
  + Eliminates dependency on gateway LID-resolution for self-identity.
  + Owner-only security enforces that bad actors cannot maliciously re-register the bot's identity to intercept commands.
  - Requires a one-time manual registration step by the owner in group chats using LIDs.

## ADR-014 — Runtime Bot Identity Detection over Static Configuration

Date    : 2026-06-24
Status  : Accepted
Context :
  The bot's WhatsApp JID is only reliably known after the
  whatsapp-web.js client authenticates. Storing it in a static
  environment variable (BOT_NUMBER) is fragile because the JID
  can change across re-authentications or deployments.

Decision :
  The Node.js gateway exposes a /whatsapp/bot-identity endpoint.
  The Python backend fetches this at startup and on a 5-minute TTL
  via BotIdentityManager. The ENV variable is retained as a fallback
  for degraded-mode operation.

Consequences :
  + Bot identity is always accurate after initial connection.
  + Eliminates a class of silent misconfiguration bugs.
  + Adds a lightweight internal HTTP dependency (mitigated by cache).
  - Slight startup delay on first cold fetch (mitigated by 2 s timeout
    and fallback to ENV).

Pattern established :
  "Runtime detection over static configuration" — prefer detecting
  volatile system identities at runtime rather than requiring them
  to be pre-configured in .env.

## ADR-015 — Auto-Sync Bot Number to Environment Variables

Date    : 2026-06-25
Status  : Accepted
Context :
  The bot identity mismatch issue was partially fixed in ADR-014 by
  reading identity dynamically. However, the BOT_NUMBER environment
  variable would remain stale, leading to warnings. Furthermore,
  degraded mode (gateway unreachable) relies on BOT_NUMBER.

Decision :
  Implement an auto-sync mechanism where if the runtime-detected bot
  identity differs from the BOT_NUMBER in the .env file, the bot will
  automatically update .env (via a file-locked read-modify-write) and
  trigger a configuration reload when AUTO_SYNC_BOT_NUMBER=True.

Consequences :
  + Keeps .env perpetually in sync without manual user intervention.
  + Degraded mode becomes highly reliable since the fallback value is
    automatically curated.
  - Requires writing to .env at runtime which needs strict file locking.

## ADR-016 — Local Regex Fallback over Network LID Resolution

Date    : 2026-06-25
Status  : Accepted
Context :
  When the bot is mentioned in a group chat, WhatsApp's multi-device
  architecture often issues an unhydrated `@lid` identifier in the
  `mentioned_jids` payload instead of a `@s.whatsapp.net` number.
  Because the webhook router runs in Python, resolving this LID requires
  issuing an HTTP `getNumberId()` request back to the Node.js gateway.
  Doing this synchronously on every incoming group message introduces
  unacceptable network latency and blocking.

Decision :
  We implemented a text-based regex fallback rather than network LID
  resolution. The Node.js gateway now exposes the bot's display name
  (`pushname`) via `/whatsapp/bot-identity`. The Python backend caches
  this. If the strict JID array match fails, the router simply performs
  a local case-insensitive regex search for `@BotName` or `@BotNumber`
  in the message text.

Consequences :
  + Preserves high throughput by avoiding synchronous HTTP fetches on
    every group message.
  + Perfectly restores mention reliability for multi-device `@lid` cases.
  - Relies on string matching which could theoretically yield false
    positives if another user shares the bot's exact name.

- **Token Limits for Reasoning Models:** Decided to use 8192 default tokens and strict prompting for high-context local reasoning models. This prevents models from exhausting tokens on verbose reasoning tracks.
- **Custom Exceptions:** Introduced `TokenExhaustedError` and `TranslationError` instead of returning dataclasses from `ask_llm`. This enables precise error handling and clean retry mechanisms.
-   * * S t r i c t   W h i t e l i s t i n g   f o r   T a r g e t   L a n g u a g e s : * *   I n s t e a d   o f   g r e e d i l y   t r e a t i n g   t h e   f i r s t   w o r d   a f t e r   ' ! t '   a s   a   l a n g u a g e   c o d e   i f   i t s   l e n g t h   i s   2 ,   t h e   s y s t e m   n o w   e n f o r c e s   a   s t r i c t   w h i t e l i s t   b a s e d   o n   2 0   k n o w n   I S O   c o d e s .   T h i s   a l l o w s   v a l i d   2 - l e t t e r   s l a n g   w o r d s   t o   f a l l   b a c k   s a f e l y   t o   t e x t   t r a n s l a t i o n .
 -   * * S e m a n t i c   C h u n k i n g : * *   T e x t   e x c e e d i n g   T R A N S L A T I O N _ C H U N K _ S I Z E   i s   s p l i t   h i e r a r c h i c a l l y   b y   p a r a g r a p h ,   l i n e ,   a n d   s e n t e n c e .   T h e   l a s t   s e n t e n c e   o f   c h u n k   N   i s   p a s s e d   a s   a   p r o m p t   p r e f i x   t o   c h u n k   N + 1   t o   m a i n t a i n   p r o n o u n   a n d   t o n e   c o n t i n u i t y .

- **DM Implicit Mentions:** Decided to treat all DMs as implicit mentions for Chatty mode, completely bypassing the message frequency requirement for DMs. This is because users interact conversationally in DMs and do not prepend the bot's phone number as they would in a Group Chat. Group Chats still require explicit tagging or exceeding the frequency threshold.
- **Explicit Mention Overrides:** Decided that explicit mentions (text `@bot` or native WhatsApp `@` tagging) take precedence over a group's default Chatty settings. If a user explicitly summons the bot, it will immediately respond via the Path A (Immediate) pipeline, completely overriding and bypassing the negative `CHATTY_GROUP_DEFAULT` or localized group settings.
- **Node.js Adapter Pattern for JID Suffixes:** Decided to strictly isolate unofficial domain suffixes (like `whatsapp-web.js`'s `@c.us`) inside the Node.js gateway. The Python backend is designed against the official WhatsApp standard (`@s.whatsapp.net`). The Node.js gateway now acts as a pure translation adapter, replacing `@c.us` with `@s.whatsapp.net` on inbound webhooks, and translating it back to `@c.us` on outbound API requests.
  - **Extension: Linked Device (@lid) Normalization:** WhatsApp Web.js also emits `@lid` suffixes for messages from linked devices (secondary devices synced to primary WhatsApp account). These are legitimate user communications, not system domains. The Node.js gateway now also normalizes `@lid` → `@s.whatsapp.net` on inbound payloads, ensuring linked device messages are not incorrectly blocked by the Python guard rail.
- **Decision #7: Strict Message Domain Separation**
  - **Problem:** Tangled logic in `router_webhook.py` causing DM/Group conflicts. DMs and Groups were passing through the same conditional tree, leading to translation leaks in DMs, inappropriate chatty suppression, and fragility.
  - **Decision:** DMs and Groups are treated as mutually exclusive domains with completely separate handlers from the moment the message is received. `router_webhook.py` is split into `_handle_dm_message()` and `_handle_group_message()`.
  - **Consequences:** Auto-translation is permanently disabled for DMs. DMs always interact with the Chatty RAG memory engine. Commands are evaluated prior to the split.
  - **Status:** Accepted.
- **Auto-Recovery Strategy for WhatsApp Gateway**: We implemented a tiered auto-recovery mechanism in the Node.js service for session corruption (e.g. "No LID for user"). Previously, corruption triggered immediate aggressive deletion of the `.wwebjs_auth` directory. The new strategy attempts Graceful Session Recovery first:
  - **Tier 1:** Restart the underlying Puppeteer execution context (resolves most UI injection issues).
  - **Tier 2:** Reinitialize the `whatsapp-web.js` client without deleting the session folder.
  - **Tier 3:** If Tiers 1 and 2 fail, aggressively delete the `.wwebjs_auth` session directory via `fs.rmSync` and prompt for a new QR scan.
  This tiered approach drastically reduces the frequency of forced manual QR rescans caused by transient network or Puppeteer corruption.
- **Decision #9: Standardized Inter-Service Protocol**
  - **Problem:** Implicit crashes and state desync between the Node.js WhatsApp Gateway and Python Backend due to session corruption (e.g. `getChat undefined`).
  - **Decision:** Implemented WISP (WhatsApp Inter-Service Protocol) with strict Pydantic/JSON schemas for `OutboundMessageRequest`, `DeliveryResponse`, and standardized `ErrorCode`s. The gateway operates in `CONNECTED`, `RECOVERING`, or `DISCONNECTED` states, utilizing 202 Accepted for queuing messages and 503 Service Unavailable for unrecoverable corruption.
  - **Consequences:** Provides absolute state visibility to the Python backend, prevents silent crashes, and queues DM commands like `!claim_ownership` when the session is gracefully recovering.
  - **Status:** Accepted.


## Decision: Asynchronous Recovery Queuing for WhatsApp Gateway

**Context:**
During session recovery loops in the Node.js gateway, synchronous retries often failed with a "detached Frame" error because Puppeteer context was still reloading. Furthermore, "No LID" errors were falsely flagged as full session corruptions.

**Decision:**
1. "No LID" is now treated as a non-fatal warning and excluded from `isSessionCorruptionError`.
2. `getChatById` pre-checks are bypassed upon failure to prevent blocking the send pipeline.
3. Upon detecting a true session corruption and initiating recovery, the gateway immediately pushes the message to `recoveryMessageQueue` and returns `HTTP 202`. The queue is then processed asynchronously after a delay, avoiding detached frame errors.

## Decision #10: getNumberId() for LID-safe DM sending
**Context**: WhatsApp's multi-device protocol introduces Linked IDs (LIDs) that are required for outbound message routing. Sending to a raw `@c.us` JID fails with `No LID for user` if the user's mapping isn't fully hydrated in the store (e.g. only seen in groups, not DMs). Bypassing `client.getChatById` doesn't fix this since `client.sendMessage` internally uses the same LID lookup.
**Decision**: Use `client.getNumberId(rawPhone)` to resolve the true serialized LID prior to sending a DM message.
**Consequence**: Eliminates `No LID for user` as a failure class, preventing unnecessary retries. If `getNumberId()` returns null, we safely throw a `NUMBER_NOT_ON_WHATSAPP` hard-abort (HTTP 400).
## Decision #11: Immediate Cleanups during Refactoring
**Context**: Iterative refactoring leaves behind legacy fragments, dead comments, and duplicate entries, bloating the repository and adding cognitive load.
**Decision**: Enforce an immediate cleanup of artifacts (such as dead comments and stale backup files like `*.bak` or `*.old`) within the refactoring phase itself instead of batching them up.
**Consequence**: Maintain high repository hygiene without requiring separate hygiene-only sweeps.
## Decision #12: Always Await Async Functions Before Boolean Evaluation
**Context**: `!chatty_delay` and `!chatty_mode` referenced `is_owner` as a variable instead of awaiting the async function, causing a `NameError` that was silently caught by the try/except block.
**Decision**: All async functions must be explicitly awaited before use in conditions. Never reference an async function as if it were a variable.
**Consequence**: Prevents silent failures where coroutine objects are evaluated as truthy in boolean contexts instead of the actual result.
## Decision #13: Use `asyncio.create_task()` for Background Work — Never `BackgroundTasks.add_task()` with Coroutines
**Context**: `background_tasks.add_task(process_message, payload)` in `whatsapp_webhook()` silently dropped every DM message because FastAPI's `BackgroundTasks.add_task()` wraps async functions in a regular callable, so the coroutine is never awaited.
**Decision**: Always use `asyncio.create_task()` directly for fire-and-forget async work. `BackgroundTasks.add_task()` only works with synchronous (non-async) callables.
**Consequence**: Prevents the entire class of "silent message loss" bugs where incoming webhooks are silently ignored.

### LLM Timeout Configurability
**Decision**: Expose LLM_TIMEOUT_SECONDS (default: 180s) via config.py and pass it to httpx.Timeout for all AsyncOpenAI operations.
**Rationale**: Local LLM inferences (e.g. LM Studio, Ollama) on slow hardware often take ~40-120 seconds. Standard httpx timeouts kill the connection prematurely, causing race conditions and logic drop-offs (e.g. failing to pass quoted message context downstream).

## ADR-019 — Robust JID Normalization

Date    : 2026-06-25
Status  : Accepted
Context :
  The `normalize_jid_for_comparison` was previously iterating through a list of possible suffixes (`@c.us`, `@lid`, etc.) to strip from incoming and internal JIDs. This failed when suffixes contained dynamic components (like the Message ID in `@g.us_3EB0...`), resulting in `ReplyContext=False` when users replied to the bot.

Decision :
  Refactored `normalize_jid_for_comparison` to uniformly drop everything from the `@` symbol onwards using `jid.split('@')[0].lstrip('+')`.

Consequences :
  + Eliminates hardcoded list of suffixes for comparison matching.
  + Accurately identifies `ReplyContext` from incoming `whatsapp-web.js` webhook events.
  + Streamlines message matching and context injection in `app/router_webhook.py`.

## ADR-020 — Webhook Quoted Message Context Serialization

Date    : 2026-06-25
Status  : Accepted
Context :
  The Python `extract_context` function expects Baileys-style `contextInfo.quotedMessage` to determine if a message is a reply to the bot. However, `whatsapp-web.js` does not automatically populate quoted messages into a single nested payload.
Decision :
  In `whatsapp-service/src/events.js`, when a message comes in with `hasQuotedMsg=true`, we manually fetch `getQuotedMessage()` and inject `quotedMessage.conversation` and `participant` into the outgoing `contextInfo` payload. We also updated the message caching logic to directly map `msg.id.id` to `msg.id._serialized` to perfectly emulate the visual quoting API string.
Consequences :
  + The Python backend can natively detect `ReplyContext=True` without extra network API calls.

## ADR-021 — Strict Webhook Quoted Message Hydration

Date    : 2026-06-25
Status  : Accepted
Context :
  The Python `extract_context` function expects Baileys-style `contextInfo.quotedMessage` to determine if a message is a reply to the bot. However, `whatsapp-web.js` does not automatically populate quoted messages into a single nested payload.
Decision :
  In `whatsapp-service/src/events.js`, when a message comes in with `hasQuotedMsg=true`, we manually execute an async `getQuotedMessage()`. We then format it into an object matching the Baileys API (`{ conversation: qMsg.body }`) and inject it into the `contextInfo.quotedMessage` field of the outgoing webhook payload, along with the `participant` field.
Consequences :
  + The Python backend can natively detect `ReplyContext=True` without needing extra API endpoints to fetch message context synchronously during the webhook cycle.
  + Eliminates dropping Threaded Conversations (native replies) from Chatty Engine flow.

## ADR-022 — Native Object Serialization for Quoted Message IDs

Date    : 2026-06-25
Status  : Accepted
Context :
  The Node.js gateway was attempting to manually reconstruct message IDs for caching using `${msg.id.remote}_${msg.id.id}` and Python was attempting to prepend `false_`. This approach failed because the `whatsapp-web.js` `sendMessage({ quotedMessageId })` API strictly requires the exact raw `_serialized` object format emitted by the library.
Decision :
  `whatsapp-service/src/events.js` now exclusively maps `msg.id.id` to `msg.id._serialized` in the internal LRU map. The Python backend fetches this exact string via `/message/resolve-quote-id` and passes it perfectly back through the `quotedMsgId` payload field during outbound requests.
Consequences :
  + Restores visual quoting functionality across Group chats and DMs.
  + Eliminates hardcoded `false_` prefixes from the Python backend entirely.

## ADR-023 — Hybrid Web Search and Fallback Strategy

Date    : 2026-06-25
Status  : Accepted
Context :
  The `!search` command lacked true web access and relied solely on LLM internal knowledge. We needed a robust real-time search component that could respect async event loop boundaries.
Decision :
  - Developed `HybridSearchService` in `app/services/search_service.py` with `SearXNGProvider` and `DuckDuckGoProvider`.
  - Used `SEARCH_PROVIDER_MODE="hybrid"` configuration by default to attempt SearXNG first, gracefully catching errors (like 429 timeouts or connection errors), and falling back to DuckDuckGo search without bubbling errors to the user.
  - `DuckDuckGoProvider` is wrapped using `asyncio.to_thread` because `ddgs` is synchronous and would block the FastAPI event loop.
Consequences :
  + Search queries execute natively over the web via external providers without slowing the application or UI.
  + Automatically protects users from 429 connection timeouts when one search backend goes down.

## ADR-024 — Iterative Agentic Search (!s)
Date    : 2026-06-25
Status  : Accepted
Context :
  The existing `!search` command is linear, lacking the ability to evaluate findings, recognize missing context, and refine its search to gather comprehensive information.
Decision :
  - Developed `AgenticSearchOrchestrator` in `app/services/agentic_search_service.py` to facilitate iterative research using `HybridSearchService`.
  - Added the `!s <query>` command alongside `!search`.
  - Implemented a "Gap Analysis" LLM Prompt strategy: Prompt LLM at the end of each iteration to analyze findings and determine if `sufficient`, missing info, and suggest a `refined_query` to continue searching up to a maximum of 2 iterations.
  - Hard loop limits (max 2 iterations) and time boundaries (14 seconds globally, 3-6 seconds locally per-step) enforce limits.
Consequences :
  + Empowers the bot to comprehensively research deep topics.
  + Does not block the event loop or violate latency requirements due to graceful degradation.

## ADR-025 — Feature Flag System & Dynamic Help
Date    : 2026-06-25
Status  : Accepted
Context :
  Experimental features like `!s` (Agentic Search) were deployed without a centralized way to safely toggle them off in production, or hide them from the help menu based on user roles, leading to potential resource exhaustion and bad UX.
Decision :
  - Created `FeatureFlagService` which stores runtime toggle states within the SQLite `GlobalSettings` table (to persist across restarts).
  - Added the `!config toggle <feature> <on|off>` command, strictly restricted to the `OWNER` role.
  - Refactored `!help` to dynamically build its text sections based on `FeatureFlagService.is_enabled` and `user_role`, maintaining clear separation of commands.
Consequences :
  + Experimental features can be turned off dynamically without downtime.
  + Users only see the commands they have permission to execute or that are actively enabled.

## ADR-026: Mandatory quotedParticipant for Group Chat Message Attribution
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (documentation)

### Context
Group message replies handled by `whatsapp-web.js` require both the `quotedMessageId` and the `quotedParticipant` (the original sender's JID) to correctly attribute the quote in the native WhatsApp UI. Previously, `quotedParticipant` was accepted by the Python gateway interface but silently dropped before HTTP serialization, causing missing attribution in group chat threaded replies (e.g., Chatty mentions or auto-translations).

### Decision
We mandate that all group chat replies MUST include the `quotedParticipant` parameter end-to-end. The Python payload must serialize it, the Node.js gateway must extract and map it into `sendOptions`, and all webhook routers must supply `msg_key.participant` when replying in groups.

### Consequences
- Positive: Proper message attribution in groups (UI displays "Replying to @user" correctly).
- Negative: Slightly more complex payload construction and routing logic.
- Neutral: DMs remain unchanged (participant remains `None` since DMs do not have multiple participants).

### Implementation Details
- Python layer: `whatsapp_gateway.py` includes `quotedParticipant` in the outbound JSON payload.
- Node.js layer: `send.js` extracts and applies `quotedParticipant` to `sendOptions`.
- Router layer: `router_webhook.py` explicitly passes `msg_key.participant` for group replies.

### References
- `ai-chat/changelog.md` (fix entry)
- `ai-chat/issues.md` (issue log)
- `ai-chat/knowledge_base/WISP_PROTOCOL.md` (schema)

## ADR-027: Keyword Heuristic for Short Malay/Indonesian Text Detection
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (implementation)

### Context
The `langdetect` library is statistically unreliable for texts shorter than ~20 characters, particularly for Malay (`ms`) and Indonesian (`id`). Common conversational words like "mulai", "makan", "saya" are frequently misidentified as Finnish (`fi`), Tagalog (`tl`), or English (`en`). This caused auto-translation to silently skip messages that should have been translated.

### Decision
Implement a two-tier hybrid detection strategy in `detect_language_safe()`:
1. **Short-text heuristic** (< 20 chars): Tokenize and check against a curated `COMMON_MS_ID_WORDS` set (~80 words). If ≥ 50% of tokens match, bypass `langdetect` and return `"ms"`.
2. **False-positive guard** (all lengths): If `langdetect` returns a known false-positive language (`fi`, `tl`, `so`, `sw`, `hr`, `ro`) AND the keyword heuristic also matches, override to `"ms"`.

### Consequences
- Positive: Short Malay/Indonesian phrases now correctly trigger translation.
- Positive: No regression for English — common English words are not in the keyword set.
- Negative: The keyword set requires manual curation and may need expansion over time.
- Neutral: Existing `TRANSLATION_EQUIVALENT_LANGS` config (`id,ms`) continues to prevent unnecessary id↔ms translations.

### References
- `ai-chat/knowledge_base/LANGUAGE_DETECTION.md` (full algorithm documentation)
- `app/translation.py` (implementation)

## ADR-028: EN/ID/MS Linguistic Sphere — Shared Language Group Policy
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (implementation)

### Context
In multilingual WhatsApp groups where users naturally mix English, Malay, and Indonesian, the auto-translation feature was generating unnecessary translations between these three languages. Users consider EN/ID/MS as mutually intelligible within their social context. Additionally, `langdetect` frequently misidentified short ms/id texts as Finnish or Tagalog, triggering incorrect translations.

### Decision
Implement an EN/ID/MS Linguistic Sphere policy:
1. `GLOBAL_IGNORED_LANGUAGES` defaults to `"en,id,ms"` — messages detected as any of these are **never translated**.
2. `TRANSLATION_EQUIVALENT_LANGS` expanded to `"en,id,ms"` — all three are treated as mutually equivalent.
3. The keyword heuristic (`COMMON_MS_ID_WORDS`) checks against the ignored set and returns `None` (skip) immediately.
4. The `langdetect` result is checked against `GLOBAL_IGNORED_LANGUAGES` before any translation proceeds.
5. Only truly foreign languages (Arabic, Chinese, Japanese, French, etc.) trigger translation.

### Consequences
- Positive: No unnecessary translations between EN/ID/MS in multilingual groups.
- Positive: Eliminates all `langdetect` false positives for ms/id that previously leaked through.
- Positive: Configurable — users can remove languages from the sphere via `.env`.
- Negative: Code-switching sentences (e.g., "I nak go to school") are silently skipped. This is intentional — the user community considers these natural.
- Neutral: Foreign languages (ar, zh, ja, fr, de, es, etc.) continue to be translated correctly.

### References
- `ai-chat/knowledge_base/LANGUAGE_DETECTION.md` (algorithm documentation)
- `app/config.py` (configuration defaults)
- `app/translation.py` (implementation)

## ADR-029: Hierarchical Auto-Translation Control with External Keyword Dictionary
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (implementation)

### Context
The translation skip keywords were hardcoded in `translation.py` as `COMMON_MS_ID_WORDS`, making it impossible for users to expand the dictionary without code changes. Additionally, there was no Owner-only global toggle command — only per-group `!auto on/off` existed. The `.env.example` defaults were misaligned with code defaults, creating confusion.

### Decision
1. **External Keyword File**: Move keywords to `data/translation_skip_keywords.txt` (one per line, `#` for comments). Loaded at startup with `frozenset` caching.
2. **Global Toggle Command**: Add `!globaltrans on/off` (Owner-only) that persists state to `data/global_config.json`.
3. **Hierarchy**: Global OFF → all translation disabled. Global ON → per-group `!auto on/off` controls individual groups.
4. **Safe Defaults**: `GLOBAL_AUTO_TRANSLATE=False` in both code and `.env.example`.

### Consequences
- Positive: Users can expand keywords without code changes.
- Positive: Owner has runtime control over global translation state.
- Positive: Hierarchy is clear: Global → Group → Keyword → Sphere → Translate.
- Negative: Keyword file changes require restart (no hot-reload yet).

### References
- `data/translation_skip_keywords.txt` (keyword dictionary)
- `app/config.py` (loader and persistence)
- `app/commands.py` (`!globaltrans` handler)
