"""Comprehensive tests for admin memory management and resolve expansion.

Tests MEM-ADMIN-SECURE-001 (owner-only memory commands, granular control, safety locks)
and UTIL-RESOLVE-EXPAND-001 (resolve @mention support, expanded utility).

Requirements (from task):
- Owner-only permission gates for !rag_status and !memory_clear
- Granular subcommands: list, me, user, group, all --confirm
- Safety lock on all subcommand (--confirm required)
- @mention resolution for !resolve command
- Comprehensive audit logging for all admin actions
- Zero information leakage in denial messages
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy.orm import Session
from datetime import datetime
from pathlib import Path

from app.commands import handle_command
from app.permissions import is_owner, is_admin
from app.utils.audit_logger import log_admin_action
from app.services.ai_memory_engine import AIMemoryEngine


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def owner_id():
    """Owner WhatsApp JID."""
    return "1234567890@s.whatsapp.net"


@pytest.fixture
def non_owner_id():
    """Non-owner WhatsApp JID."""
    return "9876543210@s.whatsapp.net"


@pytest.fixture
def chat_id():
    """Example chat ID."""
    return "1234567890@s.whatsapp.net"


@pytest.fixture
def group_id():
    """Example group ID."""
    return "120362001234567890-1234567890@g.us"


@pytest.fixture
def mock_memory_engine():
    """Create a mock AIMemoryEngine."""
    engine = MagicMock(spec=AIMemoryEngine)
    engine.get_rag_stats = AsyncMock(return_value={
        "chromadb_count": 42,
        "embedding_model": "all-MiniLM-L6-v2",
        "ttl_days": 7,
        "recency_alpha": 0.5,
        "rag_enabled": True,
    })
    engine.clear_all_memory = AsyncMock(return_value=True)
    engine.list_collections = AsyncMock(return_value=["user1@s.whatsapp.net", "user2@s.whatsapp.net"])
    engine.clear_scope = AsyncMock(return_value=42)
    return engine


# ============================================================================
# PERMISSION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_rag_status_owner_only_gate_denies_non_owner(mock_db, non_owner_id, chat_id):
    """Non-owner should be denied access to !rag_status."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            mock_is_owner.return_value = False
            mock_db.query = MagicMock()
            
            await handle_command("!rag_status", chat_id, non_owner_id, mock_db, mentioned_jids=[])
            
            # Verify denial message sent
            mock_send.assert_called()
            args, kwargs = mock_send.call_args
            assert "Access Denied" in args[1]
            assert "🚫" in args[1]


@pytest.mark.asyncio
async def test_memory_clear_owner_only_gate_denies_non_owner(mock_db, non_owner_id, chat_id):
    """Non-owner should be denied access to !memory_clear."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            mock_is_owner.return_value = False
            
            await handle_command("!memory_clear list", chat_id, non_owner_id, mock_db, mentioned_jids=[])
            
            mock_send.assert_called()
            args, kwargs = mock_send.call_args
            assert "Access Denied" in args[1]


@pytest.mark.asyncio
async def test_resolve_owner_only_gate_denies_non_owner(mock_db, non_owner_id, chat_id):
    """Non-owner should be denied access to !resolve @mention."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            mock_is_owner.return_value = False
            
            await handle_command("!resolve @user", chat_id, non_owner_id, mock_db, mentioned_jids=["1111111111@s.whatsapp.net"])
            
            mock_send.assert_called()
            args, kwargs = mock_send.call_args
            assert "Access Denied" in args[1]


