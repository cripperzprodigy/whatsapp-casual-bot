from app.router_webhook import is_bot_mentioned, is_explicitly_tagged

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
