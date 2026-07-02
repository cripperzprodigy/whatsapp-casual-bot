import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from zoneinfo import ZoneInfo
from datetime import datetime

from filelock import FileLock
import httpx


from langdetect import detect, DetectorFactory
DetectorFactory.seed = 0
from langdetect.lang_detect_exception import LangDetectException
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
import pdfplumber

from app.config import settings

# Since AIMemoryEngine interacts with ai_client.py, we might have to import it
from app.services.profile_service import read_profile, write_profile
from app.ai_client import ask_llm
# Language mirroring helpers (ADR-039)
from app.utils.lang_detect import (
    detect_language as mirror_detect_language,
    build_language_enforcement_block,
    SUPPORTED_LANGS as MIRROR_SUPPORTED_LANGS,
)

logger = logging.getLogger(__name__)


# ── Module-level helpers ────────────────────────────────────────────────────

# Keywords that signal the user is asking about historical context, which
# bypasses the RAG TTL filter so old messages are still retrieved (Task 6).
_HISTORICAL_QUERY_KEYWORDS = frozenset({
    "last month", "last year", "last week", "last time",
    "remember when", "a while ago", "previously", "before", "earlier",
    "yesterday", "do you remember", "we talked about", "you mentioned",
    "you said", "i told you", "we discussed",
})


def _is_historical_query(text: str) -> bool:
    """Return True if *text* implies searching historical context (bypass TTL)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _HISTORICAL_QUERY_KEYWORDS)

# Keywords that indicate the user wants real-time / searchable information.
# When CHATTY_SEARCH_DEFAULT=True, these trigger auto web search integration.
_SEARCH_TRIGGER_KEYWORDS: frozenset[str] = frozenset({
    "latest", "news", "weather", "stock", "price", "today's", "this week",
    "current", "breaking", "recent", "just happened", "just announced",
    "what time", "what day", "what date", "who won", "who is winning",
    "score", "election", "update", "announcement", "search the web",
    "look up", "find out", "google", "check online",
})


def _should_trigger_search(text: str) -> bool:
    """Return True if the user's message warrants an automatic web search."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _SEARCH_TRIGGER_KEYWORDS)


_global_embedding_model = None
_chroma_clients = {}

def get_embedding_model():
    global _global_embedding_model
    if _global_embedding_model is None:
        model_name = settings.RAG_EMBEDDING_MODEL
        try:
            logger.info(f"Loading embedding model: {model_name} (this may take a moment on first run)")
            _global_embedding_model = SentenceTransformer(model_name)
            logger.info(f"Embedding model '{model_name}' loaded successfully.")
        except Exception as e:
            logger.warning(f"Failed to load embedding model {model_name}. Fallback to all-MiniLM-L3-v2. Error: {e}")
            _global_embedding_model = SentenceTransformer('all-MiniLM-L3-v2')
    return _global_embedding_model

# Eagerly preload the embedding model at import time to prevent blocking
# the asyncio event loop on the first message. This is critical because
# SentenceTransformer.__init__ is a synchronous blocking call that can
# take 10-60 seconds to download and load the neural network weights.
try:
    get_embedding_model()
except Exception as e:
    logger.error(f"Failed to preload embedding model at startup: {e}")

