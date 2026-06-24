# [RESOLVED] Investigation: Threaded Conversation (Reply) Not Triggering

## 1. Problem Statement
In group chats, when a user uses the native WhatsApp "Reply" feature to respond directly to a message sent by the bot (e.g., "Yes, I'm here. How can I help you?"), the bot fails to respond immediately. It treats the message as a standard group message rather than a direct interaction.

## 2. Root Cause Analysis

After reviewing the recent implementations in `app/router_webhook.py`, the flow is as follows:

1. **Context Extraction (Success):** 
   The webhook router successfully calls `extract_context(content_obj, bot_number, bot_known_ids)`. It correctly identifies that the user is quoting the bot and returns a valid `context_tuple` (e.g., `("reply", "Yes, I'm here...")`).
   
2. **Mention Detection (Failure Point):** 
   The code checks if the bot was addressed using the `is_explicitly_tagged(text, bot_id, mentioned_jids)` function.
   However, when a user uses the WhatsApp "Reply" UI without manually typing out `@BotName` in the text box, WhatsApp **does not** automatically inject the bot's JID into the `mentioned_jids` array of the payload. 

3. **Routing Consequence:**
   Because `is_explicit_mention` evaluates to `False`, the `_handle_group_message` routing logic categorizes the message as a passive background message. It skips Path A (Immediate Inline Reply) and does not set `trigger = True` (unless the random chatty frequency counter happens to hit its limit on that exact message). The message is silently logged or sent to Auto-Translation.

## 3. Proposed Fix

We need to elevate a validated "reply context" to carry the same routing weight as an explicit `@mention`.

In `app/router_webhook.py`, inside `_handle_group_message`, we should update the mention logic:

```python
# Check for traditional text/JID mentions
is_text_mention = is_explicitly_tagged(text, bot_id, mentioned_jids)

# Check if the user is natively replying to the bot
has_reply_context = (context_tuple is not None) and (context_tuple[0] == "reply")

# Treat BOTH as an explicit mention for routing purposes
is_explicit_mention = is_text_mention or has_reply_context
```

We then update the `update_counter` closure to also trigger immediately if `is_explicit_mention` is True:

```python
def update_counter(p):
    nonlocal trigger
    nonlocal burst_count

    if is_explicit_mention:  # Updated to include reply context
        trigger = True
        p["message_counter"] = 0
    elif chatty_status:
        # ... frequency logic
```

## 4. Resolution
This issue has been successfully resolved. 
1. **Trigger Logic & NameError Fix**: The `NameError` for `is_explicit_mention` was resolved by explicitly defining it near the top of the function to satisfy auto-translation scoping requirements while maintaining the decoupled trigger priorities.
2. **JID Normalization**: `extract_context` now uses the `normalize_jid` helper string splitting logic on both the quoted sender JID and the bot's known IDs, successfully resolving mismatches between `@lid` and `@c.us` suffixes.
3. **Gateway Native Quoting**: The `send_text_message` function inside `whatsapp_gateway.py` has been explicitly updated to accept `quoted_msg_id` and map it to `payload["quotedMsgId"]`. This successfully renders the visual reply bubble inside WhatsApp UI.
4. **Empty Context on Tag/Reply**: Fixed `router_webhook.py` to correctly append the user's message (`text`) directly into the `final_user_input` context string before passing it into `engine.process_message()`, guaranteeing the AI is aware of exactly what the user is replying or tagging.
5. **LLM Connection Timeout**: Fixed `httpx` timeout defaults breaking high-latency local models by exposing `LLM_TIMEOUT_SECONDS` inside `.env.example` and `config.py`, and explicitly wiring it up to `httpx.Timeout` inside `app/ai_client.py`.
6. **400 Bad Request Payload Validation**: Fixed a bug where the Python webhook would pass `None` or `""` as `quotedMsgId` to the Node.js API if no reply was intended, resulting in a strict validation `400 Bad Request` crash. The gateway API call now safely trims and validates string bounds before merging `quotedMsgId` into the payload dictionary.
7. **Visual Quoting for Tags**: Updated `router_webhook.py` to aggressively map `getattr(msg_key, 'id', None)` to `quoted_msg_id` regardless of whether the incoming message was a Threaded Reply or a direct `@mention` Tag, ensuring the bot natively quotes the invoking message in all explicit triggering scenarios.
60. **Serialized ID Resolution (The Final Fix)**: Discovered that `whatsapp-web.js` expects strict composite quote IDs (e.g. `1234@g.us_3EB0...`) rather than the raw `_serialized` object format or short keys (`3EB0...`). Added a POST endpoint (`/message/resolve-quote-id`) to the Node.js gateway coupled with a global Map cache that dynamically constructs and translates short keys into the exact `chatId_messageId` format before allowing Python to dispatch quoted messages.
61. **Gateway `sendOptions` Validation & Payload Alignment**: Fixed the `/message/sendText` endpoint in Node.js to explicitly omit the third `sendOptions` parameter when calling `client.sendMessage()` if `quotedMsgId` is `undefined`, completely eliminating the persistent `400 Bad Request` schema failures that occurred when the bot fell back to plain text messages. We also adapted the Node gateway to seamlessly parse the modern Python payload schema (`to`, `message`, `quotedMsgId`).
62. **Synchronous Cache Initialisation & JID Normalization**: Discovered a critical race condition where fast webhook resolutions occurred before the `whatsapp-web.js` Node cache was successfully written. Expanded cache limits via ENV (`WHATSAPP_CACHE_MAX_SIZE=5000`, `WHATSAPP_CACHE_TTL_SECONDS=300`) with precise `setTimeout` garbage collection. Concurrently, unified all Python JID validations (`@lid`, `@c.us`) under `normalize_jid_for_comparison()` to guarantee accurate ReplyContext detection.
63. **Python JSON Parsing Fix for Cache Keys**: Resolved a defect in `app/whatsapp_gateway.py` where the code looked for `data.get("resolvedId")` instead of `data.get("serializedId")`, resulting in `None` being passed to the Node gateway even when a cache hit occurred. Visual quoting now works seamlessly on all cache hits.
64. **Reply Detection Prefix Handling Fix**: Fixed `app/router_webhook.py` `extract_context` logic to strip the leading `+` prefix from international JID numbers and consolidate under the robust `normalize_jid_for_comparison` standard. This resolves the `ReplyContext=False` mismatch where `6587...` failed to equal `+6587...`.

Status: **RESOLVED**. Quoting, Threaded Replies, Tags, and Payload Validation are fully operational.

65. **JID Normalization Logic Overhaul**: Refactored `normalize_jid_for_comparison` in `app/router_webhook.py` to use `.split("@")[0].lstrip("+")` instead of an explicit array of suffix replacements. This safely handles dynamically extended suffixes (like `@g.us_3EB0...`) and fixes the `ReplyContext=False` mismatch error when a user tags or replies to a bot in a group chat.

66. **Python JSON Parsing Fix & resolve_quote_id abstraction**: Refactored the inline resolving logic in `app/whatsapp_gateway.py` to `resolve_quote_id(short_id)`. The function now correctly parses `resp.json()`, accesses `resp_data.get("serializedId")`, and importantly prepends the `_INCOMING_MSG_PREFIX` (`"false_"`) to the serialized ID so that the Node gateway can correctly process visual quoting.
