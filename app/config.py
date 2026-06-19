from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Internal WhatsApp Gateway config (Node.js microservice)
    WHATSAPP_GATEWAY_URL: str = "http://localhost:3000"
    
    # Security Whitelist (Comma-separated chat IDs)
    # Leave empty to allow all chats, or specify e.g., "123@g.us,456@c.us"
    WHITELISTED_CHATS: str = ""

    # AI Config
    USE_LOCAL_LLM: bool = False
    LOCAL_LLM_ENDPOINT: str = "http://localhost:11434/v1"
    LOCAL_LLM_API_KEY: str = "local-placeholder"
    CLOUD_LLM_ENDPOINT: str = "https://api.openai.com/v1"
    CLOUD_LLM_API_KEY: str = ""
    DEFAULT_MODEL_NAME_LOCAL: str = "llama2"
    DEFAULT_MODEL_NAME_CLOUD: str = "gpt-3.5-turbo"

    # Database
    DATABASE_URL: str = "sqlite:///./bot.db"

    # Optional APIs
    WEB_SEARCH_API_KEY: Optional[str] = None
    
    # Internal Bot config
    BOT_NUMBER: str = "" # Used to prevent self-loops
    MESSAGE_BUFFER_SIZE: int = 200
    AUTO_SYNC_CONTACTS: bool = True
    
    # Global Translation Settings
    GLOBAL_AUTO_TRANSLATE: bool = False
    GLOBAL_TARGET_LANGUAGE: str = "en"
    # Comma-separated list of language codes to ignore globally
    GLOBAL_IGNORED_LANGUAGES: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
