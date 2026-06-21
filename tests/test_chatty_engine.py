import pytest
from unittest.mock import patch, MagicMock
from app.services.ai_memory_engine import AIMemoryEngine
from app.state import ChatSettings

@pytest.mark.asyncio
async def test_detect_language_group():
    with patch("app.state.SessionLocal"), \
         patch("app.state.get_chat_settings") as mock_get_settings, \
         patch("app.services.ai_memory_engine.get_embedding_model"), \
         patch("app.services.ai_memory_engine.get_chroma_client"):

         mock_settings = MagicMock(spec=ChatSettings)
         mock_settings.default_target_language = "fr"
         mock_get_settings.return_value = mock_settings

         engine = AIMemoryEngine("123@g.us", "User")
         lang = await engine._detect_language("Hello")
         assert lang == "fr"

@pytest.mark.asyncio
async def test_detect_language_dm_preferred():
    with patch("app.services.ai_memory_engine.get_embedding_model"), \
         patch("app.services.ai_memory_engine.get_chroma_client"):

         engine = AIMemoryEngine("123@s.whatsapp.net", "User")
         engine.profile["preferred_language"] = "de"

         lang = await engine._detect_language("Hello")
         assert lang == "de"
