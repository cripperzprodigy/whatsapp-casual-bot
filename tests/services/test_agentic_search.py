import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from app.services.agentic_search_service import AgenticSearchOrchestrator
from app.services.search_service import HybridSearchService

@pytest.fixture
def mock_search_service():
    service = Mock(spec=HybridSearchService)
    service.search = AsyncMock()
    return service

@pytest.mark.asyncio
async def test_agentic_search_loop_breaks_early(mock_search_service):
    class DummyResult:
        def __init__(self, title, snippet, url):
            self.title = title
            self.snippet = snippet
            self.url = url

    # Return some results
    mock_search_service.search.return_value = [DummyResult("A", "B", "C")]

    orchestrator = AgenticSearchOrchestrator(mock_search_service)

    with patch("app.services.agentic_search_service.ask_llm", new_callable=AsyncMock) as mock_ask_llm:
        # First LLM call is gap analysis, returning sufficient
        # Second LLM call is synthesis
        mock_ask_llm.side_effect = [
            '{"sufficient": true, "missing_info": "", "refined_query": ""}',
            "Final synthesized answer"
        ]

        result = await orchestrator.execute_iterative_search("test query", "user_1")

        # Ensure search was called only once
        assert mock_search_service.search.call_count == 1
        assert result == "Final synthesized answer"

@pytest.mark.asyncio
async def test_agentic_search_second_iteration(mock_search_service):
    class DummyResult:
        def __init__(self, title, snippet, url):
            self.title = title
            self.snippet = snippet
            self.url = url

    mock_search_service.search.return_value = [DummyResult("A", "B", "C")]

    orchestrator = AgenticSearchOrchestrator(mock_search_service)

    with patch("app.services.agentic_search_service.ask_llm", new_callable=AsyncMock) as mock_ask_llm:
        # First LLM call is gap analysis, returning insufficient
        # Second LLM call is synthesis (since max_iterations = 2)
        mock_ask_llm.side_effect = [
            '{"sufficient": false, "missing_info": "need X", "refined_query": "search X"}',
            "Final synthesized answer with more context"
        ]

        result = await orchestrator.execute_iterative_search("test query", "user_1")

        # Ensure search was called twice
        assert mock_search_service.search.call_count == 2

        # Verify the second search query was the refined one
        assert mock_search_service.search.call_args_list[1][0][0] == "search X"
        assert result == "Final synthesized answer with more context"

@pytest.mark.asyncio
async def test_agentic_search_identical_query_break(mock_search_service):
    class DummyResult:
        def __init__(self, title, snippet, url):
            self.title = title
            self.snippet = snippet
            self.url = url

    mock_search_service.search.return_value = [DummyResult("A", "B", "C")]

    orchestrator = AgenticSearchOrchestrator(mock_search_service)

    with patch("app.services.agentic_search_service.ask_llm", new_callable=AsyncMock) as mock_ask_llm:
        # First LLM call gap analysis returns insufficient but same query
        # Second LLM call is synthesis
        mock_ask_llm.side_effect = [
            '{"sufficient": false, "missing_info": "need X", "refined_query": "test query"}',
            "Final synthesized answer after breaking loop"
        ]

        result = await orchestrator.execute_iterative_search("test query", "user_1")

        # Ensure search was called ONCE because it broke the loop on identical query
        assert mock_search_service.search.call_count == 1
        assert result == "Final synthesized answer after breaking loop"

@pytest.mark.asyncio
async def test_agentic_search_gap_analysis_failure(mock_search_service):
    class DummyResult:
        def __init__(self, title, snippet, url):
            self.title = title
            self.snippet = snippet
            self.url = url

    mock_search_service.search.return_value = [DummyResult("A", "B", "C")]

    orchestrator = AgenticSearchOrchestrator(mock_search_service)

    with patch("app.services.agentic_search_service.ask_llm", new_callable=AsyncMock) as mock_ask_llm:
        # Simulate LLM failure during gap analysis
        mock_ask_llm.side_effect = [
            Exception("LLM Rate limit"),
            "Fallback synthesized answer"
        ]

        result = await orchestrator.execute_iterative_search("test query", "user_1")

        # Should catch exception, break loop, and synthesize
        assert mock_search_service.search.call_count == 1
        assert result == "Fallback synthesized answer"
        # Verify that we passed reasoning_failed=True context to synthesizer system prompt
        assert "Advanced reasoning step failed" in mock_ask_llm.call_args_list[1][1]['system_override']
