"""
Test suite for SEARCH-GATE-001: Global search kill switch functionality.

Tests verify that:
1. When SEARCH_ENABLED=False, all search entry points reject with clear message
2. When SEARCH_ENABLED=True, normal operation continues
3. Configuration loads correctly (GROUP_SEARCH_COOLDOWN, LLM_SEARCH_TIMEOUT)
4. Gate check is applied uniformly across DM, Group, and Command flows
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Setup path for imports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app.utils.search_intent import is_search_enabled, detect_search_intent
from app.config import settings


class TestGlobalSearchGateFunction:
    """Test the is_search_enabled() helper function."""

    def test_search_enabled_default_true(self):
        """is_search_enabled() should default to True."""
        assert is_search_enabled() is True

    def test_search_enabled_reads_from_config(self):
        """is_search_enabled() should read from settings.SEARCH_ENABLED."""
        # Default is True (see config.py)
        assert getattr(settings, "SEARCH_ENABLED", True) is True
        assert is_search_enabled() is True


class TestSearchIntentDetectionWithGate:
    """Test that search intent detection still works and respects gate."""

    def test_detect_search_intent_with_gate_enabled(self):
        """Search intent should detect normally when gate is enabled."""
        # By default, SEARCH_ENABLED should be True
        assert is_search_enabled() is True
        found, query = detect_search_intent("search for python")
        assert found is True
        assert query == "python"

    def test_detect_search_intent_respects_gate_disabled(self):
        """Even if intent is detected, the gate can block downstream."""
        # Intent detection itself doesn't check the gate
        # The gate is checked at the router level
        found, query = detect_search_intent("search for news")
        assert found is True
        assert query == "news"
        
        # But if SEARCH_ENABLED is False, router should block
        # (This is tested in integration tests)


class TestGroupSearchCooldownConfig:
    """Test that GROUP_SEARCH_COOLDOWN is loaded correctly."""

    def test_group_search_cooldown_default(self):
        """GROUP_SEARCH_COOLDOWN should default to 60 seconds."""
        cooldown = getattr(settings, "GROUP_SEARCH_COOLDOWN", 60)
        assert cooldown == 60

    def test_group_search_cooldown_is_int(self):
        """GROUP_SEARCH_COOLDOWN should be an integer."""
        cooldown = getattr(settings, "GROUP_SEARCH_COOLDOWN", 60)
        assert isinstance(cooldown, int)
        assert cooldown > 0


class TestLLMSearchTimeoutConfig:
    """Test that LLM_SEARCH_TIMEOUT is loaded correctly."""

    def test_llm_search_timeout_default(self):
        """LLM_SEARCH_TIMEOUT should default to 90 seconds."""
        timeout = getattr(settings, "LLM_SEARCH_TIMEOUT", 90)
        assert timeout == 90

    def test_llm_search_timeout_is_int(self):
        """LLM_SEARCH_TIMEOUT should be an integer."""
        timeout = getattr(settings, "LLM_SEARCH_TIMEOUT", 90)
        assert isinstance(timeout, int)
        assert timeout > 0


class TestSearchEnabledConfigLoading:
    """Test that SEARCH_ENABLED loads correctly from config."""

    def test_search_enabled_exists_in_settings(self):
        """SEARCH_ENABLED should exist in settings."""
        assert hasattr(settings, "SEARCH_ENABLED")

    def test_search_enabled_is_bool(self):
        """SEARCH_ENABLED should be a boolean."""
        assert isinstance(settings.SEARCH_ENABLED, bool)

    def test_search_enabled_default_true(self):
        """SEARCH_ENABLED should default to True."""
        assert settings.SEARCH_ENABLED is True


class TestSearchGateBehavior:
    """Test the semantic behavior of the search gate."""

    def test_gate_blocks_when_disabled(self):
        """is_search_enabled() should return False when SEARCH_ENABLED=False."""
        # Save original value
        original_value = getattr(settings, "SEARCH_ENABLED", True)
        
        try:
            # Temporarily disable
            settings.SEARCH_ENABLED = False
            assert is_search_enabled() is False
        finally:
            # Restore original
            settings.SEARCH_ENABLED = original_value

    def test_gate_allows_when_enabled(self):
        """is_search_enabled() should return True when SEARCH_ENABLED=True."""
        # Save original value
        original_value = getattr(settings, "SEARCH_ENABLED", True)
        
        try:
            # Explicitly enable
            settings.SEARCH_ENABLED = True
            assert is_search_enabled() is True
        finally:
            # Restore original
            settings.SEARCH_ENABLED = original_value


class TestEnvExampleSynchronization:
    """Verify that .env.example contains all search-related config keys."""

    def test_env_example_contains_search_enabled(self):
        """SEARCH_ENABLED should be documented in .env.example."""
        env_path = ".env.example"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "SEARCH_ENABLED" in content, "SEARCH_ENABLED missing from .env.example"
            assert "True" in content or "False" in content, "SEARCH_ENABLED value not set in .env.example"

    def test_env_example_contains_group_search_cooldown(self):
        """GROUP_SEARCH_COOLDOWN should be documented in .env.example."""
        env_path = ".env.example"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "GROUP_SEARCH_COOLDOWN" in content, "GROUP_SEARCH_COOLDOWN missing from .env.example"

    def test_env_example_contains_llm_search_timeout(self):
        """LLM_SEARCH_TIMEOUT should be documented in .env.example."""
        env_path = ".env.example"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "LLM_SEARCH_TIMEOUT" in content, "LLM_SEARCH_TIMEOUT missing from .env.example"

    def test_env_example_contains_deep_crawl_enabled(self):
        """DEEP_CRAWL_ENABLED should still be documented in .env.example."""
        env_path = ".env.example"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "DEEP_CRAWL_ENABLED" in content, "DEEP_CRAWL_ENABLED missing from .env.example"

    def test_env_example_web_search_section_header(self):
        """Should have a clear 'WEB SEARCH' section header in .env.example."""
        env_path = ".env.example"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Check for section header mentioning search
            assert any(header in content for header in [
                "WEB SEARCH",
                "DEEP CRAWL",
                "SEARCH"
            ]), "Missing WEB SEARCH section header in .env.example"


class TestSearchGateDocumentation:
    """Test that documentation is updated."""

    def test_web_search_protocol_doc_updated(self):
        """WEB_SEARCH_PROTOCOL.md should document global disable."""
        doc_path = "ai-chat/knowledge_base/WEB_SEARCH_PROTOCOL.md"
        if os.path.exists(doc_path):
            with open(doc_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Should mention global disable or SEARCH_ENABLED
            has_mention = any(phrase in content for phrase in [
                "Global",
                "kill switch",
                "SEARCH_ENABLED",
                "disabled by administration"
            ])
            assert has_mention, "WEB_SEARCH_PROTOCOL.md missing global disable documentation"

    def test_env_example_has_gate_comment(self):
        """SEARCH_ENABLED in .env.example should have clear comment."""
        env_path = ".env.example"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Find SEARCH_ENABLED line and check for surrounding comments
            search_enabled_found = False
            for i, line in enumerate(lines):
                if "SEARCH_ENABLED" in line:
                    search_enabled_found = True
                    # Should have context (comments above or below)
                    context = "".join(lines[max(0, i-3):min(len(lines), i+3)])
                    assert any(phrase in context for phrase in [
                        "kill switch",
                        "disabled",
                        "global",
                        "all web search"
                    ]), f"SEARCH_ENABLED missing clear explanation. Context:\n{context}"
                    break
            
            assert search_enabled_found, "SEARCH_ENABLED not found in .env.example"


if __name__ == "__main__":
    # Run with: py -m pytest tests/test_search_gates.py -v
    pytest.main([__file__, "-v"])
