# Architectural Decisions

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
