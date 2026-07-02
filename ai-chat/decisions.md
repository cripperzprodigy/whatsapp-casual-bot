# Architectural Decisions

## ADR-038 — RAG Temporal Decay with Configurable TTL

Date    : 2026-07-02
Status  : Accepted
Context :
  The RAG retrieval logic in `_retrieve_rag_context()` performed semantic
  search over ALL historical messages with no time-awareness. This caused
  stale information (e.g., old lunch plans, outdated preferences) to be
  retrieved and surfaced as if current, leading to hallucinations where the
  bot contradicted recent statements with old ones.

Decision :
  1. Add `RAG_DEFAULT_TTL_DAYS` (default: 7) to `app/config.py`. When > 0,
     retrieval queries include a `{"$and": [chat_id filter, timestamp >= cutoff]}`
     ChromaDB where clause to exclude messages older than the TTL.
  2. Implement `_is_historical_query(text)` module-level helper that detects
     temporal keywords ("last month", "remember when", "you mentioned", etc.)
     and bypasses TTL filtering for those queries — allowing users to
     explicitly ask about older history when needed.
  3. Add `expires_at` and `weight` metadata fields to every ChromaDB document
     during ingestion in `_append_history()`. These fields support future
     re-ranking and selective purge workflows.
  4. Implement a fallback: if the TTL-filtered query raises an exception
     (e.g., `n_results > filtered_count` in older ChromaDB versions), the
     system transparently retries with a chat_id-only filter.
  5. Set `RAG_DEFAULT_TTL_DAYS=0` to disable TTL filtering entirely.

Consequences :
  + Standard queries automatically exclude stale context, reducing hallucinations.
  + Users can still access historical context by phrasing queries with
    temporal markers — no functionality loss.
  + Configurable via `.env` — no magic numbers in code (SOP compliant).
  - Requires ChromaDB `$and` operator support. Older collection versions
    without `timestamp` metadata gracefully fall back to no-TTL query.

## ADR-037 — Session State Durability and Optimistic Locking

Date    : 2026-07-02
Status  : Accepted
Context :
  Critical per-session fields (current_tool, typing_state, tool_scratchpad)
  were stored exclusively in a Python in-memory dict. A process crash or
  restart lost all session state, potentially leaving chats in inconsistent
  states (e.g., stuck `is_processing=True`). Under high concurrency, two
  concurrent coroutines updating the same chat's state could corrupt it
  silently.

Decision :
  1. Add `SessionState` SQLAlchemy model to `app/state.py` with fields:
     `chat_id` (PK), `current_tool`, `typing_state`, `tool_scratchpad` (JSON),
     `session_version` (optimistic lock counter), `is_processing`, `last_active`.
  2. Implement `get_or_create_session_state(db, chat_id)` and
     `update_session_state_atomic(db, chat_id, updates, expected_version)`.
     The latter increments `session_version` on success and returns `False`
     on version mismatch (concurrent modification), allowing callers to
     detect and handle conflicts explicitly.
  3. Implement `recover_stale_sessions(db, stale_age_seconds=300)` which
     resets any session stuck with `is_processing=True` whose `last_active`
     is older than the threshold. Called automatically in `init_db()` on
     every startup.
  4. The `SessionState` table is created automatically via
     `Base.metadata.create_all()` — backward compatible with existing
     SQLite databases.

Consequences :
  + Critical session fields survive process restarts.
  + Concurrent updates are detected at the application level via the version
    counter rather than relying on database row-level locking.
  + Startup recovery eliminates "phantom in-flight" sessions after crashes.
  - Every critical state write now incurs a SQLite commit. This is
    acceptable given the infrequency of state changes vs message throughput.

## ADR-036 — Preference Scoping: Per-(user_id, chat_id) Persona Isolation

Date    : 2026-07-02
Status  : Accepted
Context :
  User preferences (tone, persona, language) were stored in per-chat
  `profile.json` files keyed by `chat_id`. However, nothing prevented
  code paths that looked up a sender's individual profile from applying
  DM-configured persona settings (e.g. "casual tone", custom emoji style)
  to group chat interactions, or vice versa.

