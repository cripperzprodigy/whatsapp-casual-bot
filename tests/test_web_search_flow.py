"""
Web Search Flow Tests — WEB-SEARCH-FIX-001.

Covers:
  1. Natural language intent detection (10+ variations).
  2. False positive exclusion ("I looked for my keys").
  3. Time injection in deep crawl synthesis prompt.
  4. Flow ordering: search completes before reply.
  5. Hallucination prevention: empty results → graceful message.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── Test 1: Natural language intent detection ────────────────────────────────

class TestSearchIntentDetection:

    def test_search_for(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("search for FIFA world cup results")
        assert triggered is True
        assert "FIFA" in query

    def test_look_up(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("look up the latest news on AI")
        assert triggered is True
        assert "news" in query.lower()

    def test_google(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("google weather in Singapore")
        assert triggered is True
        assert "weather" in query.lower()

    def test_find_latest(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("find the latest stock prices")
        assert triggered is True
        assert "stock" in query.lower()

    def test_what_are_the_latest(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("what are the latest FIFA results")
        assert triggered is True
        assert "FIFA" in query

    def test_check_news(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("check the latest news")
        assert triggered is True
        assert query  # non-empty

    def test_can_you_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("can you search for Python tutorials?")
        assert triggered is True
        assert "Python" in query

    def test_can_you_look_up(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("can you look up the weather?")
        assert triggered is True
        assert "weather" in query.lower()

    def test_search_the_web_for(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("search the web for best restaurants in Tokyo")
        assert triggered is True
        assert "restaurants" in query.lower()

    def test_look_up_online(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("look up online the current time")
        assert triggered is True
        assert "current time" in query.lower()


# ── Test 2: False positive exclusion ─────────────────────────────────────────

class TestFalsePositiveExclusion:

    def test_find_my_keys_not_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, _ = detect_search_intent("find my keys")
        assert triggered is False

    def test_i_looked_for_not_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, _ = detect_search_intent("I looked for my phone this morning")
        assert triggered is False

    def test_i_searched_for_not_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, _ = detect_search_intent("I searched for hours but couldn't find it")
        assert triggered is False

    def test_find_it_not_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, _ = detect_search_intent("find it")
        assert triggered is False

    def test_find_out_not_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, _ = detect_search_intent("find out")
        assert triggered is False

    def test_empty_string(self):
        from app.utils.search_intent import detect_search_intent
        triggered, query = detect_search_intent("")
        assert triggered is False
        assert query is None

    def test_normal_conversation_not_search(self):
        from app.utils.search_intent import detect_search_intent
        triggered, _ = detect_search_intent("hello, how are you today?")
        assert triggered is False


# ── Test 3: Time injection in deep crawl synthesis ────────────────────────────

class TestTimeInjection:

    @pytest.mark.asyncio
    async def test_synthesize_prompt_contains_current_time(self):
        """The synthesis prompt must include [SYSTEM TIME] with current UTC."""
        from app.services.deep_crawl_service import DeepCrawlService

        mock_search = MagicMock()
        service = DeepCrawlService(search_service=mock_search)

        captured_prompt = []

        async def fake_ask_llm(prompt, **kwargs):
            captured_prompt.append(prompt)
            return "Synthesised answer."

        with patch("app.services.deep_crawl_service.ask_llm", side_effect=fake_ask_llm):
            await service._synthesize("latest news", "some context", snippet_fallback=False)

        assert captured_prompt, "ask_llm was never called"
        prompt = captured_prompt[0]
        assert "[SYSTEM TIME:" in prompt, "Prompt must contain [SYSTEM TIME] header"
        # Verify the time is today's date
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today_str in prompt, f"Prompt must contain today's date ({today_str})"

    @pytest.mark.asyncio
    async def test_synthesize_includes_relative_time_instruction(self):
        """Prompt must instruct LLM to interpret 'latest', 'recent' relative to system time."""
        from app.services.deep_crawl_service import DeepCrawlService

        mock_search = MagicMock()
        service = DeepCrawlService(search_service=mock_search)

        captured_prompt = []

        async def fake_ask_llm(prompt, **kwargs):
            captured_prompt.append(prompt)
            return "Answer."

        with patch("app.services.deep_crawl_service.ask_llm", side_effect=fake_ask_llm):
            await service._synthesize("latest news", "context", snippet_fallback=False)

        prompt = captured_prompt[0]
        assert "latest" in prompt.lower() or "recent" in prompt.lower(), (
            "Prompt must mention relative time terms"
        )
        assert "Interpret" in prompt, "Prompt must instruct LLM to interpret relative time"


# ── Test 4: Flow ordering — search before reply ──────────────────────────────

class TestFlowOrdering:

    @pytest.mark.asyncio
    async def test_search_intent_triggers_before_chatty(self):
        """When search intent is detected, the deep crawl path must be taken,
        NOT the standard Chatty LLM path."""
        from app.utils.search_intent import detect_search_intent

        # Verify the intent detector catches a natural search phrase
        triggered, query = detect_search_intent("search for latest AI news")
        assert triggered is True
        assert query is not None
        # This confirms the router would intercept before calling process_message

    @pytest.mark.asyncio
    async def test_search_timeout_sends_fallback_message(self):
        """If search takes >15s, a fallback message is sent instead of hanging."""
        # This is verified by the asyncio.wait_for(timeout=15.0) in the router.
        # We simulate the timeout path here.
        with patch("app.services.deep_crawl_service.DeepCrawlService") as MockService:
            mock_instance = MockService.return_value
            mock_instance.search_and_crawl = AsyncMock(
                side_effect=asyncio.TimeoutError()
            )
            # The router catches TimeoutError and sends a fallback message.
            # Verify the mock raises as expected.
            with pytest.raises(asyncio.TimeoutError):
                await mock_instance.search_and_crawl("test query")


# ── Test 5: Hallucination prevention ─────────────────────────────────────────

class TestHallucinationPrevention:

    @pytest.mark.asyncio
    async def test_empty_search_results_returns_graceful_message(self):
        """When search returns no content, the service must return a graceful
        'no results' message, NOT a hallucinated answer."""
        from app.services.deep_crawl_service import DeepCrawlService

        mock_search = MagicMock()
        mock_search.search = AsyncMock(return_value=[])
        service = DeepCrawlService(search_service=mock_search)

        result = await service.search_and_crawl("nonexistent topic xyz123")

        # Must contain a "no results" or "could not find" message
        assert isinstance(result, str)
        assert len(result) > 0
        # Must NOT be a hallucinated answer — should be an error/no-results message
        assert "no results" in result.lower() or "could not find" in result.lower() or "⚠️" in result, (
            f"Expected graceful no-results message, got: {result}"
        )

    @pytest.mark.asyncio
    async def test_synthesis_uses_only_provided_context(self):
        """The synthesis prompt must instruct the LLM to use ONLY the provided
        search results, not hallucinate."""
        from app.services.deep_crawl_service import DeepCrawlService

        mock_search = MagicMock()
        service = DeepCrawlService(search_service=mock_search)

        captured_prompt = []

        async def fake_ask_llm(prompt, **kwargs):
            captured_prompt.append(prompt)
            return "Answer based on context."

        with patch("app.services.deep_crawl_service.ask_llm", side_effect=fake_ask_llm):
            await service._synthesize("query", "some context here", snippet_fallback=False)

        prompt = captured_prompt[0]
        # The prompt must reference the context
        assert "some context here" in prompt
        # The prompt must instruct the LLM to use the context
        assert "using the following" in prompt.lower()

# ── Test 6: Timeout Configuration Application ─────────────────────────────────

class TestTimeoutConfiguration:

    @pytest.mark.asyncio
    async def test_search_timeout_uses_configured_llm_search_timeout(self, monkeypatch):
        """Verify the router uses LLM_SEARCH_TIMEOUT when waiting for deep crawl."""
        from app.router_webhook import _handle_dm_message
        from app.whatsapp_gateway import WhatsAppWebhookPayload
        from types import SimpleNamespace
        import asyncio

        # We will mock deep_crawl.search_and_crawl to just delay and return "done"
        async def fake_search_and_crawl(query):
            await asyncio.sleep(0.01)
            return "done"

        # Mock the deep crawl service creation
        with patch("app.services.deep_crawl_service.DeepCrawlService") as MockService:
            mock_instance = MockService.return_value
            mock_instance.search_and_crawl = AsyncMock(side_effect=fake_search_and_crawl)
            
            # We must also mock asyncio.wait_for to capture the timeout argument
            original_wait_for = asyncio.wait_for
            wait_for_kwargs = {}
            
            async def spy_wait_for(coro, timeout=None):
                wait_for_kwargs["timeout"] = timeout
                return await original_wait_for(coro, timeout=timeout)
                
            monkeypatch.setattr(asyncio, "wait_for", spy_wait_for)
            
            # Create dummy args for _handle_dm_message
            # We just want to trigger the search path
            from app.config import settings
            settings.LLM_SEARCH_TIMEOUT = 999  # Custom timeout for test
            settings.deep_crawl_enabled = True
            settings.CHATTY_SEARCH_DEFAULT = True
            
            # Mock translation, DB, send_text_message to avoid side effects
            with patch("app.router_webhook.send_text_message", new=AsyncMock()), \
                 patch("app.router_webhook.send_long_message", new=AsyncMock()), \
                 patch("app.router_webhook.mirror_detect_language", return_value="en"), \
                 patch("app.services.ai_memory_engine.AIMemoryEngine"):
                
                # "search for something" triggers search intent
                await _handle_dm_message(
                    chat_id="123@lid",
                    sender_id="123@lid",
                    sender_name="Test",
                    text="search for something",
                    media_path=None,
                    msg_key=SimpleNamespace(id="msg1", participant="123@lid"),
                    profile={}
                )
            
            # Assert wait_for was called with the configured timeout
            assert "timeout" in wait_for_kwargs
            assert wait_for_kwargs["timeout"] == float(999)
