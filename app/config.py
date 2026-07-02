import logging
import time
import os
import json
from pathlib import Path
from filelock import FileLock
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, Field
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
    _cache_name: str | None = None
    _cache_timestamp: float | None = None

    @classmethod
    def get_bot_identity(cls) -> dict:
        """Returns the bot's identity dict: {'number': ..., 'name': ...}"""
        cls.get_bot_number() # Ensure cache is warm
        return {
            "number": cls._cache,
            "name": cls._cache_name or ""
        }

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
                            cls._cache_name = data.get('pushname', '')
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
        cls._cache_name = None
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

    # ------------------------------------------------------------------ #
    #  LID Registration & Known Identity Persistence
    # ------------------------------------------------------------------ #
    _known_lids_cache: list[str] | None = None
    KNOWN_LIDS_FILE = "data/bot_known_lids.json"

    @classmethod
    def load_known_bot_ids(cls) -> list[str]:
        """Loads and caches the known LIDs from the persistence file. Creates the file if missing."""
        if cls._known_lids_cache is not None:
            return cls._known_lids_cache

        try:
            os.makedirs(os.path.dirname(cls.KNOWN_LIDS_FILE), exist_ok=True)
            if not os.path.exists(cls.KNOWN_LIDS_FILE):
                # Initialize with empty array so the file exists for future writes
                with open(cls.KNOWN_LIDS_FILE, "w", encoding="utf-8") as f:
                    json.dump([], f)
                logger.info(f"Created empty LID registry: {cls.KNOWN_LIDS_FILE}")
                cls._known_lids_cache = []
                return []
            
            with open(cls.KNOWN_LIDS_FILE, "r", encoding="utf-8") as f:
                cls._known_lids_cache = json.load(f)
        except Exception as exc:
            logger.error(f"Failed to load known bot LIDs: {exc}")
            cls._known_lids_cache = []
            
        return cls._known_lids_cache

    @classmethod
    def register_bot_id(cls, jid: str) -> None:
        """Appends a new JID/LID to the persistence file."""
        known_ids = cls.load_known_bot_ids()
        if jid in known_ids:
            return
            
        known_ids.append(jid)
        cls._known_lids_cache = known_ids
        
        try:
            os.makedirs(os.path.dirname(cls.KNOWN_LIDS_FILE), exist_ok=True)
            lock = FileLock(f"{cls.KNOWN_LIDS_FILE}.lock")
            with lock:
                with open(cls.KNOWN_LIDS_FILE, "w", encoding="utf-8") as f:
                    json.dump(known_ids, f, indent=2)
            logger.info(f"Registered new Bot LID: {jid}")
        except Exception as exc:
            logger.error(f"Failed to save known bot LIDs: {exc}")

    @classmethod
    def clear_bot_ids(cls) -> None:
        """Clears the persisted LIDs."""
        cls._known_lids_cache = []
        try:
            os.makedirs(os.path.dirname(cls.KNOWN_LIDS_FILE), exist_ok=True)
            lock = FileLock(f"{cls.KNOWN_LIDS_FILE}.lock")
            with lock:
                with open(cls.KNOWN_LIDS_FILE, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)
            logger.info("Cleared known Bot LIDs.")
        except Exception as exc:
            logger.error(f"Failed to clear known bot LIDs: {exc}")


