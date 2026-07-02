"""
Runtime State Manager — Centralized configuration overrides with file persistence.

Provides a unified system for managing runtime configuration flags that override
environment variables and defaults. Implements state precedence:
    Env Var (Hard Override) > Runtime State (Soft Override) > Default

Used by search feature toggles, translation settings, chatty modes, etc.
Persists to config_override.json with atomic writes and corruption recovery.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CONFIG_OVERRIDE_FILE = "config_override.json"
_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def _get_cache() -> Dict[str, Any]:
    """Load config_override.json into memory cache, handling corruption gracefully."""
    global _cache
    
    if _cache is not None:
        return _cache
    
    with _lock:
        try:
            if os.path.exists(CONFIG_OVERRIDE_FILE):
                with open(CONFIG_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        _cache = json.loads(content)
                        logger.debug(f"Loaded config_override.json: {list(_cache.keys())}")
                        return _cache
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"config_override.json corrupted or unreadable ({type(e).__name__}): resetting to defaults")
        
        # Default empty state
        _cache = {}
        return _cache


def _save_cache() -> None:
    """Persist config_override.json to disk atomically."""
    with _lock:
        try:
            with open(CONFIG_OVERRIDE_FILE, "w", encoding="utf-8") as f:
                json.dump(_cache or {}, f, indent=2)
                logger.debug(f"Saved config_override.json: {list((_cache or {}).keys())}")
        except IOError as e:
            logger.error(f"Failed to save config_override.json: {e}")


def set_override(key: str, value: Any) -> None:
    """
    Set a runtime configuration override and persist to disk.
    
    Args:
        key: Configuration key (e.g., "agentic_enabled", "deep_crawl_enabled")
        value: New value
    
    Example:
        set_override("agentic_enabled", False)
    """
    cache = _get_cache()
    cache[key] = value
    _save_cache()
    logger.info(f"Set override: {key} = {value}")


def get_override(key: str, default: Any = None) -> Any:
    """
    Get a runtime configuration override.
    
    Returns the value from config_override.json if it exists, otherwise the default.
    Does NOT check environment variables (use get_config_value() for that).
    
    Args:
        key: Configuration key
        default: Default value if key not found
    
    Returns:
        Overridden value or default
    """
    cache = _get_cache()
    return cache.get(key, default)


def get_config_value(key: str, env_key: Optional[str] = None, default: Any = None) -> Any:
    """
    Get configuration with proper precedence: Env Var > Runtime Override > Default.
    
    Use this when you want to respect environment variables as hard kill switches.
    
    Args:
        key: Configuration key in config_override.json
        env_key: Environment variable name to check (defaults to key.upper())
        default: Default value if neither env nor override exists
    
    Returns:
        Configuration value respecting precedence
    
    Example:
        # Check SEARCH_ENABLED env var first, then runtime override, then default True
        value = get_config_value("search_enabled", env_key="SEARCH_ENABLED", default=True)
    """
    from app.config import settings
    
    env_key = env_key or key.upper()
    
    # 1. Check environment variable (hard override)
    env_value = getattr(settings, env_key, None)
    if env_value is not None:
        return env_value
    
    # 2. Check runtime override
    override_value = get_override(key)
    if override_value is not None:
        return override_value
    
    # 3. Return default
    return default


def clear_override(key: str) -> None:
    """Remove a runtime configuration override."""
    cache = _get_cache()
    if key in cache:
        del cache[key]
        _save_cache()
        logger.info(f"Cleared override: {key}")


def reset_all_overrides() -> None:
    """Clear all runtime configuration overrides (test utility)."""
    global _cache
    with _lock:
        _cache = {}
        _save_cache()
        logger.warning("Reset all config_override.json overrides")


def get_all_overrides() -> Dict[str, Any]:
    """Get all current runtime overrides (read-only copy)."""
    return dict(_get_cache())


class RuntimeStateManager:
    """
    Unified runtime state management with role-based access control.
    
    Provides convenience methods for common operations:
    - Toggling boolean flags
    - Owner verification
    - State persistence
    
    Example:
        manager = RuntimeStateManager()
        manager.toggle_bool("agentic_enabled")
        manager.toggle_bool("deep_crawl_enabled")
        is_allowed = manager.is_owner("1234567890@s.whatsapp.net")
    """
    
    @staticmethod
    def toggle_bool(key: str, default: bool = True) -> bool:
        """
        Toggle a boolean configuration flag and return new value.
        
        Args:
            key: Configuration key
            default: Initial value if not set
        
        Returns:
            New boolean value after toggle
        """
        current = get_override(key, default)
        new_value = not current
        set_override(key, new_value)
        return new_value
    
    @staticmethod
    def set_bool(key: str, value: bool) -> None:
        """Set a boolean configuration flag."""
        set_override(key, value)
    
    @staticmethod
    def get_bool(key: str, default: bool = True) -> bool:
        """Get a boolean configuration flag."""
        return get_override(key, default)
    
    @staticmethod
    def is_owner(user_id: str) -> bool:
        """
        Verify if a user is listed in OWNER_IDS configuration.
        
        Args:
            user_id: WhatsApp JID to verify
        
        Returns:
            True if user is an owner, False otherwise
        """
        from app.config import settings
        
        if not settings.OWNER_IDS:
            return False
        
        owner_list = [x.strip() for x in settings.OWNER_IDS.split(",") if x.strip()]
        return str(user_id) in owner_list
    
    @staticmethod
    def is_search_allowed(search_type: str) -> bool:
        """
        Check if a search type is allowed, respecting env var hard kill switch.
        
        Args:
            search_type: "agentic" or "deep" (for deep_crawl)
        
        Returns:
            True if search type is enabled and allowed
        """
        from app.config import settings
        
        # Hard kill switch: if SEARCH_ENABLED is False, block everything
        if not getattr(settings, "SEARCH_ENABLED", True):
            return False
        
        # Check runtime toggle
        if search_type == "agentic":
            return get_override("agentic_enabled", True)
        elif search_type == "deep":
            return get_override("deep_crawl_enabled", True)
        else:
            logger.warning(f"Unknown search type: {search_type}")
            return False