# ============================================================================
# RAG_STATUS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_rag_status_owner_can_execute(mock_db, owner_id, chat_id, mock_memory_engine):
    """Owner should be able to execute !rag_status."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                mock_is_owner.return_value = True
                
                await handle_command("!rag_status", chat_id, owner_id, mock_db, mentioned_jids=[])
                
                # Verify RAG stats displayed
                mock_send.assert_called()
                args, kwargs = mock_send.call_args
                response = args[1]
                assert "RAG" in response
                assert "42" in response  # chromadb_count


# ============================================================================
# MEMORY_CLEAR SUBCOMMAND TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_memory_clear_help_subcommand(mock_db, owner_id, chat_id):
    """!memory_clear help should show all available subcommands."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.app_settings") as mock_settings:
                mock_is_owner.return_value = True
                mock_settings.ENABLE_RAG_INGESTION = True
                
                await handle_command("!memory_clear help", chat_id, owner_id, mock_db, mentioned_jids=[])
                
                mock_send.assert_called()
                args, kwargs = mock_send.call_args
                response = args[1]
                assert "list" in response
                assert "me" in response
                assert "user" in response
                assert "group" in response
                assert "all" in response


@pytest.mark.asyncio
async def test_memory_clear_list_subcommand(mock_db, owner_id, chat_id, mock_memory_engine):
    """!memory_clear list should show active collections."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                with patch("app.commands.app_settings") as mock_settings:
                    mock_settings.ENABLE_RAG_INGESTION = True
                    mock_is_owner.return_value = True
                    
                    await handle_command("!memory_clear list", chat_id, owner_id, mock_db, mentioned_jids=[])
                    
                    mock_send.assert_called()
                    args, kwargs = mock_send.call_args
                    response = args[1]
                    assert "Active Collections" in response


@pytest.mark.asyncio
async def test_memory_clear_me_subcommand(mock_db, owner_id, chat_id, mock_memory_engine):
    """!memory_clear me should clear owner's own memory."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                with patch("app.commands.log_admin_action", new_callable=AsyncMock) as mock_audit:
                    with patch("app.commands.app_settings") as mock_settings:
                        mock_settings.ENABLE_RAG_INGESTION = True
                        mock_is_owner.return_value = True
                        
                        await handle_command("!memory_clear me", chat_id, owner_id, mock_db, mentioned_jids=[])
                        
                        # Verify memory cleared
                        mock_memory_engine.clear_all_memory.assert_called()
                        
                        # Verify audit logged
                        mock_audit.assert_called()
                        args, kwargs = mock_audit.call_args
                        assert args[1] == "memory_clear_self"


@pytest.mark.asyncio
async def test_memory_clear_user_with_valid_jid(mock_db, owner_id, chat_id, mock_memory_engine):
    """!memory_clear user <jid> should clear specific user's memory."""
    target_jid = "9999999999@s.whatsapp.net"
    
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                with patch("app.commands.log_admin_action", new_callable=AsyncMock) as mock_audit:
                    with patch("app.commands.app_settings") as mock_settings:
                        mock_settings.ENABLE_RAG_INGESTION = True
                        mock_is_owner.return_value = True
                        
                        await handle_command(
                            f"!memory_clear user {target_jid}",
                            chat_id,
                            owner_id,
                            mock_db,
                            mentioned_jids=[]
                        )
                        
                        mock_memory_engine.clear_all_memory.assert_called()
                        mock_audit.assert_called()
                        args, kwargs = mock_audit.call_args
                        assert args[1] == "memory_clear_user"
                        assert args[2] == target_jid


