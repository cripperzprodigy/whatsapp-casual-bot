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