Decision :
  1. Define two preference tiers in `app/services/profile_service.py`:
     - PERSONA keys: `{"tone", "emoji_style", "persona", "system_prompt"}` —
       scoped strictly to `(user_id, chat_id)`. A DM persona NEVER appears
       in a group lookup.
     - GLOBAL keys: `{"preferred_language", "lang_pref"}` — stored in a
       per-user global file and visible across all chats (fallback chain).
  2. Add functions `read_scoped_preferences()`, `write_scoped_preference()`,
     and `get_effective_preference()` to `profile_service.py`.
  3. Storage layout:
     - Scoped: `./data/prefs/{safe_user_id}/{safe_chat_id}.json`
     - Global: `./data/prefs/{safe_user_id}/global.json`
  4. Provide `scripts/migrate_preferences_scope.py` to copy existing DM
     profile.json data into the new global file format for existing users.
     The script is idempotent and supports `--dry-run`.
  5. Fallback chain for `get_effective_preference(user_id, chat_id, key)`:
     - Check `(user_id, chat_id)` scoped file first.
     - For PERSONA keys: stop — return default (no cross-chat bleed).
     - For GLOBAL keys: fall back to `(user_id, global)` → default.

Consequences :
  + DM persona settings are fully isolated from group contexts.
  + Language preference remains globally available (user can set once).
  + Existing data is preserved via idempotent migration script.
  + New scoped preference API is backward compatible with existing profile reads.

## ADR-030 — Active RAG Ingestion Pipeline

Date    : 2026-07-01
Status  : Accepted
Context :
  The ChromaDB + SentenceTransformer RAG infrastructure existed in
  `ai_memory_engine.py` but the ingestion path was dormant in two ways:
  (1) The `_append_history()` call that writes to ChromaDB was synchronous —
      `SentenceTransformer.encode()` is a CPU-bound operation that blocked
      the FastAPI asyncio event loop on every incoming message.
  (2) The "Silent Observer" and "Path B (delayed)" code paths in
      `router_webhook.py` used `await engine.process_message(generate_reply=False)`
      which blocked the webhook response cycle while computing embeddings, even
      though no reply was generated.
  There was no `ingest_message()` public API, no `ENABLE_RAG_INGESTION` kill-switch,
  no `RAG_TOP_K` configuration, and no way to backfill historical data.

Decision :
  1. Introduce a public `ingest_message(text, media_path, sender_id, message_type)`
     async method on `AIMemoryEngine`. It writes to `.jsonl` synchronously (for
     generate_delayed_reply() continuity) and schedules ChromaDB writes via
     `asyncio.create_task(_rag_ingest_async())` which runs inside
     `asyncio.to_thread()` to avoid blocking the event loop.
  2. Expose `ENABLE_RAG_INGESTION` (default: True) and `RAG_TOP_K` (default: 5)
     in `app/config.py` and `.env`. All ChromaDB writes and reads are guarded by
     the ENABLE_RAG_INGESTION flag. .jsonl writes are unconditional.
  3. Add `skip_user_ingestion=False` parameter to `process_message()`. Router
     callers set this to `True` after calling `ingest_message()` to prevent
     double-writing the user message to history.
  4. At all four message entry points in `router_webhook.py`, replace the blocking
     `await engine.process_message(generate_reply=False)` pattern with
     `asyncio.create_task(engine.ingest_message(...))`. This is consistent with
     ADR-013 (always use asyncio.create_task for fire-and-forget async work).
  5. Make RAG retrieval in `process_message()` and `generate_delayed_reply()` fully
     async via `asyncio.to_thread()` for both the encode and query steps.
  6. Update both system prompts to use an explicit `[CONTEXT MEMORY]` section with
     a continuity INSTRUCTION clause to improve LLM adherence to retrieved context.
  7. Provide `scripts/backfill_rag.py` for one-time historical ingestion.

Ingestion strategy :
  - Synchronous : .jsonl file write (fast I/O, < 1ms).
  - Asynchronous: SentenceTransformer encode + ChromaDB add, via
    asyncio.create_task → asyncio.to_thread (thread-pool, non-blocking).
  - Fire-and-forget: The webhook response is NOT delayed by ChromaDB writes.
  - Context isolation: Each chat_id maps to a separate `data/contacts/<safe_id>/`
    directory with its own ChromaDB PersistentClient and collection. DM data
    never leaks into group context.

Consequences :
  + Long-term memory is now genuinely active — all messages are indexed.
  + Event loop no longer blocks on embedding computation during ingestion.
  + Configurable kill-switch prevents runaway disk usage if ChromaDB causes issues.
  + `generate_delayed_reply()` still works correctly (reads from .jsonl which is
    always written before the async embedding task is scheduled).
  - Two async tasks are created per message (ingest + potential delayed reply).
    Both are lightweight and complete within the 5-10 second delay window.
  - Backfill of pre-existing data requires running `scripts/backfill_rag.py` once.