def get_chroma_client(db_path: str):
    if db_path not in _chroma_clients:
        _chroma_clients[db_path] = chromadb.PersistentClient(
            path=db_path,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    return _chroma_clients[db_path]

class AIMemoryEngine:
    def __init__(self, chat_id: str, sender_name: str, profile: dict = None):
        self.chat_id = chat_id
        self.sender_name = sender_name
        self.safe_id = chat_id.replace('@', '_').replace('.', '_')
        self.user_dir = Path(f"./data/contacts/{self.safe_id}")
        self.user_dir.mkdir(parents=True, exist_ok=True)

        self.profile_path = self.user_dir / "profile.json"
        self.history_path = self.user_dir / "chat_history.jsonl"
        self.vector_db_path = self.user_dir / "vector_db"
        self.vector_db_path.mkdir(parents=True, exist_ok=True)

        self.profile = profile if profile else self._load_profile()

        self.embedding_model = get_embedding_model()
        self.chroma_client = get_chroma_client(str(self.vector_db_path))
        self.collection = self.chroma_client.get_or_create_collection("user_memory")


    def _load_profile(self) -> Dict[str, Any]:
        profile = read_profile(self.chat_id)
        if profile.get("name") != self.sender_name:
            profile["name"] = self.sender_name
        return profile

    def _save_profile(self):
        write_profile(self.chat_id, self.profile)

    async def _detect_language(self, text: str) -> str:
        """Detect the user's language and return a supported ISO 639-1 code.

        ADR-039 (Language Mirroring): Uses the centralised ``mirror_detect_language``
        function from ``app/utils/lang_detect.py`` which normalises Chinese variants,
        handles Malay/Indonesian false-positives, and caps confidence-based
        code-switching noise.

        Fallback chain:
          1. New fast-path: ``mirror_detect_language()`` (LRU-cached, <20 ms).
          2. Profile ``preferred_language`` override (DMs only) — user-set preference.
          3. LLM-based detection (last resort if both above fail).
          4. Configured default language for the domain.
        """
        # ── DM: honour explicit user-set language preference first ──────────
        if "@g.us" not in self.chat_id:
            if self.profile.get("preferred_language"):
                return self.profile["preferred_language"]

        # ── Fast-path: synchronous LRU-cached detection ──────────────────────
        # mirror_detect_language handles: Chinese variants, MS/ID false-positives,
        # code-switching, short text, and unsupported-language fallback.
        try:
            detected = mirror_detect_language(text, fallback="")
            if detected:
                # Persist detected language into DM profile for session continuity
                if "@g.us" not in self.chat_id:
                    self.profile["lang_pref"] = detected
                    self.profile["name"] = self.sender_name
                    self._save_profile()
                logger.debug(
                    f"[LangMirror] chat={self.chat_id} detected='{detected}' "
                    f"supported={detected in MIRROR_SUPPORTED_LANGS}"
                )
                return detected
        except Exception as e:
            logger.warning(f"[LangMirror] mirror_detect_language failed: {e}")

        # ── Group fallback: group-configured default language ─────────────────
        if "@g.us" in self.chat_id:
            from app.state import get_chat_settings, SessionLocal
            with SessionLocal() as db:
                chat_settings = get_chat_settings(db, self.chat_id)
                group_default = (
                    chat_settings.default_target_language
                    if chat_settings.default_target_language
                    else getattr(settings, "DEFAULT_GROUP_LANGUAGE", "en")
                )

            # LLM-based detection as last resort for groups
            try:
                from app.translation import detect_language as llm_detect
                llm_lang = await llm_detect(text)
                if llm_lang:
                    return llm_lang
            except Exception as e:
                logger.warning(f"[LangMirror] Group LLM fallback failed: {e}")

            return group_default

        # ── DM final fallback ─────────────────────────────────────────────────
        try:
            from app.translation import detect_language as llm_detect
            llm_lang = await llm_detect(text)
            if llm_lang:
                return llm_lang
        except Exception as e:
            logger.warning(f"[LangMirror] DM LLM fallback failed: {e}")

        return getattr(settings, "DEFAULT_DM_LANGUAGE", "en")

    async def _process_media(self, media_path: str) -> Optional[str]:
        if not settings.VISION_ENABLED or not media_path:
            return None

        ext = media_path.split('.')[-1].lower()
        if ext in ['png', 'jpg', 'jpeg', 'webp']:
            # Call vision LLM to describe image
            # Note: app.ai_client.ask_llm doesn't support vision directly yet,
            # this will require updating ai_client.py. For now, we will add a vision flag.
            try:
                description = await ask_llm(
                    prompt="Describe this image in detail.",
                    task_type="vision",
                    image_path=media_path
                )
                return f"[Image uploaded by user: {description}]"
            except httpx.HTTPError as e:
                logger.error(f"Vision API error: {e}")
            except Exception as e:
                logger.error(f"Vision unexpected error: {e}")
                return "[Image uploaded by user, but failed to analyze]"

        elif ext == 'pdf':
            try:
                text = ""
                with pdfplumber.open(media_path) as pdf:
                    for page in pdf.pages[:3]: # limit to 3 pages for speed
                        text += page.extract_text() + "\n"
                return f"[PDF uploaded by user. Contents: {text[:1000]}]"
            except (IOError, ValueError) as e:
                logger.error(f"PDF extraction error: {e}")
                return "[PDF uploaded by user, but failed to read]"

        return f"[Unsupported media uploaded: {media_path}]"

    def _embed_text(self, text: str) -> List[float]:
        """Synchronous embedding — use asyncio.to_thread() when calling from async context."""
        return self.embedding_model.encode(text).tolist()

    def _append_history(self, role: str, content: str, extra_meta: dict = None):
        """
        Write to .jsonl synchronously (required for generate_delayed_reply).
        Schedule async ChromaDB write when ENABLE_RAG_INGESTION=True.
        """
        ts = int(time.time())
        entry = {"role": role, "content": content, "timestamp": ts}
        if extra_meta:
            entry.update(extra_meta)
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Non-blocking ChromaDB write, guarded by feature flag
        if settings.ENABLE_RAG_INGESTION and content.strip():
            ttl_days = getattr(settings, 'RAG_DEFAULT_TTL_DAYS', 7)
            meta = {
                "role": role,
                "timestamp": ts,
                "chat_id": self.chat_id,
                # Task 6: store expiry and initial weight for temporal decay
                "expires_at": ts + (ttl_days * 86400) if ttl_days > 0 else 0,
                "weight": 1.0,
            }
            if extra_meta:
                meta.update({k: v for k, v in extra_meta.items() if k != "content"})
            try:
                asyncio.create_task(self._rag_ingest_async(content, meta))
            except RuntimeError:
                # No running event loop (e.g., sync test context) — skip silently
                pass

    def _read_recent_messages_snapshot(self) -> Tuple[List[Dict], float]:
        """Capture the current recent-message window from the history file.

        Returns ``(messages, snapshot_timestamp)`` where ``snapshot_timestamp``
        is ``time.time()`` at the moment of reading.  Both values are passed to
        ``_update_summary()`` so that summary generation and RAG retrieval operate
        on the same temporal context for every request (Task 1 — Snapshot Context).
        """
        snapshot_timestamp = time.time()
        messages: List[Dict] = []
        if not self.history_path.exists():
            return messages, snapshot_timestamp
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-settings.MAX_CONTEXT_MESSAGES:]:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except (IOError, OSError) as e:
            logger.warning(
                f"[Snapshot] Failed to read history for {self.chat_id}: {e}"
            )
        return messages, snapshot_timestamp

    async def _rag_ingest_async(self, content: str, meta: dict) -> None:
        """Async ChromaDB write executed in thread pool to avoid blocking the event loop."""
        try:
            doc_id = f"msg_{self.safe_id}_{int(time.time() * 1000)}_{os.urandom(4).hex()}"
            embedding = await asyncio.to_thread(
                lambda: self.embedding_model.encode(content).tolist()
            )
            await asyncio.to_thread(
                lambda: self.collection.add(
                    documents=[content],
                    embeddings=[embedding],
                    metadatas=[meta],
                    ids=[doc_id]
                )
            )
        except Exception as e:
            logger.error(f"[RAG] Async ingest error for {self.chat_id}: {e}")

    async def _retrieve_rag_context(self, query_text: str) -> str:
        """
        Retrieve relevant past messages from ChromaDB for the current chat.

        Defense-in-depth: Although each chat_id already has its own isolated
        ChromaDB PersistentClient (filesystem-level isolation), we additionally
        filter by chat_id in the where clause. This guards against future
        architectural changes (e.g., collection consolidation) accidentally
        breaking isolation boundaries.

        Temporal Decay (Task 6): By default, messages older than
        ``RAG_DEFAULT_TTL_DAYS`` are excluded from retrieval.  Queries that
        contain historical keywords (e.g. "last month", "remember when") bypass
        the TTL filter so the user can still ask about older context explicitly.
        """
        if not settings.ENABLE_RAG_INGESTION:
            return ""
        try:
            count = await asyncio.to_thread(lambda: self.collection.count())
            if count == 0:
                return ""
            query_embedding = await asyncio.to_thread(
                lambda: self.embedding_model.encode(query_text).tolist()
            )
            n_results = min(settings.RAG_TOP_K, count)

            # Build TTL-aware where clause
            ttl_days = getattr(settings, 'RAG_DEFAULT_TTL_DAYS', 7)
            use_ttl = ttl_days > 0 and not _is_historical_query(query_text)
            if use_ttl:
                cutoff_ts = int(time.time()) - (ttl_days * 86400)
                where_clause = {
                    "$and": [
                        {"chat_id": {"$eq": self.chat_id}},
                        {"timestamp": {"$gte": cutoff_ts}},
                    ]
                }
                logger.debug(
                    f"[RAG TTL] chat={self.chat_id}, cutoff={cutoff_ts}, "
                    f"ttl_days={ttl_days}"
                )
            else:
                where_clause = {"chat_id": self.chat_id}

            try:
                results = await asyncio.to_thread(
                    lambda: self.collection.query(
                        query_embeddings=[query_embedding],
                        n_results=n_results,
                        where=where_clause,
                    )
                )
            except Exception as ttl_err:
                # TTL filter may raise if filtered count < n_results in older
                # ChromaDB versions.  Fall back to unfiltered query.
                logger.debug(
                    f"[RAG TTL] Filtered query failed for {self.chat_id}: {ttl_err}. "
                    f"Falling back to chat_id-only filter."
                )
                results = await asyncio.to_thread(
                    lambda: self.collection.query(
                        query_embeddings=[query_embedding],
                        n_results=n_results,
                        where={"chat_id": self.chat_id},
                    )
                )

            if results["documents"] and results["documents"][0]:
                # ── ADR-040: Recency-weighted re-ranking ──────────────────────
                # Fetch more candidates than needed, then apply a time-decay
                # multiplier so that recent messages rank higher than semantically
                # similar but older messages.
                alpha = getattr(settings, 'MEMORY_RECENCY_ALPHA', 0.5)
                return await self._rerank_by_recency(
                    results["documents"][0],
                    results["metadatas"][0] if results.get("metadatas") else [],
                    results["distances"][0] if results.get("distances") else [],
                    alpha,
                )
        except ValueError as e:
            logger.error(f"RAG retrieval error for {self.chat_id}: {e}")
        except Exception as e:
            logger.error(f"RAG retrieval unexpected error for {self.chat_id}: {e}")
        return ""

    async def _rerank_by_recency(
        self,
        documents: list,
        metadatas: list,
        distances: list,
        alpha: float = 0.5,
    ) -> str:
        """Re-rank retrieved documents using temporal decay.

        final_score = similarity_score / (1 + alpha * days_since_message)

        This ensures that a slightly less relevant but **much more recent**
        message ranks above a perfectly relevant but **stale** message.
        """
        if not documents:
            return ""
        now = time.time()
        scored = []
        for i, doc in enumerate(documents):
            # Convert ChromaDB distance to similarity (lower distance = more similar)
            dist = distances[i] if i < len(distances) else 0.0
            similarity = 1.0 / (1.0 + dist)

            # Extract timestamp from metadata
            meta = metadatas[i] if i < len(metadatas) else {}
            ts = meta.get("timestamp", now)
            age_days = (now - ts) / 86400.0

            decay = 1.0 / (1.0 + alpha * age_days)
            final = similarity * decay
            scored.append((final, doc))

            logger.debug(
                f"[RAG Rank] doc_ts={ts}, age_days={age_days:.1f}, "
                f"sim={similarity:.4f}, decay={decay:.4f}, final={final:.4f}"
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        top_k = min(settings.RAG_TOP_K, len(scored))
        return "\n".join(doc for _, doc in scored[:top_k])

    def _build_immediate_buffer(self) -> str:
        """Return the last N messages as a formatted immediate-context block.

        ADR-040: This buffer bypasses RAG entirely for short-term conversational
        continuity.  The raw last-N messages are injected into the system prompt
        as ``<immediate_context>...</immediate_context>`` so the LLM has direct
        access to the most recent exchange without relying on vector search.
        """
        buf_size = getattr(settings, 'MEMORY_IMMEDIATE_BUFFER_SIZE', 5)
        if buf_size <= 0 or not self.history_path.exists():
            return ""

        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (IOError, OSError):
            return ""

        recent = []
        for line in lines[-buf_size:]:
            try:
                entry = json.loads(line)
                role = entry.get("role", "unknown")
                content = entry.get("content", "").strip()
                if content:
                    prefix = "User" if role == "user" else "Assistant"
                    recent.append(f"{prefix}: {content}")
            except json.JSONDecodeError:
                pass

        if not recent:
            return ""

        joined = "\n".join(recent)
        logger.debug(
            f"[ImmediateBuffer] chat={self.chat_id}, "
            f"lines={len(recent)}, chars={len(joined)}"
        )
        return f"<immediate_context>\n{joined}\n</immediate_context>"

    def _build_time_context(self) -> str:
        """Return a [CURRENT TIME] section with Asia/Singapore time.

        ADR-041: Always-on time awareness ensures the LLM can answer temporal
        questions ("what day is it?", "what time?") without hallucinating dates.
        Falls back to UTC+8 offset when tzdata is not installed (Windows).
        """
        try:
            tz = ZoneInfo("Asia/Singapore")
            now = datetime.now(tz)
            label = now.strftime("%A, %Y-%m-%d %H:%M:%S %Z")
        except Exception:
            from datetime import timezone as dt_timezone, timedelta
            tz = dt_timezone(timedelta(hours=8))
            now = datetime.now(tz)
            label = now.strftime("%A, %Y-%m-%d %H:%M:%S UTC+8")
        return (
            f"[CURRENT TIME]\n"
            f"{label}\n"
            f"Use this for all temporal questions. The user is likely in Singapore (UTC+8)."
        )

    def _build_search_tools_section(self, user_text: str) -> str:
        """Return a [TOOLS] section when search integration should be active.

        ADR-041: When CHATTY_SEARCH_DEFAULT is True and the user's text matches
        search-trigger keywords, we inform the LLM that it may blend web search
        results naturally into the reply.
        """
        search_enabled = getattr(settings, 'CHATTY_SEARCH_DEFAULT', True)
        if not search_enabled:
            return ""
        if not _should_trigger_search(user_text):
            return ""
        return (
            "[TOOLS]\n"
            "You have access to web search for real-time information. "
            "When presenting facts, use a natural conversational tone such as: "
            "\"I checked recent sources and...\" or \"Based on current information, ...\". "
            "Blend search results smoothly into your reply without raw formatting."
        )

    async def ingest_message(
        self,
        text: str,
        media_path: Optional[str] = None,
        sender_id: str = "unknown",
        message_type: str = "dm",
    ) -> None:
        """
        Fire-and-forget ingestion entry point. Call via asyncio.create_task().

        Always persists message to the .jsonl conversation history so that
        generate_delayed_reply() can find pending messages regardless of the
        ENABLE_RAG_INGESTION flag. ChromaDB vector write is guarded by that flag.

        Context isolation: chat_id scopes all data to this chat only — DM messages
        never appear in a group's ChromaDB collection and vice versa.
        """
        media_desc = await self._process_media(media_path)
        full_text = text
        if media_desc:
            full_text += f"\n\n{media_desc}"

        extra_meta: dict = {
            "sender_id": sender_id,
            "type": message_type,
            "chat_id": self.chat_id,
        }
        # _append_history writes .jsonl unconditionally;
        # the ChromaDB task is only scheduled when ENABLE_RAG_INGESTION=True.
        self._append_history("user", full_text, extra_meta=extra_meta)
        logger.debug(
            f"[RAG Ingest] chat={self.chat_id}, type={message_type}, "
            f"sender={sender_id}, text_len={len(full_text)}, "
            f"rag_enabled={settings.ENABLE_RAG_INGESTION}"
        )

    async def _update_summary(
        self,
        snapshot_messages: Optional[List[Dict]] = None,
        context_timestamp: Optional[float] = None,
    ):
        """Generate and persist a conversation summary.

        Task 1 — Snapshot Context: When *snapshot_messages* is provided it MUST
        be the same message window that was read at the start of the current
        request (before any new messages were appended).  This guarantees that the
        summary and the RAG retrieval operate on the exact same temporal slice of
        history, eliminating context drift between the two subsystems.

        If *context_timestamp* is also provided, a consistency check is performed:
        if the last message in the snapshot is more than 30 seconds older than
        context_timestamp, a ``[CONTEXT DRIFT]`` warning is logged.
        """
        if not settings.DYNAMIC_SYSTEM_PROMPT:
            return

        if not self.history_path.exists():
            return

        with open(self.history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Only summarize every 5 messages (based on total history length)
        if len(lines) % 5 != 0:
            return

        if snapshot_messages is not None:
            # Use provided snapshot — aligned with the same request window as RAG
            messages_to_summarize = snapshot_messages

            # Consistency check: warn on significant temporal drift (Task 1)
            if context_timestamp is not None and snapshot_messages:
                last_msg_ts = max(
                    (m.get("timestamp", 0) for m in snapshot_messages), default=0
                )
                drift = abs(context_timestamp - last_msg_ts) if last_msg_ts else 0
                if drift > 30:
                    logger.warning(
                        f"[CONTEXT DRIFT] Summary and RAG context timestamps diverge "
                        f"by {drift:.1f}s for chat={self.chat_id}. "
                        f"snapshot_ts={last_msg_ts}, context_ts={context_timestamp:.0f}. "
                        f"This may indicate concurrent message arrival during processing."
                    )
            logger.debug(
                f"[SNAPSHOT CONTEXT] Summary using aligned snapshot: "
                f"{len(messages_to_summarize)} msgs, context_ts="
                f"{f'{context_timestamp:.0f}' if context_timestamp else 'N/A'}"
            )
        else:
            # Fallback: re-read from file (backward compatibility for standalone calls)
            messages_to_summarize = []
            for line in lines[-settings.MAX_CONTEXT_MESSAGES:]:
                try:
                    messages_to_summarize.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        if not messages_to_summarize:
            return

        recent = "".join([
            m.get("role", "unknown") + ": " + m.get("content", "") + "\n"
            for m in messages_to_summarize
        ])

        summary_prompt = f"""You are an expert conversation analyst. Analyze the provided chat history between a user and an assistant.
Generate a concise "Memory State" JSON object containing:
1. "user_profile": Key facts about the user (name, location, job, preferences mentioned).
2. "current_context": What is currently being discussed? (1 sentence).
3. "pending_tasks": Any open questions or tasks the assistant promised to do.
4. "tone_style": The emotional tone or slang style the user uses (e.g., "formal", "gen-z slang", "angry").

Input Chat History:
{recent}

Output ONLY valid JSON."""

        try:
            summary = await ask_llm(summary_prompt, task_type="json")
            self.profile["conversation_summary"] = summary
            self._save_profile()
        except httpx.HTTPError as e:
            logger.error(f"Failed to update summary (HTTP error): {e}")
        except Exception as e:
            logger.error(f"Failed to update summary: {e}")

    async def process_message(self, text: str, media_path: Optional[str] = None, is_burst: bool = False, generate_reply: bool = True, context_type: str | None = None, context_text: str | None = None, skip_user_ingestion: bool = False) -> Optional[str]:
        # 1. Process Language
        lang = await self._detect_language(text)

        # 2. Process Media
        media_desc = await self._process_media(media_path)
        full_text = text
        if media_desc:
            full_text += f"\n\n{media_desc}"

        # 3. Save to history & RAG (skip when ingest_message() was already called)
        if not is_burst and not skip_user_ingestion:
            self._append_history("user", full_text)

        if not generate_reply:
            return None

        # 3a. Snapshot context for aligned summary generation (Task 1).
        #     Taken AFTER the user message is appended so the snapshot includes
        #     it, ensuring summary and RAG operate on the exact same window.
        snapshot_messages, context_timestamp = self._read_recent_messages_snapshot()

        # 4. Retrieve RAG Context (async, non-blocking; guarded by ENABLE_RAG_INGESTION)
        retrieved_context = await self._retrieve_rag_context(full_text)

        # 5. Build System Prompt
        base_prompt_path = Path("./data/system_prompts/default.txt")
        base_prompt = "You are a helpful assistant."
        if base_prompt_path.exists():
            with open(base_prompt_path, "r", encoding="utf-8") as f:
                base_prompt = f.read()

        custom_instructions = self.profile.get("system_prompt") or "None"
        summary = self.profile.get("conversation_summary") or "{}"

        # ADR-039: Language enforcement block placed ABOVE RAG context so the
        # language constraint takes priority over any English-language retrieved
        # documents that could otherwise cause language drift.
        lang_enforcement = build_language_enforcement_block(lang)

        # ADR-040: Immediate buffer — inject last N messages as raw text so the
        # LLM has direct access to short-term conversational continuity without
        # relying on RAG retrieval (which can fetch stale semantically-similar content).
        immediate_buffer = self._build_immediate_buffer()

        context_section = retrieved_context if retrieved_context else "No relevant past memories found."
        system_prompt = f"""[Global Instructions]
{base_prompt}

[User Profile]
Name: {self.profile.get('name', 'Unknown')}
Preferred Language: {lang}
Custom Instructions: {custom_instructions}

{lang_enforcement}

{self._build_time_context()}

{immediate_buffer}

[CONTEXT MEMORY]
The following relevant past conversations have been retrieved:
{context_section}

INSTRUCTION: Use this context to maintain continuity. If the user refers to
previous topics, use the information above to answer accurately.
If the context is irrelevant, ignore it.
If the context is in a different language, translate relevant facts to {lang} before responding.

PRIORITY: For questions about recent events, prioritize information in
<immediate_context> over [CONTEXT MEMORY]. {immediate_buffer and 'The <immediate_context> block contains the most recent exchange — trust it over older RAG results when the user asks about something that just happened.' or ''}

{self._build_search_tools_section(full_text)}

[Recent Context Summary]
{summary}

[Constraint]
Reply ONLY in {lang}. Be natural, human-like, and concise."""

        final_user_prompt = full_text
        if context_text:
            final_user_prompt = f"{context_text} \"{full_text}\""
            logger.debug(f"Injected context: {context_text}")

        # 6. Call LLM
        # For Chatty, we just pass the system prompt and the current full_text
        # We don't need to pass chat history again because RAG + Summary covers it
        try:
            ai_reply = await ask_llm(final_user_prompt, task_type="generic", system_override=system_prompt)

            # 7. Append AI reply to history
            self._append_history("assistant", ai_reply)

            # 8. Trigger background summary using the snapshot captured before the
            #    LLM call — ensures summary aligns with the same message window
            #    as the RAG retrieval for this request (Task 1).
            await self._update_summary(
                snapshot_messages=snapshot_messages,
                context_timestamp=context_timestamp,
            )

            return ai_reply
        except httpx.HTTPError as e:
            logger.error(f"LLM API HTTP Error during Chatty reply: {e}")
        except Exception as e:
            logger.error(f"Unexpected LLM API Error during Chatty reply: {e}")
            return None

    async def generate_delayed_reply(self, is_burst: bool = False) -> Optional[str]:
        """
        Gathers all consecutive user messages from the end of the chat history
        (simulating a burst of rapid-fire texts) and generates a single combined response.
        """
        # 1. Read history to find pending user messages
        if not self.history_path.exists():
            return None

        pending_texts = []
        with open(self.history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Iterate backwards to find all user messages until we hit an assistant message
            for line in reversed(lines):
                if not line.strip(): continue
                try:
                    entry = json.loads(line)
                    if entry.get("role") == "user":
                        pending_texts.insert(0, entry.get("content", ""))
                    elif entry.get("role") == "assistant":
                        break
                except json.JSONDecodeError:
                    continue

        if not pending_texts:
            return None

        full_text = "\n".join(pending_texts)

        # 2. Process Language
        lang = await self._detect_language(full_text)

        # 2a. Snapshot context before RAG for aligned summary generation (Task 1).
        snapshot_messages, context_timestamp = self._read_recent_messages_snapshot()

        # 3. Retrieve RAG Context (async, non-blocking; guarded by ENABLE_RAG_INGESTION)
        retrieved_context = await self._retrieve_rag_context(full_text)

        # 4. Build System Prompt
        base_prompt_path = Path("./data/system_prompts/default.txt")
        base_prompt = "You are a helpful assistant."
        if base_prompt_path.exists():
            with open(base_prompt_path, "r", encoding="utf-8") as f:
                base_prompt = f.read()

        custom_instructions = self.profile.get("system_prompt") or "None"
        summary = self.profile.get("conversation_summary") or "{}"

        # ADR-039: Language enforcement block placed ABOVE RAG context (delayed reply path)
        lang_enforcement = build_language_enforcement_block(lang)

        context_section = retrieved_context if retrieved_context else "No relevant past memories found."
        system_prompt = f"""[Global Instructions]
{base_prompt}

[User Profile]
Name: {self.profile.get('name', 'Unknown')}
Preferred Language: {lang}
Custom Instructions: {custom_instructions}

{lang_enforcement}

[CONTEXT MEMORY]
The following relevant past conversations have been retrieved:
{context_section}

INSTRUCTION: Use this context to maintain continuity. If the user refers to
previous topics, use the information above to answer accurately.
If the context is irrelevant, ignore it.
If the context is in a different language, translate relevant facts to {lang} before responding.

[Recent Context Summary]
{summary}

[Constraint]
Reply ONLY in {lang}. Be natural, human-like, and concise."""

        # 5. Call LLM
        try:
            ai_reply = await ask_llm(full_text, task_type="generic", system_override=system_prompt)

            # 6. Append AI reply to history
            self._append_history("assistant", ai_reply)

            # 7. Trigger background summary with the aligned snapshot (Task 1).
            await self._update_summary(
                snapshot_messages=snapshot_messages,
                context_timestamp=context_timestamp,
            )

            return ai_reply
        except Exception as e:
            logger.error(f"Error during delayed Chatty reply: {e}")
            return None

    async def get_rag_stats(self) -> Dict[str, Any]:
        """Get statistics about RAG memory for this chat.
        
        Returns a dictionary with:
        - chromadb_count: Number of vectors stored
        - embedding_model: Current embedding model name
        - ttl_days: Current RAG TTL setting
        - recency_alpha: Recency decay factor
        - rag_enabled: Whether RAG ingestion is enabled
        """
        try:
            count = await asyncio.to_thread(lambda: self.collection.count())
            return {
                "chromadb_count": count,
                "embedding_model": settings.RAG_EMBEDDING_MODEL,
                "ttl_days": getattr(settings, 'RAG_DEFAULT_TTL_DAYS', 7),
                "recency_alpha": getattr(settings, 'MEMORY_RECENCY_ALPHA', 0.5),
                "rag_enabled": settings.ENABLE_RAG_INGESTION,
            }
        except Exception as e:
            logger.error(f"Error getting RAG stats for {self.chat_id}: {e}")
            return {"error": str(e)}

    async def clear_all_memory(self) -> bool:
        """Clear all RAG vectors and chat history for this user.
        
        Clears:
        - All ChromaDB vectors for this chat
        - All MessageBuffer entries for this chat
        - Chat history file
        
        Returns True if successful, False otherwise.
        """
        try:
            # Delete all vectors from ChromaDB for this chat
            await asyncio.to_thread(
                lambda: self.collection.delete(where={"chat_id": self.chat_id})
            )
            logger.info(f"Cleared ChromaDB vectors for {self.chat_id}")
            
            # Delete chat history file if it exists
            if self.history_path.exists():
                self.history_path.unlink()
                logger.info(f"Cleared chat history file for {self.chat_id}")
            
            return True
        except Exception as e:
            logger.error(f"Error clearing memory for {self.chat_id}: {e}")
            return False

    async def list_collections(self) -> list[str]:
        """List all active ChromaDB collection names/IDs.
        
        Returns:
            List of collection identifiers currently stored in ChromaDB
        """
        try:
            # Get all collections from ChromaDB
            all_collections = await asyncio.to_thread(
                lambda: self.chroma_client.list_collections()
            )
            return [c.name for c in all_collections]
        except Exception as e:
            logger.error(f"Error listing collections: {e}")
            return []

    async def clear_scope(
        self, scope_type: str, scope_id: str | None = None
    ) -> int:
        """Clear memory for a specific scope (user, group, or all).
        
        Args:
            scope_type: Type of scope - "user", "group", or "all"
            scope_id: Optional identifier for the scope (JID for user/group)
        
        Returns:
            Number of vectors deleted
        """
        try:
            deleted_count = 0
            
            if scope_type == "user" and scope_id:
                # Delete vectors for specific user
                await asyncio.to_thread(
                    lambda: self.collection.delete(where={"chat_id": scope_id})
                )
                deleted_count = 1
                logger.info(f"Cleared memory for user {scope_id}")
                
            elif scope_type == "group" and scope_id:
                # Delete vectors for specific group
                await asyncio.to_thread(
                    lambda: self.collection.delete(where={"chat_id": scope_id})
                )
                deleted_count = 1
                logger.info(f"Cleared memory for group {scope_id}")
                
            elif scope_type == "all":
                # Get all collections and delete them all
                all_collections = await self.list_collections()
                for cname in all_collections:
                    try:
                        coll = await asyncio.to_thread(
                            lambda: self.chroma_client.get_collection(name=cname)
                        )
                        await asyncio.to_thread(
                            lambda: coll.delete(where={})
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Error deleting collection {cname}: {e}")
                logger.info(f"Cleared all {deleted_count} memory collections")
                
            return deleted_count
        except Exception as e:
            logger.error(f"Error clearing scope {scope_type}:{scope_id}: {e}")
            return 0