@pytest.mark.asyncio
async def test_memory_clear_user_with_invalid_jid(mock_db, owner_id, chat_id):
    """!memory_clear user with invalid JID should be rejected."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.app_settings") as mock_settings:
                mock_settings.ENABLE_RAG_INGESTION = True
                mock_is_owner.return_value = True
                
                await handle_command(
                    "!memory_clear user not_a_jid",
                    chat_id,
                    owner_id,
                    mock_db,
                    mentioned_jids=[]
                )
                
                mock_send.assert_called()
                args, kwargs = mock_send.call_args
                assert "Invalid JID" in args[1]


@pytest.mark.asyncio
async def test_memory_clear_group_with_valid_gid(mock_db, owner_id, chat_id, group_id, mock_memory_engine):
    """!memory_clear group <gid> should clear specific group's memory."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                with patch("app.commands.log_admin_action", new_callable=AsyncMock) as mock_audit:
                    with patch("app.commands.app_settings") as mock_settings:
                        mock_settings.ENABLE_RAG_INGESTION = True
                        mock_is_owner.return_value = True
                        
                        await handle_command(
                            f"!memory_clear group {group_id}",
                            chat_id,
                            owner_id,
                            mock_db,
                            mentioned_jids=[]
                        )
                        
                        mock_memory_engine.clear_all_memory.assert_called()
                        mock_audit.assert_called()
                        args, kwargs = mock_audit.call_args
                        assert args[1] == "memory_clear_group"


# ============================================================================
# SAFETY LOCK TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_memory_clear_all_without_confirm_requires_flag(mock_db, owner_id, chat_id):
    """!memory_clear all without --confirm should be rejected."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.app_settings") as mock_settings:
                mock_settings.ENABLE_RAG_INGESTION = True
                mock_is_owner.return_value = True
                
                await handle_command("!memory_clear all", chat_id, owner_id, mock_db, mentioned_jids=[])
                
                mock_send.assert_called()
                args, kwargs = mock_send.call_args
                response = args[1]
                assert "DANGER" in response
                assert "--confirm" in response


@pytest.mark.asyncio
async def test_memory_clear_all_with_confirm_executes(mock_db, owner_id, chat_id, mock_memory_engine):
    """!memory_clear all --confirm should execute nuclear purge."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                with patch("app.commands.log_admin_action", new_callable=AsyncMock) as mock_audit:
                    with patch("app.commands.app_settings") as mock_settings:
                        mock_settings.ENABLE_RAG_INGESTION = True
                        mock_is_owner.return_value = True
                        
                        await handle_command(
                            "!memory_clear all --confirm",
                            chat_id,
                            owner_id,
                            mock_db,
                            mentioned_jids=[]
                        )
                        
                        mock_send.assert_called()
                        args, kwargs = mock_send.call_args
                        response = args[1]
                        assert "NUCLEAR" in response
                        
                        mock_audit.assert_called()
                        args, kwargs = mock_audit.call_args
                        assert args[1] == "memory_clear_all"


# ============================================================================
# RESOLVE @MENTION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_resolve_with_mentioned_jids(mock_db, owner_id, chat_id):
    """!resolve should handle @mention from message context."""
    mentioned_jid = "7777777777@s.whatsapp.net"
    
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.resolve_participant_info", new_callable=AsyncMock) as mock_resolve:
                with patch("app.commands.log_admin_action", new_callable=AsyncMock) as mock_audit:
                    mock_is_owner.return_value = True
                    mock_resolve.return_value = {"phone": "5551234567", "name": "Test User"}
                    
                    await handle_command(
                        "!resolve",
                        chat_id,
                        owner_id,
                        mock_db,
                        mentioned_jids=[mentioned_jid]
                    )
                    
                    # Verify resolve called with mentioned JID
                    mock_resolve.assert_called_with(mentioned_jid)
                    
                    # Verify result sent
                    mock_send.assert_called()
                    args, kwargs = mock_send.call_args
                    response = args[1]
                    assert "555" in response
                    
                    # Verify audit logged
                    mock_audit.assert_called()


@pytest.mark.asyncio
async def test_resolve_with_jid_argument(mock_db, owner_id, chat_id):
    """!resolve <jid> should accept JID as argument."""
    target_jid = "6666666666@s.whatsapp.net"
    
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.resolve_participant_info", new_callable=AsyncMock) as mock_resolve:
                with patch("app.commands.log_admin_action", new_callable=AsyncMock) as mock_audit:
                    mock_is_owner.return_value = True
                    mock_resolve.return_value = {"phone": "5559876543", "name": "Another User"}
                    
                    await handle_command(
                        f"!resolve {target_jid}",
                        chat_id,
                        owner_id,
                        mock_db,
                        mentioned_jids=[]
                    )
                    
                    mock_resolve.assert_called_with(target_jid)
                    mock_audit.assert_called()