Latency impact :
  Ingestion path: ~0ms added to webhook response time (pure task scheduling).
  Retrieval path: encode + query moved off event loop, estimated 20-80ms added
  to LLM response time depending on ChromaDB collection size and hardware.

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

## ADR-030: Message Chunking & Sequential Sending for Long Responses
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (implementation)

### Context
Long bot responses (LLM synthesis, search results, AI replies) were sent as a single HTTP payload to the WhatsApp gateway. Payloads exceeding ~3000 chars caused `ReadTimeout` errors (default httpx timeout = 5s). The retry mechanism re-sent the same oversized payload, often failing again or causing duplicate delivery.

### Decision
1. **Smart Splitter**: New module `app/utils/message_splitter.py` with hierarchical splitting (paragraphs → sentences → words → hard cut). Max 2500 chars per chunk.
2. **`send_long_message()`**: Wrapper around `send_text_message()` that auto-chunks, adds part headers (`📄 Part 1/3`), sends sequentially with 1s delay. Short messages (≤2500) pass through directly.
3. **Selective Integration**: Only code paths producing potentially long text use `send_long_message()`. Short fixed messages stay on `send_text_message()`.
4. **Timeout Increase**: `httpx.AsyncClient` timeout raised from 5s to 15s.

### 2. Message Splitting Standard
- **Decision:** The Single-Response Contract necessitates chunking inside the send boundary.
- **Rule:** Use `app.utils.message_splitter` for any response longer than `MAX_MESSAGE_LENGTH`.
- **Reasoning:** Keeps business logic clean while respecting WhatsApp protocol limits.

### 3. Contact Privacy & Active Resolution
- **Decision:** WhatsApp webhooks often obfuscate users' real phone numbers into `@lid` hashes due to strict privacy settings.
- **Rule:** When displaying contacts (via `!contacts list` or `!contacts global`), the bot uses `resolve_participant_info_batch()` to query the Node.js Gateway `POST /participant/info/batch` endpoint in chunks of 10, with smart caching (24h TTL via `data/contact_resolution_cache.json`). If a real number still cannot be found, it gracefully degrades to displaying a `🔒 Hidden (Privacy)` indicator.
- **Reasoning:** Maximizes the utility of the bot for Owners while honoring unavoidable WhatsApp platform limitations without crashing or spamming the gateway.

### Consequences
- Positive: No more ReadTimeout on long responses.
- Positive: Users receive properly formatted multi-part messages.
- Positive: Zero overhead for short messages.
- Negative: Multi-part messages take N seconds longer (1s delay between chunks).

### References
- KB: `ai-chat/knowledge_base/MESSAGE_CHUNKING.md`
- `app/utils/message_splitter.py`

## ADR-031: Bot Identity Self-Identification via Sender Exclusion
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (implementation)

### Context
The bot's `.env` phone number (e.g., `6587481374`) has a completely different numeric base than its WhatsApp LID (e.g., `68728804868116@lid`). Direct matching is impossible. The `!whoami` command had two bugs: (1) owner gate ran before registration, blocking non-owner saves, and (2) all `mentioned_jids` were registered blindly without identifying which JID belongs to the bot.

### Decision
1. **Sender Exclusion**: Identify the bot's JID by excluding the sender's JID from `mentioned_jids`. Whatever remains is the bot.
2. **Unconditional Registration**: Save the LID before any ownership check.
3. **Two-Mode Handler**: Mode A (already registered) = owner-only status check, silently ignore non-owners. Mode B (first registration) = save unconditionally, only respond to owner.
4. **`!forget-me`**: Remains owner-only (destructive operation).

### Consequences
- Positive: `bot_known_lids.json` is reliably populated by any user tagging the bot.
- Positive: Owner gets full identity details via DM.
- Positive: Non-owners cannot probe bot identity once registered.
- Negative: If someone tags both the bot and another user in `!whoami`, the other user's JID is excluded by sender check but might still be registered if they're not the sender.

### References
- KB: `ai-chat/knowledge_base/WHOAMI_LID_REGISTRATION.md`
- `app/router_webhook.py` (!whoami handler)
- `app/config.py` (BotIdentityManager)

## ADR-032: Single-Response Contract for Duplicate Prevention
Date: 2026-06-30
Status: Accepted
Authors: DEBUG-LEAD (orchestration), Antigravity (implementation)

