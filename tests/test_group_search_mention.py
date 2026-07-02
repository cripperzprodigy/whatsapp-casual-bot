import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import time
from app.utils.search_intent import clean_query, detect_search_intent
from app.router_webhook import _handle_group_message, _group_search_cooldowns
from app.config import Settings
import asyncio

# --- TestQueryCleaning ---
def test_clean_query_basic():
    assert clean_query("@CasualBot search for batam news", "CasualBot") == "batam news"
    
def test_clean_query_can_you():
    assert clean_query("@CasualBot can you look up f1 results", "CasualBot") == "f1 results"

def test_clean_query_please():
    assert clean_query("@CasualBot please find laksa recipe", "CasualBot") == "laksa recipe"

def test_clean_query_mid_sentence():
    assert clean_query("hey @CasualBot google weather", "CasualBot") == "hey weather"
    
def test_clean_query_ignore_case():
    assert clean_query("@CASUALBOT CoULd YoU SeArCH FoR testing", "CasualBot") == "testing"

def test_clean_query_multiple_trigger_words():
    assert clean_query("@CasualBot please can you search for something", "CasualBot") == "something"

def test_clean_query_no_trigger_words():
    assert clean_query("@CasualBot something", "CasualBot") == "something"

# --- TestMentionDetection ---
def test_detect_search_intent_valid():
    # In webhook, we extract text after mention to detect search intent
    idx = "@CasualBot search for Batam news".lower().find("@casualbot")
    text_after_mention = "@CasualBot search for Batam news"[idx + len("@casualbot"):].strip()
    is_search, _ = detect_search_intent(text_after_mention)
    assert is_search is True

def test_detect_search_intent_mid_sentence():
    idx = "Hey @CasualBot search for Batam news".lower().find("@casualbot")
    text_after_mention = "Hey @CasualBot search for Batam news"[idx + len("@casualbot"):].strip()
    is_search, _ = detect_search_intent(text_after_mention)
    assert is_search is True

def test_detect_search_intent_false_positive():
    # Should not trigger on "I saw a search result"
    is_search, _ = detect_search_intent("I saw a search result")
    assert is_search is False

def test_detect_search_intent_false_positive_google():
    is_search, _ = detect_search_intent("Google told me something")
    assert is_search is False

# --- TestRateLimiting (Integration via _handle_group_message) ---
@pytest.mark.asyncio
async def test_rate_limiting_enforcement():
    chat_id = "test_group_1@g.us"
    # Reset cache for test
    _group_search_cooldowns.clear()

    # Mocks
    mock_msg_key = MagicMock()
    mock_profile = {}
    mock_chat_settings = {}
    
    with patch("app.router_webhook.BotIdentityManager.get_bot_number", return_value="12345"), \
         patch("app.router_webhook.is_explicitly_tagged", return_value=False), \
         patch("app.router_webhook.send_text_message", new_callable=AsyncMock) as mock_send_text_message, \
         patch("app.services.deep_crawl_service.DeepCrawlService.search_and_crawl", new_callable=AsyncMock) as mock_search, \
         patch("app.router_webhook.send_long_message", new_callable=AsyncMock):

        # First request should succeed
        await _handle_group_message(
            chat_id, "user1", "Alice", "@CasualBot search for rate limit test", 
            None, mock_msg_key, mock_profile, mock_chat_settings, [], None
        )
        mock_send_text_message.assert_called_once_with(chat_id, "🔍 Searching for: rate limit test...")
        assert chat_id in _group_search_cooldowns

        # Second request within cooldown should fail
        mock_send_text_message.reset_mock()
        await _handle_group_message(
            chat_id, "user2", "Bob", "@CasualBot search for second test", 
            None, mock_msg_key, mock_profile, mock_chat_settings, [], None
        )
        mock_send_text_message.assert_called_once()
        assert "Please wait" in mock_send_text_message.call_args[0][1]

        # Simulate time jump
        _group_search_cooldowns[chat_id] -= 61

        # Third request should succeed
        mock_send_text_message.reset_mock()
        await _handle_group_message(
            chat_id, "user3", "Charlie", "@CasualBot search for third test", 
            None, mock_msg_key, mock_profile, mock_chat_settings, [], None
        )
        mock_send_text_message.assert_called_once_with(chat_id, "🔍 Searching for: third test...")

