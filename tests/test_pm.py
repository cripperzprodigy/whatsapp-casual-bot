import pytest
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.state import Base, GlobalSettings, get_global_setting, set_global_setting
from app.pm_service import _send_batch_with_flood_control
from unittest.mock import patch, MagicMock

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_global_settings(db_session):
    assert get_global_setting(db_session, "test_key", "default_val") == "default_val"
    set_global_setting(db_session, "test_key", "new_val")
    assert get_global_setting(db_session, "test_key", "default_val") == "new_val"
    
    # Update existing
    set_global_setting(db_session, "test_key", "updated_val")
    assert get_global_setting(db_session, "test_key", "default_val") == "updated_val"

@pytest.mark.asyncio
async def test_pm_service_batching():
    # Mock the database and settings to avoid real DB calls in background task
    with patch('app.pm_service.SessionLocal') as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        # Limit 2 per batch, 0 second interval for fast tests
        with patch('app.pm_service.get_global_setting', side_effect=lambda db, key, default: "2" if key == "pm_flood_limit" else "0"):
            with patch('app.pm_service.send_text_message', return_value=True) as mock_send:
                
                target_jids = ["1@s", "2@s", "3@s", "4@s", "5@s"]
                
                await _send_batch_with_flood_control("chat1", target_jids, "Hello")
                
                # Should be called 5 times for targets + 1 time for completion msg
                assert mock_send.call_count == 6
                mock_send.assert_any_call("chat1", "✅ Batched PM operation completed. Total attempted: 5.")