class Settings(BaseSettings):
    # ------------------------------------------------------------------ #
    #  Internal WhatsApp Gateway config (Node.js microservice)
    # ------------------------------------------------------------------ #
    WHATSAPP_GATEWAY_URL: str = "http://whatsapp-gateway:3000"
    WHATSAPP_CACHE_MAX_SIZE: int = 5000
    WHATSAPP_CACHE_TTL_SECONDS: int = 300

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
    #  Web Search Timeouts
    # ------------------------------------------------------------------ #
    LLM_SEARCH_TIMEOUT: int = Field(default=45, ge=10)
    CRAWL_CONNECTION_TIMEOUT: int = Field(default=10, ge=1)
    CRAWL_TOTAL_TIMEOUT: int = Field(default=30, ge=1)

    # ------------------------------------------------------------------ #
    #  Database Config
    # ------------------------------------------------------------------ #
    DATABASE_URL: str = "sqlite:///./bot.db"

    # ------------------------------------------------------------------ #
    #  Deep Crawl & Agentic Search Configuration
    # ------------------------------------------------------------------ #
    SEARCH_PROVIDER_MODE: str = "hybrid"  # options: "hybrid", "searxng", "duckduckgo"
    SEARXNG_BASE_URL: Optional[str] = None
    enable_agentic_search: bool = True
    search_max_results: int = Field(default=5, ge=1, le=20)
    search_results_per_query: int = Field(default=10, ge=1, le=50)
    agentic_max_iterations: int = Field(default=3, ge=1, le=10)

    deep_crawl_enabled: bool = True
    deep_crawl_max_urls: int = Field(default=5, ge=1, le=20)
    deep_crawl_timeout_seconds: int = Field(default=10, ge=1)
    crawl_timeout_seconds: float = Field(default=15.0, ge=1.0)
    max_total_context_chars: int = Field(default=15000, ge=1000)
    llm_timeout_seconds: int = Field(default=300, ge=10)

    openrouter_rate_limit_delay: float = Field(default=2.0, ge=0.0)
    fallback_to_snippets: bool = True

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
    # Comma-separated list of language codes to ignore globally.
    # Messages detected as any of these languages will NEVER be translated.
    # Default: EN/ID/MS linguistic sphere — these are treated as a single
    # shared language group in multilingual groups. See ADR-028.
    GLOBAL_IGNORED_LANGUAGES: str = "en,id,ms"

    # Auto-Translation Sensitivity
    TRANSLATION_MIN_LENGTH: int = 4
    TRANSLATION_CONFIDENCE_THRESHOLD: float = 0.70
    # Languages treated as mutually equivalent (no translation between them).
    # Part of the EN/ID/MS linguistic sphere policy (ADR-028).
    TRANSLATION_EQUIVALENT_LANGS: str = "en,id,ms"

    # External keyword file for linguistic sphere detection.
    # One keyword per line, # for comments. See ADR-029.
    TRANSLATION_SKIP_KEYWORDS_FILE: str = "data/translation_skip_keywords.txt"

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

    # ------------------------------------------------------------------ #
    #  RAG (Retrieval-Augmented Generation) Configuration
    # ------------------------------------------------------------------ #
    # Master toggle: set False to disable all ChromaDB writes and retrieval
    ENABLE_RAG_INGESTION: bool = True
    # Number of past messages retrieved from ChromaDB per query
    RAG_TOP_K: int = 5
    # Temporal decay TTL: exclude messages older than N days from standard queries.
    # Set to 0 to disable TTL filtering (retrieve all history).
    # Queries containing historical keywords ("last month", "remember when", etc.)
    # bypass this filter automatically. Configurable via RAG_DEFAULT_TTL_DAYS in .env.
    RAG_DEFAULT_TTL_DAYS: int = 7

    # ── Hybrid Context Configuration (ADR-040) ──────────────────────────────
    # Number of immediate past messages injected into the prompt as raw text
    # (bypasses RAG for short-term conversational continuity).
    MEMORY_IMMEDIATE_BUFFER_SIZE: int = 5
    # Recency decay alpha for RAG re-ranking: final_score = similarity / (1 + alpha * days_since_msg).
    # Higher values make recent messages dominate; lower values favour semantic similarity.
    MEMORY_RECENCY_ALPHA: float = 0.5

    # ── Chatty Web Search Integration (ADR-041) ─────────────────────────────
    # When True, the AI engine may perform automatic web searches when it detects
    # queries needing real-time or factual information, blending results naturally
    # into the reply.  Toggle per-chat via !chatty search on|off.
    CHATTY_SEARCH_DEFAULT: bool = True
    # Max seconds to wait for a natural-language-triggered search to complete.
    # If exceeded, the bot sends a timeout message rather than hanging.
    CHATTY_SEARCH_TIMEOUT_SECONDS: int = 15

    # Chatty Frequency Control Defaults
    CHATTY_DEFAULT_FREQUENCY: int = 10
    CHATTY_DEFAULT_BURST: int = 1
    CHATTY_DELAY_MIN: int = 5
    CHATTY_DELAY_MAX: int = 10
    CHATTY_DELAY_MODE: str = "debounce"
    # Languages supported by the Chatty AI engine for auto-selection.
    # Includes 'zh' for Chinese (Simplified & Traditional) per ADR-039.
    CHATTY_ENABLED_LANGUAGES: str = "en,id,ms,zh"
    DEFAULT_GROUP_LANGUAGE: str = "en"
    DEFAULT_DM_LANGUAGE: str = "en"

    # ------------------------------------------------------------------ #
    #  User Facing Strings
    # ------------------------------------------------------------------ #
    MSG_TRANSLATION_ERROR: str = "[⚠️ Translation service temporarily unavailable]"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="forbid"
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
    def _parse_and_clamp_search_results(cls, data: dict) -> dict:
        def _clamp(key: str, min_val: float, max_val: float, default: float, is_int: bool = True):
            # Check lowercase, then uppercase
            val = data.get(key)
            if val is None:
                val = data.get(key.upper())
            if val is not None:
                try:
                    num = int(val) if is_int else float(val)
                    data[key] = max(min_val, min(max_val, num))
                    if key.upper() in data:
                        data[key.upper()] = data[key]
                except (ValueError, TypeError):
                    data[key] = default

        _clamp("search_max_results", 1, 20, 5)
        _clamp("deep_crawl_max_urls", 1, 20, 5)
        _clamp("llm_timeout_seconds", 10, 1200, 300)
        _clamp("deep_crawl_timeout_seconds", 1, 60, 10)
        _clamp("crawl_timeout_seconds", 1.0, 60.0, 15.0, is_int=False)
        _clamp("max_total_context_chars", 1000, 100000, 15000)
        _clamp("agentic_max_iterations", 1, 10, 3)
        _clamp("search_results_per_query", 1, 50, 10)
        _clamp("openrouter_rate_limit_delay", 0.0, 10.0, 2.0, is_int=False)

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

