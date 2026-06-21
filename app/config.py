import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ------------------------------------------------------------------ #
    #  Internal WhatsApp Gateway config (Node.js microservice)
    # ------------------------------------------------------------------ #
    WHATSAPP_GATEWAY_URL: str = "http://localhost:3000"

    # ------------------------------------------------------------------ #
    #  Security Whitelist (Comma-separated chat IDs)
    #  Leave empty to allow all chats, e.g. "123@g.us,456@c.us"
    # ------------------------------------------------------------------ #
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
    BOT_NUMBER: str = ""
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
    MAX_INPUT_LENGTH_CHARS: int = 4000

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
    def _parse_and_clamp_input_length(cls, data: dict) -> dict:
        limit_val = data.get("MAX_INPUT_LENGTH_CHARS")
        if limit_val is not None:
            try:
                val = int(limit_val)
                data["MAX_INPUT_LENGTH_CHARS"] = max(500, min(100000, val))
            except (ValueError, TypeError):
                data.pop("MAX_INPUT_LENGTH_CHARS", None)
        return data

    # Issue 5: warn on missing critical fields at startup
    @model_validator(mode="after")
    def _warn_on_missing_critical_fields(self) -> "Settings":
        if not self.BOT_NUMBER:
            logger.warning(
                "BOT_NUMBER is not set. The bot cannot prevent "
                "self-message loops. Set BOT_NUMBER in your .env."
            )
        if not self.LLM_API_KEY:
            logger.warning(
                "LLM_API_KEY is not set. AI features will fail "
                "unless your endpoint does not require authentication."
            )
        return self


settings = Settings()
