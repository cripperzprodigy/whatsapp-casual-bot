"""
Integration tests for RAG context isolation boundaries.

Proves that the per-chat-id filesystem isolation (separate ChromaDB
PersistentClient directories) and the defense-in-depth `where` clause
filtering prevent any cross-chat context leakage.

Scenarios:
  A: User sends in Group 1, query in Group 2 (same user) → No results
  B: User sends in Group 1, query in DM with Bot → No results
  C: User sends in DM, query in same DM → Results found
  D: User sends in Group 1, query in Group 1 → Results found
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock


# ── helpers ──────────────────────────────────────────────────────────────────


def _create_engine(chat_id: str, tmp_path: Path, sender_name: str = "TestUser"):
    """
    Create an AIMemoryEngine with mocked embedding model and a real
    (temp-directory) ChromaDB PersistentClient for integration testing.
    """
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    safe_id = chat_id.replace("@", "_").replace(".", "_")
    db_path = tmp_path / safe_id / "vector_db"
    db_path.mkdir(parents=True, exist_ok=True)

    mock_model = MagicMock()
    # Produce deterministic embeddings based on content hash for reproducibility
    mock_model.encode = MagicMock(
        side_effect=lambda text: [float(hash(text) % 1000) / 1000.0] * 384
    )

    with (
        patch("app.services.ai_memory_engine.get_embedding_model") as mock_emb,
        patch("app.services.ai_memory_engine.get_chroma_client") as mock_chroma,
    ):
        mock_emb.return_value = mock_model

        # Use a REAL ChromaDB PersistentClient in a temp directory
        real_client = chromadb.PersistentClient(
            path=str(db_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        mock_chroma.return_value = real_client

        from app.services.ai_memory_engine import AIMemoryEngine

        engine = AIMemoryEngine(chat_id, sender_name, profile={})
        engine.embedding_model = mock_model
        engine.history_path = tmp_path / safe_id / "chat_history.jsonl"
        engine.history_path.parent.mkdir(parents=True, exist_ok=True)

    return engine


async def _ingest_text(engine, text: str, sender_id: str = "user1@s.whatsapp.net",
                       message_type: str = "dm"):
    """Helper to ingest a message synchronously (bypassing create_task)."""
    import time, os

    meta = {
        "role": "user",
        "timestamp": int(time.time()),
        "chat_id": engine.chat_id,
        "sender_id": sender_id,
        "type": message_type,
    }
    doc_id = f"msg_{engine.safe_id}_{int(time.time() * 1000)}_{os.urandom(4).hex()}"
    embedding = engine.embedding_model.encode(text)

    engine.collection.add(
        documents=[text],
        embeddings=[embedding],
        metadatas=[meta],
        ids=[doc_id],
    )


async def _retrieve(engine, query_text: str) -> str:
    """Helper to call the engine's retrieval method directly."""
    return await engine._retrieve_rag_context(query_text)


# ── Scenario A: Group 1 → Group 2 (same user) ──────────────────────────────


@pytest.mark.asyncio
async def test_scenario_a_group1_to_group2_no_leakage(tmp_path):
    """
    User sends message in Group 1. Query in Group 2 (same user)
    → Should return NO results (different ChromaDB databases).
    """
    with patch("app.services.ai_memory_engine.settings") as mock_settings:
        mock_settings.ENABLE_RAG_INGESTION = True
        mock_settings.RAG_TOP_K = 5
        mock_settings.RAG_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

        group1_engine = _create_engine("group1@g.us", tmp_path)
        group2_engine = _create_engine("group2@g.us", tmp_path)

        # Ingest into Group 1
        await _ingest_text(
            group1_engine, "The project deadline is next Friday",
            sender_id="user1@s.whatsapp.net", message_type="group"
        )

        # Verify Group 1 has the data
        assert group1_engine.collection.count() == 1

        # Query from Group 2 — must return empty
        result = await _retrieve(group2_engine, "What is the project deadline?")
        assert result == "", (
            f"ISOLATION BREACH: Group 2 retrieved Group 1 data: {result!r}"
        )


# ── Scenario B: Group → DM (same user) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_b_group_to_dm_no_leakage(tmp_path):
    """
    User sends message in Group 1. Query in DM with Bot
    → Should return NO results (group data must not appear in DM).
    """
    with patch("app.services.ai_memory_engine.settings") as mock_settings:
        mock_settings.ENABLE_RAG_INGESTION = True
        mock_settings.RAG_TOP_K = 5
        mock_settings.RAG_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

        group_engine = _create_engine("group1@g.us", tmp_path)
        dm_engine = _create_engine("user1@s.whatsapp.net", tmp_path)

        # Ingest into Group
        await _ingest_text(
            group_engine, "Secret group strategy: flank from the left",
            sender_id="user1@s.whatsapp.net", message_type="group"
        )

        # Verify Group has the data
        assert group_engine.collection.count() == 1

        # Query from DM — must return empty
        result = await _retrieve(dm_engine, "What is the strategy?")
        assert result == "", (
            f"ISOLATION BREACH: DM retrieved Group data: {result!r}"
        )