# ------------------------------------------------------------------ #
#  Global Config Persistence (runtime overrides via !globaltrans)
# ------------------------------------------------------------------ #
GLOBAL_CONFIG_FILE = "data/global_config.json"

def _apply_persisted_global_config() -> None:
    """Applies persisted runtime config overrides from global_config.json."""
    global settings
    try:
        if os.path.exists(GLOBAL_CONFIG_FILE):
            with open(GLOBAL_CONFIG_FILE, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            if "GLOBAL_AUTO_TRANSLATE" in overrides:
                settings.GLOBAL_AUTO_TRANSLATE = overrides["GLOBAL_AUTO_TRANSLATE"]
                logger.info(f"Applied persisted global config: GLOBAL_AUTO_TRANSLATE={settings.GLOBAL_AUTO_TRANSLATE}")
            if "deep_crawl_enabled" in overrides:
                settings.deep_crawl_enabled = overrides["deep_crawl_enabled"]
                logger.info(f"Applied persisted global config: deep_crawl_enabled={settings.deep_crawl_enabled}")
            elif "DEEP_CRAWL_ENABLED" in overrides:
                settings.deep_crawl_enabled = overrides["DEEP_CRAWL_ENABLED"]
                logger.info(f"Applied persisted global config (legacy key): deep_crawl_enabled={settings.deep_crawl_enabled}")
            
            if "enable_agentic_search" in overrides:
                settings.enable_agentic_search = overrides["enable_agentic_search"]
                logger.info(f"Applied persisted global config: enable_agentic_search={settings.enable_agentic_search}")
            elif "ENABLE_AGENTIC_SEARCH" in overrides:
                settings.enable_agentic_search = overrides["ENABLE_AGENTIC_SEARCH"]
                logger.info(f"Applied persisted global config: enable_agentic_search={settings.enable_agentic_search}")
    except Exception as exc:
        logger.error(f"Failed to load persisted global config: {exc}")

def persist_global_config(key: str, value) -> None:
    """Persists a runtime config override to data/global_config.json."""
    try:
        os.makedirs(os.path.dirname(GLOBAL_CONFIG_FILE), exist_ok=True)
        lock = FileLock(f"{GLOBAL_CONFIG_FILE}.lock")
        existing = {}
        with lock:
            if os.path.exists(GLOBAL_CONFIG_FILE):
                with open(GLOBAL_CONFIG_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing[key] = value
            with open(GLOBAL_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
        logger.info(f"Persisted global config: {key}={value}")
    except Exception as exc:
        logger.error(f"Failed to persist global config: {exc}")

# Apply persisted overrides on import
_apply_persisted_global_config()


# ------------------------------------------------------------------ #
#  External Keyword File Loader (Cached)
# ------------------------------------------------------------------ #
_skip_keywords_cache: frozenset[str] | None = None

def load_skip_keywords() -> frozenset[str]:
    """
    Loads and caches the translation skip keywords from the external file.
    Supports comments (#) and blank lines. Returns a frozenset for O(1) lookup.
    """
    global _skip_keywords_cache
    if _skip_keywords_cache is not None:
        return _skip_keywords_cache

    keywords = set()
    filepath = settings.TRANSLATION_SKIP_KEYWORDS_FILE

    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        keywords.add(stripped.lower())
            logger.info(f"Loaded {len(keywords)} skip keywords from {filepath}")
        else:
            logger.warning(f"Skip keywords file not found: {filepath}. Using empty set.")
    except Exception as exc:
        logger.error(f"Failed to load skip keywords from {filepath}: {exc}")

    _skip_keywords_cache = frozenset(keywords)
    return _skip_keywords_cache

def invalidate_skip_keywords_cache() -> None:
    """Forces the next call to reload from disk."""
    global _skip_keywords_cache
    _skip_keywords_cache = None
    logger.debug("Skip keywords cache invalidated.")


def safe_reload_settings():
    """
    Re-reads .env file, re-validates all settings, invalidates BotIdentityManager cache.
    """
    global settings
    try:
        settings = Settings()
        BotIdentityManager.invalidate_cache()
        invalidate_skip_keywords_cache()
        _apply_persisted_global_config()
        logger.info("Settings reloaded successfully.")
    except Exception as exc:
        logger.error(f"Failed to reload settings: {exc}")