### Context
When OpenRouter API returned HTTP 500, `execute_iterative_search()` only caught `asyncio.TimeoutError`. Other exceptions (e.g., `TranslationError`) propagated to `commands.py`, where the caller's `except` block sent an additional error message — producing duplicate messages in the group chat.

### Decision
1. **Catch-all Contract**: Service functions that return user-facing messages MUST catch all exceptions internally and ALWAYS return a string. Never raise.
2. **Safety Net**: Callers may keep a defensive `except` block but must log `"this should not happen"` to flag contract violations.
3. **Logging**: Breadcrumb log entries at each fallback construction point.

### Consequences
- Positive: Exactly one message sent per command execution.
- Positive: Contract is easy to enforce and verify via log monitoring.
- Negative: Catch-all suppresses unexpected exceptions; must rely on logging to detect them.

### References
- KB: `ai-chat/knowledge_base/ERROR_HANDLING_DUPLICATE_PREVENTION.md`
- `app/services/agentic_search_service.py`
- `app/commands.py`
- SOP.md (Single-Response Contract rule)

## ADR-031 — Deep Crawl Search Architecture: SSRF Protection & Dynamic Context Budgeting

### Context
We introduced the `!sc` command to crawl and parse full HTML pages from search results. This introduces three major risks:
1. **Security**: Server-Side Request Forgery (SSRF) if the bot crawls private network IPs.
2. **Stability**: Fetching too many pages could cause a timeout or exhaust memory.
3. **LLM Context Overflow**: Combining the text of up to 20 full webpages would exceed the LLM's token window, leading to API crashes.

### Decision
1. **SSRF Protection via URL Validation**: Before any `httpx` GET request, `is_safe_url()` is invoked. It blocks non-HTTP schemes, resolves the hostname, and enforces `ipaddress` blocks against private (`10.x`, `192.168.x`), loopback, link-local, and multicast IP ranges.
2. **Dynamic Context Budgeting**: Instead of hardcoding a maximum character limit per page, we set a global `_TOTAL_CONTEXT_BUDGET` (15,000 characters). The per-page limit is dynamically calculated as `15,000 // MAX_URLS`. If `!sc` is configured for 5 URLs, each gets 3,000 chars. If 20 URLs, each gets 750 chars. 
3. **Dual-Layer Toggle Configuration**: `DEEP_CRAWL_MAX_URLS` and `DEEP_CRAWL_ENABLED` are loaded from `.env` and clamped. Runtime state (`!sc_toggle on|off`) persists to `global_config.json`.
4. **HTML Parsing Engine**: We use `BeautifulSoup` with `lxml` for fast stripping of non-content elements (`<script>`, `<nav>`, etc.).

### Consequences
- Positive: Fully mitigates SSRF vulnerabilities by forcing DNS resolution and verifying the resulting IPs before the request is initiated.
- Positive: The LLM context window is mathematically protected from overflow regardless of how many URLs the owner configures the bot to crawl.
- Negative: Heavy JS-rendered sites cannot be properly scraped, but fallback snippets provide graceful degradation.

### References
- `app/services/deep_crawl_service.py`
- KB: `ai-chat/knowledge_base/AGENTIC_SEARCH_FEATURE.md`

## ADR-033 — GroupContactLedger as Canonical Contact Store & Batch Resolution

### Context
The original contact system relied on filesystem-based `profile.json` files in `data/contacts/*_g_us/` directories. This caused:
1. Race conditions when aggregating files simultaneously (requiring `FileLock`).
2. Path mismatches between export directories and read directories (`!contacts global` returned empty).
3. No way to enrich contact exports with human-readable group names.

### Decision
1. **Database as Single Source of Truth**: All contact commands (`!contacts list`, `!contacts global`, `!contacts export`) now query the `GroupContactLedger` SQLite table exclusively. The filesystem-based `data/contacts/` directory is considered legacy.
2. **Batch Resolution Endpoint**: The legacy single-contact `GET /contact/info` and `GET /participant/info` endpoints have been replaced by `POST /participant/info/batch` which processes JIDs in chunks of 10.
3. **Smart Cache**: Resolution results are cached in `data/contact_resolution_cache.json` with a 24-hour TTL to prevent redundant gateway calls.
4. **Hierarchical Global Output**: `!contacts global` groups contacts by chat, with groups and members sorted alphabetically, using `ChatSettings` for group name resolution.
5. **Timestamped Exports**: `!contacts export` generates timestamped filenames (`ledger_YYYYMMDD_HHMMSS.csv`) and performs a SQLAlchemy outerjoin with `ChatSettings` for group name enrichment.
6. **Live Resolution for List**: `!contacts list` now performs live network resolution (identical to global) instead of showing stale cached data.

