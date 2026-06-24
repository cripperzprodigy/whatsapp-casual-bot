import logging
import time
import os
from pathlib import Path
from filelock import FileLock
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional

logger = logging.getLogger(__name__)

class BotIdentityManager:
    """
    Manages dynamic detection of the bot's own WhatsApp number.
    Prefers runtime detection via the Node.js gateway over the static
    BOT_NUMBER environment variable. Results are cached with a TTL to
    minimise HTTP overhead.
    """
    _cache: str | None = None
    _cache_timestamp: float | None = None

    @classmethod
    def get_bot_number(cls) -> str | None:
        """
        Returns the bot's bare phone number (digits only, no JID suffix).
        Fetches from gateway if cache is expired, falls back to ENV.
        """
        now = time.time()
        
        # We need to defer accessing settings until it's instantiated
        # but we can safely access global settings here since get_bot_number
        # is called at runtime/startup, not at module definition time.
        ttl = getattr(settings, 'BOT_IDENTITY_CACHE_TTL', 300)

        # Return cached value if still fresh
        if (cls._cache is not None
                and cls._cache_timestamp is not None
                and (now - cls._cache_timestamp) < ttl):
            return cls._cache

        # Attempt runtime detection from Node.js gateway
        try:
            import httpx
            gateway_url = getattr(settings, 'WHATSAPP_GATEWAY_URL', None)
            if gateway_url:
                url = f"{gateway_url.rstrip('/')}/whatsapp/bot-identity"
                with httpx.Client(timeout=2.0) as http:
                    resp = http.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        detected = data.get('number')
                        if detected:
                            cls._cache = detected
                            cls._cache_timestamp = now
                            # Warn if ENV value differs from detected
                            env_number = getattr(settings, 'BOT_NUMBER', None)
                            if env_number and env_number != detected:
                                logger.warning(
                                    f"BOT_NUMBER env ({env_number}) differs "
                                    f"from detected JID ({detected}). "
                                    f"Using detected value."
                                )
                            else:
                                logger.info(
                                    f"Bot identity confirmed: {detected}"
                                )
                            return cls._cache
        except Exception as exc:
            logger.warning(
                f"Could not fetch bot identity from gateway: {exc}. "
                f"Falling back to BOT_NUMBER env var."
            )

        # Fallback: use ENV variable
        fallback = getattr(settings, 'BOT_NUMBER', None)
        cls._cache = fallback
        cls._cache_timestamp = now
        if fallback:
            logger.info(f"Using BOT_NUMBER from ENV as fallback: {fallback}")
        else:
            logger.error(
                "BOT_NUMBER is unset and gateway is unreachable. "
                "@mention detection will be disabled."
            )
        return cls._cache

    @classmethod
    def invalidate_cache(cls) -> None:
        """Force the next call to re-fetch from the gateway."""
        cls._cache = None
        cls._cache_timestamp = None
        logger.debug("BotIdentityManager cache invalidated.")

    @classmethod
    def sync_bot_number_to_env(cls) -> bool:
        """
        Fetches current bot identity from gateway.
        Compares with .env BOT_NUMBER value.
        If different, updates .env file atomically (read-modify-write with file lock).
        Logs the change with before/after values.
        Returns True if update was made, False otherwise.
        """
        try:
            import httpx
            gateway_url = getattr(settings, 'WHATSAPP_GATEWAY_URL', None)
            if not gateway_url:
                return False
            url = f"{gateway_url.rstrip('/')}/whatsapp/bot-identity"
            with httpx.Client(timeout=2.0) as http:
                resp = http.get(url)
                if resp.status_code != 200:
                    return False
                data = resp.json()
                detected = data.get('number')
                if not detected:
                    return False

            env_number = getattr(settings, 'BOT_NUMBER', None)
            if detected != env_number:
                logger.info(f"Auto-syncing BOT_NUMBER in .env: {env_number} -> {detected}")
                env_path = Path(".env")
                lock = FileLock(".env.lock")
                with lock:
                    lines = []
                    if env_path.exists():
                        with open(env_path, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                    
                    found = False
                    for i, line in enumerate(lines):
                        if line.startswith("BOT_NUMBER="):
                            lines[i] = f"BOT_NUMBER={detected}\n"
                            found = True
                            break
                    if not found:
                        lines.append(f"\nBOT_NUMBER={detected}\n")
                    
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.writelines(lines)
                return True
            return False
        except Exception as exc:
            logger.error(f"Failed to auto-sync bot number: {exc}")
            return False


class Settings(BaseSettings):
    # ------------------------------------------------------------------ #
    #  Internal WhatsApp Gateway config (Node.js microservice)
    # ------------------------------------------------------------------ #
    WHATSAPP_GATEWAY_URL: str = "http://whatsapp-gateway:3000"

    # ------------------------------------------------------------------ #
    #  Security Whitelist (Comma-separated chat IDs)
    #  Leave empty to allow all chats, e.g. "123@g.us,456@c.us"
    # ------------------------------------------------------------------ #
    ENFORCE_WHITELIST: bool = False
    WHITELISTED_CHATS: str = ""

    # ------------------------------------------------------------------ #
    #  Unified AI Config (OpenAI-compatible)
    # ------------------------------------------------------------------ #
    LLM_ENDPOINT: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    DEFAULT_MODEL_NAME: str = "gpt-3.5-turbo"

    # ------------------------------------------------------------------ #
    #  Database
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "sqlite:///./bot.db"

    # ------------------------------------------------------------------ #
    #  Optional APIs
    # ------------------------------------------------------------------ #
    WEB_SEARCH_API_KEY: Optional[str] = None

    # ------------------------------------------------------------------ #
    #  Internal Bot config
    # ------------------------------------------------------------------ #
    # Issue 5: BOT_NUMBER used to prevent self-loops — warn if empty
    BOT_NUMBER: Optional[str] = None
    AUTO_SYNC_BOT_NUMBER: bool = False
    BOT_IDENTITY_CACHE_TTL: int = 300
    # Bootstrap Owner configured via .env
    BOT_OWNER_ID: Optional[str] = None
    # Issue 2: buffer size, now referenced as a named config value
    MESSAGE_BUFFER_SIZE: int = 200
    AUTO_SYNC_CONTACTS: bool = True

    # ------------------------------------------------------------------ #
    #  Global Translation Settings
    # ------------------------------------------------------------------ #
    GLOBAL_AUTO_TRANSLATE: bool = False
    GLOBAL_TARGET_LANGUAGE: str = "en"
    # Comma-separated list of language codes to ignore globally
    GLOBAL_IGNORED_LANGUAGES: str = ""

    # Auto-Translation Sensitivity
    TRANSLATION_MIN_LENGTH: int = 4
    TRANSLATION_CONFIDENCE_THRESHOLD: float = 0.70
    TRANSLATION_EQUIVALENT_LANGS: str = "id,ms"

    # ------------------------------------------------------------------ #
    #  Issue 8: Rate Limiting
    # ------------------------------------------------------------------ #
    # Max webhook requests per minute per IP (slowapi)
    WEBHOOK_RATE_LIMIT: int = 60

    # ------------------------------------------------------------------ #
    #  Issue 10: Configurable Export Path
    # ------------------------------------------------------------------ #
    CONTACTS_EXPORT_DIR: str = "exports/groups"

    # ------------------------------------------------------------------ #
    #  Issue 14: Named constants replacing magic numbers
    # ------------------------------------------------------------------ #
    SUMMARY_MESSAGE_LIMIT: int = 500
    LLM_MAX_TOKENS: int = 8192
    ROSTER_EXPORT_THROTTLE_SECONDS: int = 60
    MAX_CONTEXT_MESSAGES: int = 50
    TRANSLATION_CHUNK_SIZE: int = 2000
    TRANSLATION_MAX_CHUNKS: int = 5

    # ------------------------------------------------------------------ #
    #  Issue 16: Logging
    # ------------------------------------------------------------------ #
    LOG_LEVEL: str = "INFO"

    # ------------------------------------------------------------------ #
    #  PM Flood Control Defaults
    # ------------------------------------------------------------------ #
    PM_FLOOD_LIMIT: int = 10
    PM_FLOOD_INTERVAL_SECONDS: int = 60

    # ------------------------------------------------------------------ #
    #  Chatty Feature & Persistent Memory (RAG)
    # ------------------------------------------------------------------ #
    CHATTY_DEFAULT: bool = True
    CHATTY_GROUP_DEFAULT: bool = False
    DYNAMIC_SYSTEM_PROMPT: bool = True
    RAG_EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    VISION_ENABLED: bool = True

    # Chatty Frequency Control Defaults
    CHATTY_DEFAULT_FREQUENCY: int = 10
    CHATTY_DEFAULT_BURST: int = 1
    CHATTY_DELAY_MIN: int = 5
    CHATTY_DELAY_MAX: int = 10
    CHATTY_DELAY_MODE: str = "debounce"
    CHATTY_ENABLED_LANGUAGES: str = "en,id,ms"
    DEFAULT_GROUP_LANGUAGE: str = "en"
    DEFAULT_DM_LANGUAGE: str = "en"

    # ------------------------------------------------------------------ #
    #  User Facing Strings
    # ------------------------------------------------------------------ #
    MSG_TRANSLATION_ERROR: str = "[⚠️ Translation service temporarily unavailable]"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8"
    )

    @model_validator(mode="before")
    @classmethod
    def _parse_and_clamp_summary_limit(cls, data: dict) -> dict:
        limit_val = data.get("SUMMARY_MESSAGE_LIMIT")
        if limit_val is not None:
            try:
                val = int(limit_val)
                data["SUMMARY_MESSAGE_LIMIT"] = max(10, min(2000, val))
            except (ValueError, TypeError):
                # Fall back to default silently if invalid
                data.pop("SUMMARY_MESSAGE_LIMIT", None)
        return data

    @model_validator(mode="before")
    @classmethod
    def _parse_and_clamp_llm_tokens(cls, data: dict) -> dict:
        limit_val = data.get("LLM_MAX_TOKENS")
        if limit_val is not None:
            try:
                val = int(limit_val)
                data["LLM_MAX_TOKENS"] = max(512, min(131072, val))
            except (ValueError, TypeError):
                data.pop("LLM_MAX_TOKENS", None)
        return data

    @model_validator(mode="before")
    @classmethod
    def _parse_and_clamp_context_messages(cls, data: dict) -> dict:
        limit_val = data.get("MAX_CONTEXT_MESSAGES")
        if limit_val is not None:
            try:
                val = int(limit_val)
                data["MAX_CONTEXT_MESSAGES"] = max(5, min(1000, val))
            except (ValueError, TypeError):
                data.pop("MAX_CONTEXT_MESSAGES", None)
        return data

    @model_validator(mode="before")
    @classmethod
    def _validate_bot_number(cls, data: dict) -> dict:
        bn = data.get("BOT_NUMBER")
        if not bn or not str(bn).strip():
            return data # Now optional

        bn_str = str(bn).strip()
        # Strip leading + if it exists
        if bn_str.startswith('+'):
            bn_str = bn_str[1:]

        if not bn_str.isdigit():
            raise ValueError("CRITICAL CONFIG ERROR: BOT_NUMBER must be numeric (can start with +). Check .env file.")

        data["BOT_NUMBER"] = bn_str
        return data

    @model_validator(mode="before")
    @classmethod
    def _parse_and_clamp_translation_chunks(cls, data: dict) -> dict:
        limit_val = data.get("TRANSLATION_CHUNK_SIZE")
        if limit_val is not None:
            try:
                val = int(limit_val)
                data["TRANSLATION_CHUNK_SIZE"] = max(500, min(4000, val))
            except (ValueError, TypeError):
                data.pop("TRANSLATION_CHUNK_SIZE", None)

        chunks_val = data.get("TRANSLATION_MAX_CHUNKS")
        if chunks_val is not None:
            try:
                val = int(chunks_val)
                data["TRANSLATION_MAX_CHUNKS"] = max(1, min(20, val))
            except (ValueError, TypeError):
                data.pop("TRANSLATION_MAX_CHUNKS", None)
        return data

    @model_validator(mode="after")
    def _warn_on_missing_critical_fields(self) -> "Settings":
        if not self.LLM_API_KEY:
            logger.warning(
                "LLM_API_KEY is not set. AI features will fail "
                "unless your endpoint does not require authentication."
            )
        return self


settings = Settings()

def safe_reload_settings():
    """
    Re-reads .env file, re-validates all settings, invalidates BotIdentityManager cache.
    """
    global settings
    try:
        settings = Settings()
        BotIdentityManager.invalidate_cache()
        logger.info("Settings reloaded successfully.")
    except Exception as exc:
        logger.error(f"Failed to reload settings: {exc}")
