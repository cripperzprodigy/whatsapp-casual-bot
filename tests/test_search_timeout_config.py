import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.config import Settings
from app.services.deep_crawl_service import DeepCrawlService

@pytest.mark.asyncio
async def test_search_timeout_defaults_and_wiring():
    # 1. Assert default is exactly 90
    settings = Settings()
    assert getattr(settings, "LLM_SEARCH_TIMEOUT") == 90, "LLM_SEARCH_TIMEOUT must default to 90"

    # 2. Mock HybridSearchService
    mock_search_svc = AsyncMock()
    from app.services.search_service import SearchResult
    mock_search_svc.search.return_value = [SearchResult(url="https://test.com", title="Test", snippet="Test")]

    # 3. Create service
    deep_crawl = DeepCrawlService(search_service=mock_search_svc)

    # 4. Mock ask_llm to verify timeout argument
    with patch("app.services.deep_crawl_service.ask_llm", new_callable=AsyncMock) as mock_ask_llm:
        mock_ask_llm.return_value = "Mocked answer"

        # Execute with explicitly passed 90s timeout (like router_webhook does)
        result = await deep_crawl.search_and_crawl("test query", timeout=90)

        assert "Mocked answer" in result
        
        # 5. Verify the timeout parameter passed to ask_llm matches 90
        mock_ask_llm.assert_called_once()
        _, kwargs = mock_ask_llm.call_args
        assert kwargs.get("timeout") == 90, f"Expected timeout=90, got {kwargs.get('timeout')}"

@pytest.mark.asyncio
async def test_llm_client_kwargs():
    from app.ai_client import ask_llm
    with patch("app.ai_client.llm_client.chat.completions.create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="answer"))])
        
        await ask_llm("test", timeout=90)
        
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs.get("timeout") == 90, "ask_llm must pass timeout to OpenAI client"