### Consequences
- Positive: Eliminates all filesystem race conditions.
- Positive: No more path mismatch bugs; single canonical data source.
- Positive: Export history is preserved (no more overwrites).
- Positive: Group context is preserved in both display and export.
- Negative: First-time resolution for large groups (500+ members) may take 10-20s, mitigated by smart cache on subsequent runs.

### References
- `app/commands.py` (handle_contacts_command)
- `app/contact_sync.py` (resolve_participant_info_batch)
- KB: `ai-chat/knowledge_base/CONTACT_SYNC_ARCHITECTURE.md`

## ADR-034 — Live Language Detection for Group AI Responses

### Context
The AI Memory Engine's `_detect_language()` method had a group-specific early return that bypassed actual language detection. For any group chat (`@g.us`), it immediately returned `chat_settings.default_target_language` (defaulting to `'en'`), meaning the AI always responded in English regardless of the user's input language.

### Decision
1. **Live Detection First**: For group chats, `_detect_language()` now runs `langdetect` on the actual incoming message text before considering any static defaults.
2. **3-Tier Fallback**: (1) `langdetect` library, (2) LLM-based `detect_language()` from `app/translation.py`, (3) group's configured `default_target_language` only as last resort.
3. **System Prompt Injection**: The detected language is injected into both `Preferred Language: {lang}` and the constraint `Reply ONLY in {lang}` in the system prompt.
4. **DM Unaffected**: The DM detection path (profile preference → langdetect → LLM fallback) was already correct and remains unchanged.

### Consequences
- Positive: Indonesian messages now receive Indonesian replies; English messages get English replies.
- Positive: `langdetect` is sub-millisecond, adding no measurable latency.
- Positive: Group's configured default still serves as a safety net if detection fails.
- Negative: None identified.

### References
- `app/services/ai_memory_engine.py:_detect_language()`
- KB: `ai-chat/knowledge_base/LANGUAGE_DETECTION.md`

## ADR-035 — RAG Per-Chat Filesystem Isolation & Defense-in-Depth Filtering

### Context
A code audit was initiated to investigate suspected cross-chat context leakage in the RAG retrieval pipeline — specifically whether a user's DM query might return messages from their group conversations, or vice versa.

The audit revealed that the existing architecture already provides **complete filesystem-level isolation**: each `chat_id` maps to a separate `ChromaDB.PersistentClient` at `./data/contacts/{safe_id}/vector_db/`. Since each chat has its own physical SQLite database, cross-chat vector retrieval is architecturally impossible.

However, two gaps were identified:
1. The retrieval queries used no `where` clause at all — relying entirely on filesystem separation.
2. The retrieval logic was duplicated identically in `process_message()` and `generate_delayed_reply()` (~20 lines each).
3. No integration tests existed to formally prove the isolation guarantees.

### Decision
1. **Extract `_retrieve_rag_context()`**: Consolidate the duplicated retrieval blocks into a single reusable async method, eliminating ~40 lines of code duplication.
2. **Defense-in-depth `where` clause**: Add `where={"chat_id": self.chat_id}` to the ChromaDB `collection.query()` call. This is a no-op in the current per-chat-db architecture but guards against future architectural changes (e.g., collection consolidation) accidentally breaking isolation.
3. **Isolation test suite**: Create `tests/test_rag_isolation.py` with 6 integration tests covering all cross-chat boundary scenarios (Group↔Group, Group↔DM, same-chat retrieval, where clause verification, filesystem path uniqueness).

### Consequences
- Positive: Formal proof (via tests) that no cross-chat leakage exists.
- Positive: Defense-in-depth ensures isolation survives future refactors.
- Positive: Code duplication eliminated — single retrieval method to maintain.
- Positive: Zero performance impact — `where` clause filtering within a single-chat collection adds negligible overhead.
- Negative: None identified.

### References
- `app/services/ai_memory_engine.py:_retrieve_rag_context()`
- `tests/test_rag_isolation.py`
- KB: `ai-chat/knowledge_base/RAG_MEMORY_ENGINE.md` (Context Isolation Architecture section)