# ── Scenario C: DM → Same DM ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_c_dm_to_same_dm_returns_results(tmp_path):
    """
    User sends message in DM. Query in same DM
    → Should return the message (same chat context).
    """
    with patch("app.services.ai_memory_engine.settings") as mock_settings:
        mock_settings.ENABLE_RAG_INGESTION = True
        mock_settings.RAG_TOP_K = 5
        mock_settings.RAG_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

        dm_engine = _create_engine("user1@s.whatsapp.net", tmp_path)

        # Ingest into DM
        await _ingest_text(
            dm_engine, "My favorite color is blue",
            sender_id="user1@s.whatsapp.net", message_type="dm"
        )

        # Verify DM has the data
        assert dm_engine.collection.count() == 1

        # Query from same DM — must return the message
        result = await _retrieve(dm_engine, "What is my favorite color?")
        assert result != "", (
            "Same-DM retrieval returned empty — expected the ingested message"
        )
        assert "blue" in result.lower(), (
            f"Same-DM retrieval did not contain expected content: {result!r}"
        )


# ── Scenario D: Group → Same Group ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_d_group_to_same_group_returns_results(tmp_path):
    """
    User sends message in Group 1. Query in Group 1
    → Should return the message (same chat context).
    """
    with patch("app.services.ai_memory_engine.settings") as mock_settings:
        mock_settings.ENABLE_RAG_INGESTION = True
        mock_settings.RAG_TOP_K = 5
        mock_settings.RAG_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

        group_engine = _create_engine("group1@g.us", tmp_path)

        # Ingest into Group
        await _ingest_text(
            group_engine, "Meeting moved to 3pm tomorrow",
            sender_id="user1@s.whatsapp.net", message_type="group"
        )

        # Verify Group has the data
        assert group_engine.collection.count() == 1

        # Query from same Group — must return the message
        result = await _retrieve(group_engine, "When is the meeting?")
        assert result != "", (
            "Same-Group retrieval returned empty — expected the ingested message"
        )
        assert "3pm" in result.lower(), (
            f"Same-Group retrieval did not contain expected content: {result!r}"
        )


# ── Scenario E: Verify where clause is used (defense-in-depth) ──────────────


@pytest.mark.asyncio
async def test_where_clause_includes_chat_id(tmp_path):
    """
    Verify that _retrieve_rag_context() passes a where={\"chat_id\": chat_id}
    filter to ChromaDB, providing defense-in-depth isolation.
    """
    with patch("app.services.ai_memory_engine.settings") as mock_settings:
        mock_settings.ENABLE_RAG_INGESTION = True
        mock_settings.RAG_TOP_K = 5

        with (
            patch("app.services.ai_memory_engine.get_embedding_model") as mock_emb,
            patch("app.services.ai_memory_engine.get_chroma_client") as mock_chroma,
        ):
            mock_model = MagicMock()
            mock_model.encode = MagicMock(return_value=[0.1] * 384)
            mock_emb.return_value = mock_model

            mock_collection = MagicMock()
            mock_collection.count.return_value = 3
            mock_collection.query.return_value = {"documents": [["doc1"]], "metadatas": [[{}]]}
            mock_chroma.return_value.get_or_create_collection.return_value = mock_collection

            from app.services.ai_memory_engine import AIMemoryEngine

            engine = AIMemoryEngine("test_chat@g.us", "TestUser", profile={})
            engine.embedding_model = mock_model
            engine.collection = mock_collection
            engine.history_path = tmp_path / "history.jsonl"

        result = await engine._retrieve_rag_context("test query")

        # Verify that collection.query was called with a where clause
        mock_collection.query.assert_called_once()
        call_kwargs = mock_collection.query.call_args
        # Handle both positional kwargs and keyword-only calls
        if call_kwargs.kwargs:
            where_clause = call_kwargs.kwargs.get("where")
        else:
            where_clause = call_kwargs[1].get("where") if len(call_kwargs) > 1 else None

        assert where_clause is not None, (
            "collection.query() was called WITHOUT a where clause — "
            "defense-in-depth isolation is missing"
        )
        assert where_clause == {"chat_id": "test_chat@g.us"}, (
            f"where clause does not filter by chat_id: {where_clause}"
        )


# ── Scenario F: Filesystem path isolation ────────────────────────────────────


def test_filesystem_isolation_different_chat_types():
    """
    Verify that DM, Group, and different Group chats all produce
    distinct ChromaDB database paths (filesystem-level isolation).
    """
    with (
        patch("app.services.ai_memory_engine.get_embedding_model"),
        patch("app.services.ai_memory_engine.get_chroma_client"),
    ):
        from app.services.ai_memory_engine import AIMemoryEngine

        dm_engine = AIMemoryEngine("user1@s.whatsapp.net", "UserA", profile={})
        group1_engine = AIMemoryEngine("group1@g.us", "UserA", profile={})
        group2_engine = AIMemoryEngine("group2@g.us", "UserA", profile={})

        paths = {
            str(dm_engine.vector_db_path),
            str(group1_engine.vector_db_path),
            str(group2_engine.vector_db_path),
        }
        assert len(paths) == 3, (
            f"Expected 3 distinct vector_db_paths, got {len(paths)}: {paths}"
        )

        # Same user in DM must not share path with any group
        assert dm_engine.vector_db_path != group1_engine.vector_db_path
        assert dm_engine.vector_db_path != group2_engine.vector_db_path
        # Different groups must not share paths
        assert group1_engine.vector_db_path != group2_engine.vector_db_path
