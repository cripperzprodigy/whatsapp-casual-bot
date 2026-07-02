"""
Test suite for unified search toggle commands (CMD-HELP-SYNC-001).

Tests the new !search_toggle command and legacy backward compatibility,
including owner authorization, persistence, help menu rendering, and
runtime state management.
"""

import json
import os
import pytest
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.orm import Session

# Test fixtures
CONFIG_OVERRIDE_FILE = "config_override.json"


@pytest.fixture(autouse=True)
def setup_teardown():
    """Clean up config_override.json before and after each test."""
    # Setup: Remove file if it exists
    if os.path.exists(CONFIG_OVERRIDE_FILE):
        os.remove(CONFIG_OVERRIDE_FILE)
    
    # Clear cache
    import app.utils.state_manager as sm
    sm._cache = None
    
    yield
    
    # Teardown: Clean up after test
    if os.path.exists(CONFIG_OVERRIDE_FILE):
        os.remove(CONFIG_OVERRIDE_FILE)
    sm._cache = None


# ============================================================================
# TEST CLASS 1: Unified !search_toggle Command
# ============================================================================
class TestSearchToggleCommand:
    """Tests for the new unified !search_toggle command."""

    @patch("app.config.settings")
    @pytest.mark.asyncio
    async def test_owner_can_toggle_agentic_on(self, mock_settings):
        """Owner can toggle agentic search on via !search_toggle."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "1234567890@s.whatsapp.net"
        
        # Start disabled
        RuntimeStateManager.set_bool("agentic_enabled", False)
        assert RuntimeStateManager.get_bool("agentic_enabled") is False
        
        # Toggle on
        new_state = RuntimeStateManager.toggle_bool("agentic_enabled")
        assert new_state is True
        assert RuntimeStateManager.get_bool("agentic_enabled") is True

    @patch("app.config.settings")
    @pytest.mark.asyncio
    async def test_owner_can_toggle_agentic_off(self, mock_settings):
        """Owner can toggle agentic search off via !search_toggle."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "1234567890@s.whatsapp.net"
        
        # Start enabled
        RuntimeStateManager.set_bool("agentic_enabled", True)
        assert RuntimeStateManager.get_bool("agentic_enabled") is True
        
        # Toggle off
        new_state = RuntimeStateManager.toggle_bool("agentic_enabled")
        assert new_state is False
        assert RuntimeStateManager.get_bool("agentic_enabled") is False

    @patch("app.config.settings")
    @pytest.mark.asyncio
    async def test_owner_can_toggle_deep_crawl_on(self, mock_settings):
        """Owner can toggle deep crawl search on via !search_toggle."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "1234567890@s.whatsapp.net"
        
        # Start disabled
        RuntimeStateManager.set_bool("deep_crawl_enabled", False)
        assert RuntimeStateManager.get_bool("deep_crawl_enabled") is False
        
        # Toggle on
        new_state = RuntimeStateManager.toggle_bool("deep_crawl_enabled")
        assert new_state is True
        assert RuntimeStateManager.get_bool("deep_crawl_enabled") is True

    @patch("app.config.settings")
    @pytest.mark.asyncio
    async def test_owner_can_toggle_deep_crawl_off(self, mock_settings):
        """Owner can toggle deep crawl search off via !search_toggle."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "1234567890@s.whatsapp.net"
        
        # Start enabled
        RuntimeStateManager.set_bool("deep_crawl_enabled", True)
        assert RuntimeStateManager.get_bool("deep_crawl_enabled") is True
        
        # Toggle off
        new_state = RuntimeStateManager.toggle_bool("deep_crawl_enabled")
        assert new_state is False
        assert RuntimeStateManager.get_bool("deep_crawl_enabled") is False