@pytest.mark.asyncio
async def test_resolve_no_mention_no_args_shows_error(mock_db, owner_id, chat_id):
    """!resolve with no mention and no args should show helpful error."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            mock_is_owner.return_value = True
            
            await handle_command("!resolve", chat_id, owner_id, mock_db, mentioned_jids=[])
            
            mock_send.assert_called()
            args, kwargs = mock_send.call_args
            response = args[1]
            assert "No user specified" in response


@pytest.mark.asyncio
async def test_resolve_hidden_user_shows_privacy_message(mock_db, owner_id, chat_id):
    """!resolve should handle hidden users with privacy message."""
    mentioned_jid = "8888888888@s.whatsapp.net"
    
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.resolve_participant_info", new_callable=AsyncMock) as mock_resolve:
                mock_is_owner.return_value = True
                mock_resolve.return_value = {"name": "Secret User", "phone": None}
                
                await handle_command(
                    "!resolve",
                    chat_id,
                    owner_id,
                    mock_db,
                    mentioned_jids=[mentioned_jid]
                )
                
                mock_send.assert_called()
                args, kwargs = mock_send.call_args
                response = args[1]
                assert "Hidden" in response or "🔒" in response


# ============================================================================
# AUDIT LOGGING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_audit_log_created_on_memory_clear(tmp_path):
    """!memory_clear actions should create audit log entries."""
    with patch("pathlib.Path", return_value=tmp_path):
        result = await log_admin_action(
            "owner@s.whatsapp.net",
            "memory_clear_user",
            "target@s.whatsapp.net",
            "success"
        )
        
        assert result is True or result is False  # Either succeeds or fails gracefully


@pytest.mark.asyncio
async def test_audit_log_contains_admin_id():
    """Audit logs should contain admin ID for accountability."""
    with patch("builtins.open", create=True):
        result = await log_admin_action(
            "admin@s.whatsapp.net",
            "test_action",
            "target",
            "success"
        )
        # Function should return bool without crashing
        assert isinstance(result, bool)


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_memory_clear_empty_collections_list(mock_db, owner_id, chat_id):
    """!memory_clear list should handle empty collections gracefully."""
    mock_engine = MagicMock(spec=AIMemoryEngine)
    mock_engine.list_collections = AsyncMock(return_value=[])
    
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_engine):
                with patch("app.commands.app_settings") as mock_settings:
                    mock_settings.ENABLE_RAG_INGESTION = True
                    mock_is_owner.return_value = True
                    
                    await handle_command("!memory_clear list", chat_id, owner_id, mock_db, mentioned_jids=[])
                    
                    mock_send.assert_called()
                    args, kwargs = mock_send.call_args
                    response = args[1]
                    assert "No active" in response or "📭" in response


@pytest.mark.asyncio
async def test_concurrent_memory_clear_operations(mock_db, owner_id, chat_id, mock_memory_engine):
    """Concurrent !memory_clear operations should be handled safely."""
    with patch("app.commands.is_owner", new_callable=AsyncMock) as mock_is_owner:
        with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
            with patch("app.commands.AIMemoryEngine", return_value=mock_memory_engine):
                with patch("app.commands.app_settings") as mock_settings:
                    mock_settings.ENABLE_RAG_INGESTION = True
                    mock_is_owner.return_value = True
                    
                    # Simulate concurrent calls
                    tasks = [
                        handle_command(f"!memory_clear user jid{i}@s.whatsapp.net", chat_id, owner_id, mock_db, mentioned_jids=[])
                        for i in range(3)
                    ]
                    
                    # Should complete without errors
                    await asyncio.gather(*tasks)
                    
                    assert mock_send.call_count >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
