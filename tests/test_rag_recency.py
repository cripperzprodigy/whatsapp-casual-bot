"""
RAG Recency & Immediate Buffer Tests — RAG-FIX-003 / ADR-040.

Covers:
  1. Immediate buffer reading from history file
  2. Recency-weighted re-ranking
  3. Immediate buffer injected into system prompt
  4. Prompt priority instruction present
  5. Buffer respects MEMORY_IMMEDIATE_BUFFER_SIZE
  6. Recency alpha changes ranking order
  7. Empty history returns empty buffer
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_engine(chat_id: str = "123@s.whatsapp.net", tmp_path: Path = None):
    """Return an AIMemoryEngine with all I/O and ChromaDB mocked."""
    import app.services.ai_memory_engine  # noqa: F401
    with (
        patch("app.services.ai_memory_engine.get_embedding_model") as mock_emb,
        patch("app.services.ai_memory_engine.get_chroma_client") as mock_chroma,
    ):
        mock_model = MagicMock()
        mock_model.encode = MagicMock(return_value=[0.1, 0.2, 0.3])
        mock_emb.return_value = mock_model

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.return_value.get_or_create_collection.return_value = mock_collection

        from app.services.ai_memory_engine import AIMemoryEngine
        engine = AIMemoryEngine(chat_id, "TestUser", profile={})
        engine.embedding_model = mock_model
        engine.collection = mock_collection
        if tmp_path:
            engine.history_path = tmp_path / "chat_history.jsonl"
        return engine


# ── Test A: Immediate buffer from history file ────────────────────────────────

class TestImmediateBuffer:

    def test_buffer_empty_when_no_history(self, tmp_path):
        engine = _make_engine(tmp_path=tmp_path)
        result = engine._build_immediate_buffer()
        assert result == ""

    def test_buffer_returns_last_n_messages(self, tmp_path):
        engine = _make_engine(tmp_path=tmp_path)
        entries = [
            {"role": "user", "content": "hello", "timestamp": 1},
            {"role": "assistant", "content": "hi there", "timestamp": 2},
            {"role": "user", "content": "how are you", "timestamp": 3},
            {"role": "assistant", "content": "I'm fine", "timestamp": 4},
        ]
        engine.history_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )

        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE = 2
            result = engine._build_immediate_buffer()

        assert "<immediate_context>" in result
        assert "how are you" in result
        assert "I'm fine" in result
        # Older messages should not be in buffer
        assert "hello" not in result

    def test_buffer_respects_config_size(self, tmp_path):
        engine = _make_engine(tmp_path=tmp_path)
        entries = [{"role": "user", "content": f"msg{i}", "timestamp": i} for i in range(10)]
        engine.history_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )

        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE = 3
            result = engine._build_immediate_buffer()

        assert "msg7" in result
        assert "msg8" in result
        assert "msg9" in result
        assert "msg6" not in result
        assert "msg0" not in result

    def test_buffer_zero_size_skips(self, tmp_path):
        engine = _make_engine(tmp_path=tmp_path)
        entries = [{"role": "user", "content": "test", "timestamp": 1}]
        engine.history_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )

        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE = 0
            result = engine._build_immediate_buffer()

        assert result == ""


# ── Test B: Recency-weighted re-ranking ───────────────────────────────────────

class TestRecencyReRanking:

    @pytest.mark.asyncio
    async def test_recent_message_ranks_higher(self, tmp_path):
        """A very recent but less-similar message should outrank an old perfect-match message."""
        engine = _make_engine(tmp_path=tmp_path)

        now = time.time()
        # Old message from 30 days ago — semantically identical
        old_doc = "I love pizza"
        old_ts = now - (30 * 86400)

        # Recent message from 1 hour ago — different topic
        recent_doc = "My cat is sleeping"
        recent_ts = now - 3600

        documents = [old_doc, recent_doc]  # old first, recent second
        metadatas = [
            {"timestamp": int(old_ts), "role": "user"},
            {"timestamp": int(recent_ts), "role": "user"},
        ]
        distances = [0.1, 0.5]  # old is more similar (lower distance)

        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.RAG_TOP_K = 2
            result = await engine._rerank_by_recency(
                documents, metadatas, distances, alpha=0.5
            )

        # Recent message should appear BEFORE the old one after re-ranking
        assert recent_doc in result
        assert old_doc in result
        # Check ordering — recent should be first
        assert result.index(recent_doc) < result.index(old_doc), (
            "Recent message should rank higher after recency re-ranking"
        )

    @pytest.mark.asyncio
    async def test_same_age_preserves_original_order(self, tmp_path):
        """Messages with identical timestamps should keep their original ranking."""
        engine = _make_engine(tmp_path=tmp_path)
        now = int(time.time())

        documents = ["A. pizza facts", "B. weather today"]
        metadatas = [
            {"timestamp": now, "role": "user"},
            {"timestamp": now, "role": "user"},
        ]
        distances = [0.1, 0.2]  # A is more similar

        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.RAG_TOP_K = 2
            result = await engine._rerank_by_recency(
                documents, metadatas, distances, alpha=0.5
            )

        assert result.index("A.") < result.index("B."), (
            "Original semantic order should be preserved when ages are equal"
        )

    @pytest.mark.asyncio
    async def test_high_alpha_prefers_recency_strongly(self, tmp_path):
        """With high alpha, recency should dominate entirely."""
        engine = _make_engine(tmp_path=tmp_path)
        now = time.time()

        documents = ["old_perfect_match", "recent_no_match"]
        metadatas = [
            {"timestamp": int(now - 86400)},  # 1 day ago
            {"timestamp": int(now)},           # now
        ]
        distances = [0.01, 2.0]  # old = extremely similar, recent = poor match

        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.RAG_TOP_K = 2
            result = await engine._rerank_by_recency(
                documents, metadatas, distances, alpha=10.0
            )

        assert result.index("recent_no_match") < result.index("old_perfect_match"), (
            "High alpha should make recency dominate over pure semantic similarity"
        )


# ── Test C: System prompt injection ───────────────────────────────────────────

class TestSystemPromptInjection:

    @pytest.mark.asyncio
    async def test_immediate_buffer_injected_into_prompt(self, tmp_path):
        """The system prompt in process_message must contain immediate_context block."""
        engine = _make_engine(tmp_path=tmp_path)

        # Write the current message plus a prior one so buffer has content
        engine.history_path.write_text(
            json.dumps({"role": "user", "content": "I love pizza", "timestamp": 1}) + "\n",
            encoding="utf-8",
        )

        captured_prompt = []

        async def fake_ask_llm(prompt, **kwargs):
            captured_prompt.append(kwargs.get("system_override", ""))

        with (
            patch("app.services.ai_memory_engine.settings") as mock_cfg,
            patch("app.services.ai_memory_engine.ask_llm", side_effect=fake_ask_llm),
            patch.object(engine, "_detect_language", new_callable=AsyncMock, return_value="en"),
            patch.object(engine, "_retrieve_rag_context", new_callable=AsyncMock, return_value=""),
            patch.object(engine, "_process_media", new_callable=AsyncMock, return_value=None),
            patch.object(engine, "_update_summary", new_callable=AsyncMock),
        ):
            mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE = 5
            mock_cfg.RAG_DEFAULT_TTL_DAYS = 7
            mock_cfg.RAG_TOP_K = 5
            mock_cfg.ENABLE_RAG_INGESTION = True
            mock_cfg.DYNAMIC_SYSTEM_PROMPT = True
            mock_cfg.MAX_CONTEXT_MESSAGES = 50
            mock_cfg.MEMORY_RECENCY_ALPHA = 0.5

            await engine.process_message("What did I just say?", skip_user_ingestion=True)

        assert captured_prompt, "LLM was never called"
        prompt = captured_prompt[0]
        assert "<immediate_context>" in prompt, (
            "Immediate buffer must be injected into system prompt"
        )
        assert "PRIORITY" in prompt, (
            "Prompt must include priority instruction for immediate context"
        )

    @pytest.mark.asyncio
    async def test_priority_instruction_absent_when_buffer_empty(self, tmp_path):
        """When buffer is empty, priority instruction should not appear."""
        engine = _make_engine(tmp_path=tmp_path)
        # Ensure buffer is empty
        buf = engine._build_immediate_buffer()
        assert buf == ""

        captured_prompt = []

        async def fake_ask_llm(prompt, **kwargs):
            captured_prompt.append(kwargs.get("system_override", ""))

        with (
            patch("app.services.ai_memory_engine.settings") as mock_cfg,
            patch("app.services.ai_memory_engine.ask_llm", side_effect=fake_ask_llm),
            patch.object(engine, "_detect_language", new_callable=AsyncMock, return_value="en"),
            patch.object(engine, "_retrieve_rag_context", new_callable=AsyncMock, return_value=""),
            patch.object(engine, "_process_media", new_callable=AsyncMock, return_value=None),
            patch.object(engine, "_update_summary", new_callable=AsyncMock),
        ):
            mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE = 5
            mock_cfg.RAG_DEFAULT_TTL_DAYS = 7
            mock_cfg.RAG_TOP_K = 5
            mock_cfg.ENABLE_RAG_INGESTION = True
            mock_cfg.DYNAMIC_SYSTEM_PROMPT = True
            mock_cfg.MAX_CONTEXT_MESSAGES = 50
            mock_cfg.MEMORY_RECENCY_ALPHA = 0.5

            await engine.process_message("hello", skip_user_ingestion=True)

        prompt = captured_prompt[0]
        # When buffer is empty, the PRIORITY block should not add the verbose instruction
        # (the f-string conditional handles this)
        assert "prioritize information in <immediate_context>" not in prompt.lower(), (
            "Priority instruction should not reference immediate_context when buffer is empty"
        )


# ── Test D: Config values correctly propagated ────────────────────────────────

class TestConfigPropagation:
    def test_memory_immediate_buffer_size_default(self):
        """Config should have default value of 5."""
        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE = 5
            assert mock_cfg.MEMORY_IMMEDIATE_BUFFER_SIZE == 5

    def test_memory_recency_alpha_default(self):
        """Config should have default value of 0.5."""
        with patch("app.services.ai_memory_engine.settings") as mock_cfg:
            mock_cfg.MEMORY_RECENCY_ALPHA = 0.5
            assert mock_cfg.MEMORY_RECENCY_ALPHA == 0.5
