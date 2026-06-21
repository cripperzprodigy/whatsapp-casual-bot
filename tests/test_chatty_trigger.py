import pytest

def mock_update_counter(p, text, bot_id, default_freq):
    trigger = False
    is_mentioned = (bot_id and (bot_id in text or f"@{bot_id}" in text)) or "@bot" in text.lower()
    
    if is_mentioned:
        trigger = True
        p["message_counter"] = 0
    else:
        p["message_counter"] = p.get("message_counter", 0) + 1
        if p["message_counter"] >= p.get("chatty_frequency", default_freq):
            trigger = True
            p["message_counter"] = 0
    return trigger, p

def test_chatty_trigger_no_mention_empty_bot_number():
    p = {}
    bot_id = None # Simulating BOT_NUMBER = None after the pydantic validator
    default_freq = 5
    
    # 5 consecutive messages without mentions
    for i in range(1, 5):
        trigger, p = mock_update_counter(p, "hello", bot_id, default_freq)
        assert trigger is False
        assert p["message_counter"] == i
        
    # 5th message should trigger
    trigger, p = mock_update_counter(p, "hello 5", bot_id, default_freq)
    assert trigger is True
    assert p["message_counter"] == 0

def test_chatty_trigger_with_mention():
    p = {"message_counter": 3}
    bot_id = "12345"
    default_freq = 5
    
    trigger, p = mock_update_counter(p, "hey @12345 what's up", bot_id, default_freq)
    assert trigger is True
    assert p["message_counter"] == 0
    
def test_chatty_trigger_with_generic_bot_mention():
    p = {"message_counter": 2}
    bot_id = None
    default_freq = 5
    
    trigger, p = mock_update_counter(p, "hey @bot", bot_id, default_freq)
    assert trigger is True
    assert p["message_counter"] == 0
