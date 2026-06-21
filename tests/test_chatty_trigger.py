from app.router_webhook import is_bot_mentioned, is_explicitly_tagged

# ── Test Suite: Mention Detection ──

def test_dm_implicit_trigger():
    # DM Implicit Trigger: Input "Hello", Bot "123", Is_Group=False -> Expect True
    assert is_bot_mentioned("Hello", "123", is_group=False) is True

def test_group_tag_variations():
    # Input "@1234567890@c.us hello", Bot "1234567890" -> Expect True
    assert is_bot_mentioned("@1234567890@c.us hello", "1234567890", is_group=True) is True
    # Input "@1234567890 hello", Bot "1234567890" -> Expect True
    assert is_bot_mentioned("@1234567890 hello", "1234567890", is_group=True) is True

def test_false_positive_prevention():
    # Input "Call 12345", Bot "123" -> Expect False
    assert is_bot_mentioned("Call 12345", "123", is_group=True) is False
    # Input "Room 101", Bot "10" -> Expect False
    assert is_bot_mentioned("Room 101", "10", is_group=True) is False

def test_explicitly_tagged_bot_keyword():
    # Should match "@bot" case-insensitive with word boundaries
    assert is_explicitly_tagged("hey @bot how are you", "123") is True
    assert is_explicitly_tagged("@Bot", "123") is True
    assert is_explicitly_tagged("what is up @bOT", "123") is True
    # Should NOT match partials
    assert is_explicitly_tagged("hey @bottle", "123") is False
    assert is_explicitly_tagged("robot", "123") is False

def test_is_bot_mentioned_empty_bot_number():
    assert is_bot_mentioned("hello @bot", None, is_group=True) is True
    assert is_bot_mentioned("hello", None, is_group=True) is False
    assert is_bot_mentioned("hello", None, is_group=False) is True

# ── Test Suite: Dual-Path Architecture ──

def test_explicit_mention_bypasses_delay():
    """
    Verify that an explicit @bot tag results in is_explicitly_tagged = True,
    which means Path A (immediate inline reply) is selected, NOT Path B
    (delayed background task).
    """
    bot_number = "1234567890"
    text_with_mention = "hey @1234567890 what's the weather?"
    text_without_mention = "what's the weather?"

    # Path A: explicit tag detected -> immediate reply path
    assert is_explicitly_tagged(text_with_mention, bot_number) is True

    # Path B: no explicit tag -> frequency/delayed path
    assert is_explicitly_tagged(text_without_mention, bot_number) is False

def test_explicit_mention_immediate_response():
    """
    Validates the core acceptance criterion:
    When @bot is detected, is_explicitly_tagged returns True, which means
    the router will call process_message(generate_reply=True) inline
    instead of deferring to a background task.
    """
    # Group chat with @bot mention
    assert is_explicitly_tagged("@bot tell me a joke", "999") is True
    assert is_bot_mentioned("@bot tell me a joke", "999", is_group=True) is True

    # Group chat without mention — should NOT trigger explicit path
    assert is_explicitly_tagged("tell me a joke", "999") is False
    assert is_bot_mentioned("tell me a joke", "999", is_group=True) is False

    # DM — always triggers via is_bot_mentioned but is_explicitly_tagged can be False
    assert is_bot_mentioned("tell me a joke", "999", is_group=False) is True
    assert is_explicitly_tagged("tell me a joke", "999") is False

# ── Test Suite: Translation Suppression on Explicit Mention ──

def test_bot_mention_suppresses_translation():
    """
    When a message contains an explicit bot mention (@bot or @number),
    is_explicitly_tagged returns True. The router uses this to skip
    auto-translation, preventing duplicate responses.
    """
    bot_number = "1234567890"

    # Case A: "@bot hi" -> explicit tag = True -> translation SKIPPED
    assert is_explicitly_tagged("@bot hi", bot_number) is True

    # Case B: "Hello everyone" -> explicit tag = False -> translation ALLOWED
    assert is_explicitly_tagged("Hello everyone", bot_number) is False

    # Case C: "@bot hi" in foreign language -> still explicit -> translation SKIPPED
    assert is_explicitly_tagged("@bot 你好", bot_number) is True

def test_normal_messages_still_translate():
    """
    Messages that do NOT mention the bot should still be eligible
    for auto-translation. This ensures no regression.
    """
    bot_number = "999"

    # Normal group messages without mentions
    assert is_explicitly_tagged("Buenos días a todos", bot_number) is False
    assert is_explicitly_tagged("Guten Morgen!", bot_number) is False
    assert is_explicitly_tagged("Hello 12345", bot_number) is False

# ── Test Suite: Native WhatsApp Mentions ──

def test_native_whatsapp_mention():
    """
    When a user natively tags the bot using the @ dropdown, the webhook
    payload contains the bot's JID in extendedTextMessage.contextInfo.mentionedJid.
    The text might just say @ContactName without the bot's number.
    """
    bot_number = "1234567890"
    bot_jid = f"{bot_number}@s.whatsapp.net"
    other_jid = "9999999999@s.whatsapp.net"

    # Case A: Text doesn't contain the number, but native JID is present -> True
    assert is_explicitly_tagged("@BotName hello", bot_number, mentioned_jids=[bot_jid]) is True

    # Case B: Text doesn't contain the number, other JID is present -> False
    assert is_explicitly_tagged("@SomeoneElse hello", bot_number, mentioned_jids=[other_jid]) is False

    # Case C: Multiple JIDs including the bot -> True
    assert is_explicitly_tagged("@Everyone hello", bot_number, mentioned_jids=[other_jid, bot_jid]) is True

    # Case D: whatsapp-web.js format (@c.us)
    wwebjs_jid = f"{bot_number}@c.us"
    assert is_explicitly_tagged("@Bot hello", bot_number, mentioned_jids=[wwebjs_jid]) is True

    # Case E: Any other format (e.g. @any.domain)
    random_jid = f"{bot_number}@any.domain"
    assert is_explicitly_tagged("@Bot hello", bot_number, mentioned_jids=[random_jid]) is True

