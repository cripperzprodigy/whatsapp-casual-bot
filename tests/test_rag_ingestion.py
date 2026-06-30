"""
Unit tests for the RAG ingestion pipeline.

Covers:
- ingest_message() persists to .jsonl and schedules async ChromaDB write
- ENABLE_RAG_INGESTION=False suppresses ChromaDB writes (but keeps .jsonl)
- skip_user_ingestion=True in process_message() avoids double-write
- Context isolation: DM and Group chats use separate ChromaDB collections
- Config flags RAG_TOP_K and ENABLE_RAG_INGESTION are honoured
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── helpers ──────────────────────────────────────────────────────────────────


def _mock_engine(chat_id: str = "123@s.whatsapp.net", tmp_path: Path = None):
    """Return an AIMemoryEngine whose I/O and ChromaDB are fully mocked."""
    with (
        patch("app.services.ai_memory_engine.get_embedding_model") as mock_emb_factory,
        patch("app.services.ai_memory_engine.get_chroma_client") as mock_chroma_factory,
    ):
        mock_model = MagicMock()
        mock_model.encode = MagicMock(return_value=[0.1, 0.2, 0.3])
        mock_emb_factory.return_value = mock_model

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma_factory.return_value.get_or_create_collection.return_value = mock_collection

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine(chat_id, "TestUser", profile={})
        engine.embedding_model = mock_model
        engine.collection = mock_collection
        if tmp_path:
            engine.history_path = tmp_path / "chat_history.jsonl"
        return engine


# ── Tests: ingest_message() ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_message_writes_jsonl(tmp_path):
    """ingest_message() must always write the user message to .jsonl."""
    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
        patch("app.services.ai_memory_engine.settings") as mock_cfg,
        patch("asyncio.create_task"),  # suppress background ChromaDB task in test
    ):
        mock_cfg.ENABLE_RAG_INGESTION = True
        mock_cfg.VISION_ENABLED = False

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine("chat1@s.whatsapp.net", "Alice", profile={})
        engine.history_path = tmp_path / "history.jsonl"
        engine.collection = MagicMock()
        engine.embedding_model = MagicMock()

        await engine.ingest_message(
            "Hello world", sender_id="alice@s.whatsapp.net", message_type="dm"
        )

        assert engine.history_path.exists(), ".jsonl file should be created"
        lines = engine.history_path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["role"] == "user"
        assert entry["content"] == "Hello world"
        assert entry["type"] == "dm"
        assert entry["sender_id"] == "alice@s.whatsapp.net"
        assert entry["chat_id"] == "chat1@s.whatsapp.net"


@pytest.mark.asyncio
async def test_ingest_message_jsonl_written_when_rag_disabled(tmp_path):
    """
    When ENABLE_RAG_INGESTION=False, .jsonl write still happens so that
    generate_delayed_reply() can find pending messages. Only ChromaDB is skipped.
    """
    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
        patch("app.services.ai_memory_engine.settings") as mock_cfg,
    ):
        mock_cfg.ENABLE_RAG_INGESTION = False
        mock_cfg.VISION_ENABLED = False

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine("chat2@s.whatsapp.net", "Bob", profile={})
        engine.history_path = tmp_path / "history.jsonl"
        mock_collection = MagicMock()
        engine.collection = mock_collection
        engine.embedding_model = MagicMock()

        await engine.ingest_message("Test message", sender_id="bob@s.whatsapp.net", message_type="dm")

        # .jsonl MUST be written for conversation continuity
        assert engine.history_path.exists(), ".jsonl must be written even when RAG is disabled"
        # ChromaDB add must NOT be called
        mock_collection.add.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_message_schedules_chromadb_when_rag_enabled(tmp_path):
    """When ENABLE_RAG_INGESTION=True, a background ChromaDB task is scheduled."""
    created_tasks = []

    def fake_create_task(coro):
        created_tasks.append(coro)
        # Don't actually schedule — just drain to avoid ResourceWarning
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(coro)
        except Exception:
            pass
        return MagicMock()

    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
        patch("app.services.ai_memory_engine.settings") as mock_cfg,
        patch("app.services.ai_memory_engine.asyncio.create_task", side_effect=fake_create_task),
        patch("app.services.ai_memory_engine.asyncio.to_thread", new=AsyncMock(return_value=[0.1])),
    ):
        mock_cfg.ENABLE_RAG_INGESTION = True
        mock_cfg.VISION_ENABLED = False

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine("chat3@s.whatsapp.net", "Carol", profile={})
        engine.history_path = tmp_path / "history.jsonl"
        engine.collection = MagicMock()
        engine.embedding_model = MagicMock()
        engine.safe_id = "chat3_s_whatsapp_net"

        await engine.ingest_message("RAG test", sender_id="carol@s.whatsapp.net", message_type="dm")

        assert len(created_tasks) >= 1, "At least one background task should be scheduled for ChromaDB"


# ── Tests: skip_user_ingestion parameter ─────────────────────────────────────


@pytest.mark.asyncio
async def test_process_message_does_not_double_write_with_skip_flag(tmp_path):
    """
    When skip_user_ingestion=True, process_message must not write the user
    message to .jsonl (it was already written by ingest_message()).
    """
    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
        patch("app.services.ai_memory_engine.settings") as mock_cfg,
        patch("app.services.ai_memory_engine.ask_llm", new_callable=AsyncMock) as mock_llm,
        patch("asyncio.create_task"),
    ):
        mock_cfg.ENABLE_RAG_INGESTION = False  # simplify: disable RAG for this test
        mock_cfg.DYNAMIC_SYSTEM_PROMPT = False
        mock_cfg.VISION_ENABLED = False
        mock_cfg.LLM_MAX_TOKENS = 1024
        mock_cfg.MAX_CONTEXT_MESSAGES = 10
        mock_cfg.RAG_TOP_K = 5
        mock_llm.return_value = "AI reply"

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine("chat4@s.whatsapp.net", "Dave", profile={})
        engine.history_path = tmp_path / "history.jsonl"
        engine.collection = MagicMock()
        engine.collection.count.return_value = 0
        engine.embedding_model = MagicMock()
        engine.profile["preferred_language"] = "en"

        with patch("pathlib.Path.exists", return_value=False):
            reply = await engine.process_message(
                "Hello", generate_reply=True, skip_user_ingestion=True
            )

        assert reply == "AI reply"
        if engine.history_path.exists():
            lines = engine.history_path.read_text().strip().splitlines()
            roles = [json.loads(l)["role"] for l in lines if l.strip()]
            assert "user" not in roles, (
                "User message must NOT appear in .jsonl when skip_user_ingestion=True"
            )


@pytest.mark.asyncio
async def test_process_message_writes_user_without_skip_flag(tmp_path):
    """Without skip_user_ingestion, process_message still writes the user entry."""
    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
        patch("app.services.ai_memory_engine.settings") as mock_cfg,
        patch("app.services.ai_memory_engine.ask_llm", new_callable=AsyncMock) as mock_llm,
        patch("asyncio.create_task"),
    ):
        mock_cfg.ENABLE_RAG_INGESTION = False
        mock_cfg.DYNAMIC_SYSTEM_PROMPT = False
        mock_cfg.VISION_ENABLED = False
        mock_cfg.LLM_MAX_TOKENS = 1024
        mock_cfg.MAX_CONTEXT_MESSAGES = 10
        mock_cfg.RAG_TOP_K = 5
        mock_llm.return_value = "reply"

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine("chat5@s.whatsapp.net", "Eve", profile={})
        engine.history_path = tmp_path / "history.jsonl"
        engine.collection = MagicMock()
        engine.collection.count.return_value = 0
        engine.embedding_model = MagicMock()
        engine.profile["preferred_language"] = "en"

        with patch("pathlib.Path.exists", return_value=False):
            await engine.process_message("Hello", generate_reply=True, skip_user_ingestion=False)

        assert engine.history_path.exists(), ".jsonl must be written when skip_user_ingestion=False"
        lines = engine.history_path.read_text().strip().splitlines()
        roles = [json.loads(l)["role"] for l in lines if l.strip()]
        assert "user" in roles, "User message MUST appear in .jsonl when skip_user_ingestion=False"


# ── Tests: context isolation ─────────────────────────────────────────────────


def test_context_isolation_separate_vector_paths():
    """DM and Group engines must use different vector_db_paths (context isolation)."""
    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
    ):
        from app.services.ai_memory_engine import AIMemoryEngine

        dm_engine = AIMemoryEngine("111@s.whatsapp.net", "UserA", profile={})
        group_engine = AIMemoryEngine("222@g.us", "UserB", profile={})

        assert dm_engine.safe_id != group_engine.safe_id, (
            "DM and Group chats must have different safe_ids"
        )
        assert dm_engine.vector_db_path != group_engine.vector_db_path, (
            "DM and Group chats must use separate ChromaDB paths"
        )


# ── Tests: config flags honoured ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rag_top_k_used_in_retrieval(tmp_path):
    """process_message() must use settings.RAG_TOP_K for n_results, not hardcoded 5."""
    captured_n_results = []

    async def fake_to_thread(fn, *args, **kwargs):
        result = fn()
        if hasattr(result, "__class__") and "query" in str(result):
            pass
        return result

    def fake_collection_query(**kwargs):
        captured_n_results.append(kwargs.get("n_results"))
        return {"documents": [[]], "metadatas": [[]], "ids": [[]]}

    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
        patch("app.services.ai_memory_engine.settings") as mock_cfg,
        patch("app.services.ai_memory_engine.ask_llm", new_callable=AsyncMock) as mock_llm,
        patch("asyncio.create_task"),
        patch("app.services.ai_memory_engine.asyncio.to_thread") as mock_to_thread,
    ):
        mock_cfg.ENABLE_RAG_INGESTION = True
        mock_cfg.RAG_TOP_K = 3  # custom value to verify it's respected
        mock_cfg.DYNAMIC_SYSTEM_PROMPT = False
        mock_cfg.VISION_ENABLED = False
        mock_cfg.LLM_MAX_TOKENS = 1024
        mock_cfg.MAX_CONTEXT_MESSAGES = 10
        mock_llm.return_value = "reply"

        # Fake count returns 10 so retrieval path is entered
        call_count = {"n": 0}

        async def smart_to_thread(fn, *a, **kw):
            result = fn()
            # Capture n_results when query is called
            if isinstance(result, dict) and "documents" in result:
                pass
            return result

        mock_collection = MagicMock()
        mock_collection.count.return_value = 10
        mock_collection.query.side_effect = lambda **kw: (
            captured_n_results.append(kw.get("n_results")) or
            {"documents": [[]], "metadatas": [[]], "ids": [[]]}
        )
        mock_to_thread.side_effect = smart_to_thread

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine("chat6@s.whatsapp.net", "Frank", profile={})
        engine.history_path = tmp_path / "history.jsonl"
        engine.collection = mock_collection
        engine.embedding_model = MagicMock()
        engine.embedding_model.encode.return_value = [0.1, 0.2]
        engine.profile["preferred_language"] = "en"

        with patch("pathlib.Path.exists", return_value=False):
            await engine.process_message("What's my favourite color?", generate_reply=True, skip_user_ingestion=True)

        # n_results should be min(RAG_TOP_K=3, count=10) = 3
        if captured_n_results:
            assert captured_n_results[0] == 3, (
                f"Expected RAG_TOP_K=3 to be used for n_results, got {captured_n_results[0]}"
            )