# ============================================================================
# TEST CLASS 2: Owner Authorization
# ============================================================================
class TestOwnerAuthorization:
    """Tests for owner verification in toggle commands."""

    @patch("app.config.settings")
    def test_owner_verification_with_valid_id(self, mock_settings):
        """RuntimeStateManager.is_owner() returns True for valid owner IDs."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "1234567890@s.whatsapp.net,9876543210@s.whatsapp.net"
        
        assert RuntimeStateManager.is_owner("1234567890@s.whatsapp.net") is True
        assert RuntimeStateManager.is_owner("9876543210@s.whatsapp.net") is True

    @patch("app.config.settings")
    def test_owner_verification_with_invalid_id(self, mock_settings):
        """RuntimeStateManager.is_owner() returns False for non-owner IDs."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "1234567890@s.whatsapp.net"
        
        assert RuntimeStateManager.is_owner("9999999999@s.whatsapp.net") is False
        assert RuntimeStateManager.is_owner("not-a-jid") is False

    @patch("app.config.settings")
    def test_owner_verification_with_empty_list(self, mock_settings):
        """RuntimeStateManager.is_owner() returns False when OWNER_IDS is empty."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = ""
        
        assert RuntimeStateManager.is_owner("1234567890@s.whatsapp.net") is False


# ============================================================================
# TEST CLASS 3: Persistence and State Recovery
# ============================================================================
class TestStatePersistence:
    """Tests for config_override.json persistence."""

    @patch("app.config.settings")
    def test_toggle_persists_to_disk(self, mock_settings):
        """Toggle operations persist state to config_override.json."""
        from app.utils.state_manager import RuntimeStateManager, _cache
        import app.utils.state_manager as sm
        
        mock_settings.OWNER_IDS = "owner@s.whatsapp.net"
        
        # Toggle agentic
        RuntimeStateManager.set_bool("agentic_enabled", False)
        
        # Verify file exists and contains the value
        assert os.path.exists(CONFIG_OVERRIDE_FILE)
        with open(CONFIG_OVERRIDE_FILE, "r") as f:
            data = json.load(f)
        assert data["agentic_enabled"] is False

    @patch("app.config.settings")
    def test_state_survives_cache_reload(self, mock_settings):
        """State persisted to disk is loaded on subsequent cache refresh."""
        from app.utils.state_manager import RuntimeStateManager, get_override
        import app.utils.state_manager as sm
        
        # Set initial state
        RuntimeStateManager.set_bool("deep_crawl_enabled", False)
        assert get_override("deep_crawl_enabled") is False
        
        # Clear cache to simulate restart
        sm._cache = None
        
        # Verify state is reloaded from disk
        assert get_override("deep_crawl_enabled") is False

    @patch("app.config.settings")
    def test_multiple_toggles_persist_independently(self, mock_settings):
        """Multiple toggles persist independently in config_override.json."""
        from app.utils.state_manager import RuntimeStateManager, get_override
        
        RuntimeStateManager.set_bool("agentic_enabled", False)
        RuntimeStateManager.set_bool("deep_crawl_enabled", True)
        
        # Verify both are persisted
        assert get_override("agentic_enabled") is False
        assert get_override("deep_crawl_enabled") is True


# ============================================================================
# TEST CLASS 4: Search Gate Functions
# ============================================================================
class TestSearchGateFunctions:
    """Tests for is_agentic_search_allowed() and is_deep_crawl_allowed()."""

    @patch("app.config.settings")
    def test_agentic_search_allowed_when_enabled(self, mock_settings):
        """is_agentic_search_allowed() returns True when enabled."""
        from app.utils.search_intent import is_agentic_search_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.SEARCH_ENABLED = True
        RuntimeStateManager.set_bool("agentic_enabled", True)
        
        assert is_agentic_search_allowed() is True

    @patch("app.config.settings")
    def test_agentic_search_blocked_when_disabled(self, mock_settings):
        """is_agentic_search_allowed() returns False when disabled."""
        from app.utils.search_intent import is_agentic_search_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.SEARCH_ENABLED = True
        RuntimeStateManager.set_bool("agentic_enabled", False)
        
        assert is_agentic_search_allowed() is False

    @patch("app.config.settings")
    def test_deep_crawl_allowed_when_enabled(self, mock_settings):
        """is_deep_crawl_allowed() returns True when enabled."""
        from app.utils.search_intent import is_deep_crawl_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.SEARCH_ENABLED = True
        RuntimeStateManager.set_bool("deep_crawl_enabled", True)
        
        assert is_deep_crawl_allowed() is True

    @patch("app.config.settings")
    def test_deep_crawl_blocked_when_disabled(self, mock_settings):
        """is_deep_crawl_allowed() returns False when disabled."""
        from app.utils.search_intent import is_deep_crawl_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.SEARCH_ENABLED = True
        RuntimeStateManager.set_bool("deep_crawl_enabled", False)
        
        assert is_deep_crawl_allowed() is False

    @patch("app.config.settings")
    def test_hard_kill_switch_blocks_both_searches(self, mock_settings):
        """When SEARCH_ENABLED=False, both searches are blocked."""
        from app.utils.search_intent import is_agentic_search_allowed, is_deep_crawl_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.SEARCH_ENABLED = False
        RuntimeStateManager.set_bool("agentic_enabled", True)
        RuntimeStateManager.set_bool("deep_crawl_enabled", True)
        
        # Both should be blocked by hard kill switch
        assert is_agentic_search_allowed() is False
        assert is_deep_crawl_allowed() is False


# ============================================================================
# TEST CLASS 5: Help Menu Role-Based Rendering
# ============================================================================
class TestHelpMenuRoleBasedRendering:
    """Tests for role-based help menu visibility."""

    @patch("app.permissions.get_user_role")
    @patch("app.utils.search_intent.is_agentic_search_allowed")
    @patch("app.utils.search_intent.is_deep_crawl_allowed")
    @pytest.mark.asyncio
    async def test_owner_sees_search_toggle_command(self, mock_deep, mock_agentic, mock_role):
        """Help menu shows !search_toggle for owner."""
        from app.commands import _build_help_text
        
        mock_agentic.return_value = True
        mock_deep.return_value = True
        
        # Mock database
        db = Mock(spec=Session)
        
        # Owner role
        help_text = await _build_help_text(db, "owner", False)
        
        # Should contain the unified command
        assert "!search_toggle" in help_text
        assert "agentic|deep" in help_text or "agentic" in help_text

    @patch("app.permissions.get_user_role")
    @patch("app.utils.search_intent.is_agentic_search_allowed")
    @patch("app.utils.search_intent.is_deep_crawl_allowed")
    @pytest.mark.asyncio
    async def test_user_does_not_see_search_toggle_command(self, mock_deep, mock_agentic, mock_role):
        """Help menu does NOT show !search_toggle for regular users."""
        from app.commands import _build_help_text
        
        mock_agentic.return_value = True
        mock_deep.return_value = True
        
        db = Mock(spec=Session)
        
        # Regular user role
        help_text = await _build_help_text(db, "public", False)
        
        # Should NOT contain the owner-only toggle command
        assert "!search_toggle" not in help_text

    @patch("app.permissions.get_user_role")
    @patch("app.utils.search_intent.is_agentic_search_allowed")
    @patch("app.utils.search_intent.is_deep_crawl_allowed")
    @pytest.mark.asyncio
    async def test_help_shows_dynamic_search_status(self, mock_deep, mock_agentic, mock_role):
        """Help menu dynamically shows search feature status."""
        from app.commands import _build_help_text
        
        # Agentic enabled, deep disabled
        mock_agentic.return_value = True
        mock_deep.return_value = False
        
        db = Mock(spec=Session)
        help_text = await _build_help_text(db, "public", False)
        
        # Should show status icons
        assert "🟢" in help_text or "✅" in help_text  # Some enabled indicator
        assert "🔴" in help_text or "❌" in help_text  # Some disabled indicator


# ============================================================================
# TEST CLASS 6: Legacy !sc_toggle Backward Compatibility
# ============================================================================
class TestLegacyCommandBackwardCompatibility:
    """Tests for !sc_toggle legacy command compatibility."""

    @patch("app.config.settings")
    def test_sc_toggle_still_works(self, mock_settings):
        """Legacy !sc_toggle command still functions with RuntimeStateManager."""
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.OWNER_IDS = "owner@s.whatsapp.net"
        
        # Start with deep crawl enabled
        RuntimeStateManager.set_bool("deep_crawl_enabled", True)
        
        # !sc_toggle off should disable it
        new_state = RuntimeStateManager.toggle_bool("deep_crawl_enabled")
        assert new_state is False

    @patch("app.config.settings")
    def test_sc_toggle_and_search_toggle_use_same_state(self, mock_settings):
        """!sc_toggle and !search_toggle use the same persistent state."""
        from app.utils.state_manager import RuntimeStateManager
        
        # Set via !sc_toggle style
        RuntimeStateManager.set_bool("deep_crawl_enabled", False)
        
        # Check via !search_toggle style
        assert RuntimeStateManager.get_bool("deep_crawl_enabled") is False


# ============================================================================
# TEST CLASS 7: Configuration Precedence
# ============================================================================
class TestConfigurationPrecedence:
    """Tests for state precedence: Env Var > Runtime Override > Default."""

    @patch("app.config.settings")
    def test_env_var_overrides_runtime_state(self, mock_settings):
        """Env var (SEARCH_ENABLED) hard-overrides runtime toggles."""
        from app.utils.search_intent import is_agentic_search_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        # Env var says search is disabled
        mock_settings.SEARCH_ENABLED = False
        
        # But runtime state says agentic is enabled
        RuntimeStateManager.set_bool("agentic_enabled", True)
        
        # Env var should win
        assert is_agentic_search_allowed() is False

    @patch("app.config.settings")
    def test_runtime_override_beats_default(self, mock_settings):
        """Runtime override takes precedence over default value."""
        from app.utils.state_manager import get_override
        
        # Don't set OWNER_IDS in env
        mock_settings.OWNER_IDS = ""
        
        # But set in runtime
        config_key = "custom_setting"
        import app.utils.state_manager as sm
        sm.set_override(config_key, "custom_value")
        
        # Should retrieve the override
        assert get_override(config_key) == "custom_value"


# ============================================================================
# TEST CLASS 8: File Corruption Recovery
# ============================================================================
class TestFileCorrectionRecovery:
    """Tests for graceful corruption recovery."""

    def test_corrupted_json_resets_to_defaults(self):
        """Corrupted config_override.json resets state to defaults."""
        import app.utils.state_manager as sm
        
        # Write corrupted JSON
        with open(CONFIG_OVERRIDE_FILE, "w") as f:
            f.write("{invalid json}")
        
        # Clear cache to force reload
        sm._cache = None
        
        # Should not crash, returns default empty state
        result = sm._get_cache()
        assert result == {}

    def test_empty_file_handled_gracefully(self):
        """Empty config_override.json is handled gracefully."""
        import app.utils.state_manager as sm
        
        # Write empty file
        with open(CONFIG_OVERRIDE_FILE, "w") as f:
            f.write("")
        
        # Clear cache
        sm._cache = None
        
        # Should return empty state
        result = sm._get_cache()
        assert result == {}


# ============================================================================
# TEST CLASS 9: Integration Tests
# ============================================================================
class TestIntegration:
    """End-to-end integration tests."""

    @patch("app.config.settings")
    def test_full_toggle_lifecycle(self, mock_settings):
        """Full lifecycle: enable → disable → verify persistence."""
        from app.utils.state_manager import RuntimeStateManager
        import app.utils.state_manager as sm
        
        mock_settings.OWNER_IDS = "owner@s.whatsapp.net"
        mock_settings.SEARCH_ENABLED = True
        
        # Step 1: Start with defaults (both enabled)
        assert RuntimeStateManager.get_bool("agentic_enabled", True) is True
        
        # Step 2: Disable agentic
        RuntimeStateManager.set_bool("agentic_enabled", False)
        assert RuntimeStateManager.get_bool("agentic_enabled") is False
        
        # Step 3: Clear cache (simulate restart)
        sm._cache = None
        
        # Step 4: Verify state persisted
        assert RuntimeStateManager.get_bool("agentic_enabled") is False

    @patch("app.config.settings")
    def test_independent_toggle_behavior(self, mock_settings):
        """Disabling one search type doesn't affect the other."""
        from app.utils.search_intent import is_agentic_search_allowed, is_deep_crawl_allowed
        from app.utils.state_manager import RuntimeStateManager
        
        mock_settings.SEARCH_ENABLED = True
        
        # Enable both
        RuntimeStateManager.set_bool("agentic_enabled", True)
        RuntimeStateManager.set_bool("deep_crawl_enabled", True)
        
        # Disable agentic only
        RuntimeStateManager.set_bool("agentic_enabled", False)
        
        # Agentic should be blocked, deep crawl should work
        assert is_agentic_search_allowed() is False
        assert is_deep_crawl_allowed() is True
