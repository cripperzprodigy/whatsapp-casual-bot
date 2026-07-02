"""
Runtime State Manager for Search Feature Toggles (ADMIN-TOGGLE-002).

⚠️  DEPRECATED: This module is maintained for backward compatibility only.
Use `app.utils.state_manager.RuntimeStateManager` for new code.

Manages persistent toggles for agentic search and deep crawl without requiring
bot restarts. State is stored in .search_state.json at the project root.

The hierarchy is:
1. ENV VAR SEARCH_ENABLED (Hard Kill Switch) — if False, all search is blocked
2. Runtime State (Soft Toggles) — allows independent control of agentic vs deep crawl

NOTE: This module now delegates to RuntimeStateManager internally for consistency.
"""

import json
import os
import threading
from typing import Dict

logger = __import__("logging").getLogger(__name__)

STATE_FILE = ".search_state.json"
_lock = threading.Lock()


def _get_default_state() -> Dict[str, bool]:
    """Return the default state when no state file exists."""
    return {
        "agentic_enabled": True,
        "deep_crawl_enabled": True,
    }


def get_search_state() -> Dict[str, bool]:
    """
    Load the current search state. Delegates to RuntimeStateManager.
    
    Returns
    -------
    Dict[str, bool]
        Dictionary with keys 'agentic_enabled' and 'deep_crawl_enabled'.
        Defaults to all-enabled if file is missing or corrupted.
    """
    from app.utils.state_manager import RuntimeStateManager
    
    defaults = _get_default_state()
    agentic = RuntimeStateManager.get_bool("agentic_enabled", defaults["agentic_enabled"])
    deep_crawl = RuntimeStateManager.get_bool("deep_crawl_enabled", defaults["deep_crawl_enabled"])
    
    return {
        "agentic_enabled": agentic,
        "deep_crawl_enabled": deep_crawl,
    }


def save_search_state(state: Dict[str, bool]) -> None:
    """
    Save the search state. Delegates to RuntimeStateManager.
    
    Parameters
    ----------
    state : Dict[str, bool]
        Dictionary with 'agentic_enabled' and 'deep_crawl_enabled' keys.
    """
    from app.utils.state_manager import RuntimeStateManager
    
    if "agentic_enabled" in state:
        RuntimeStateManager.set_bool("agentic_enabled", state["agentic_enabled"])
    if "deep_crawl_enabled" in state:
        RuntimeStateManager.set_bool("deep_crawl_enabled", state["deep_crawl_enabled"])
    
    logger.info(f"Persisted search state via RuntimeStateManager: {state}")


def toggle_agentic() -> bool:
    """
    Toggle agentic search on/off and persist the change. Delegates to RuntimeStateManager.
    
    Returns
    -------
    bool
        New state of agentic search (True = enabled, False = disabled).
    """
    from app.utils.state_manager import RuntimeStateManager
    
    new_value = RuntimeStateManager.toggle_bool("agentic_enabled")
    logger.info(f"Toggled agentic search to {new_value}")
    return new_value


def toggle_deep_crawl() -> bool:
    """
    Toggle deep crawl on/off and persist the change. Delegates to RuntimeStateManager.
    
    Returns
    -------
    bool
        New state of deep crawl (True = enabled, False = disabled).
    """
    from app.utils.state_manager import RuntimeStateManager
    
    new_value = RuntimeStateManager.toggle_bool("deep_crawl_enabled")
    logger.info(f"Toggled deep crawl to {new_value}")
    return new_value


def is_agentic_enabled() -> bool:
    """
    Check if agentic search is enabled in runtime state. Delegates to RuntimeStateManager.
    
    Returns
    -------
    bool
        True if agentic search is enabled, False otherwise.
    """
    from app.utils.state_manager import RuntimeStateManager
    
    return RuntimeStateManager.get_bool("agentic_enabled", True)


def is_deep_crawl_enabled() -> bool:
    """
    Check if deep crawl is enabled in runtime state. Delegates to RuntimeStateManager.
    
    Returns
    -------
    bool
        True if deep crawl is enabled, False otherwise.
    """
    from app.utils.state_manager import RuntimeStateManager
    
    return RuntimeStateManager.get_bool("deep_crawl_enabled", True)


def reset_to_defaults() -> None:
    """Reset state file to all-enabled defaults. Delegates to RuntimeStateManager. Useful for testing."""
    from app.utils.state_manager import RuntimeStateManager
    import app.utils.state_manager as sm
    
    RuntimeStateManager.set_bool("agentic_enabled", True)
    RuntimeStateManager.set_bool("deep_crawl_enabled", True)
    sm._cache = None  # Clear cache for tests
    
    logger.info("Reset search state to defaults (all enabled) via RuntimeStateManager.")
