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
    SUMMARY_MESSAGE_LIMIT: int = 30
    LLM_MAX_TOKENS: int = 1024
    ROSTER_EXPORT_THROTTLE_SECONDS: int = 60

    # ------------------------------------------------------------------ #
    #  Issue 16: Logging
    # ------------------------------------------------------------------ #
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8"
    )

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
