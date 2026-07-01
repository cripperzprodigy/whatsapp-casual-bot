import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

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

logger = logging.getLogger(__name__)


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
        # Group Check: Detect the actual message language first,
        # falling back to the group's configured default only if detection fails.
        # This ensures AI replies match the user's input language (e.g., Indonesian
        # triggers get Indonesian replies) rather than always defaulting to English.
        if "@g.us" in self.chat_id:
            from app.state import get_chat_settings
            from app.state import SessionLocal
            with SessionLocal() as db:
                chat_settings = get_chat_settings(db, self.chat_id)
                group_default_lang = chat_settings.default_target_language if chat_settings.default_target_language else getattr(settings, 'DEFAULT_GROUP_LANGUAGE', 'en')
            
            # Attempt live detection on the incoming message text
            try:
                detected = detect(text)
                if detected:
                    return detected
            except (LangDetectException, json.JSONDecodeError, ValueError):
                pass
            
            # LLM-based fallback detection
            try:
                from app.translation import detect_language
                detected = await detect_language(text)
                if detected:
                    return detected
            except Exception as e:
                logger.warning(f"Group language detection fallback failed: {e}")
            
            # Final fallback: group's configured default language
            return group_default_lang

        # Private DM Check
        if self.profile.get("preferred_language"):
            return self.profile["preferred_language"]

        try:
            lang = detect(text)
            self.profile["lang_pref"] = lang
            self.profile["name"] = self.sender_name # Update name just in case
            self._save_profile()
            return lang
        except (LangDetectException, json.JSONDecodeError, ValueError) as e:
            from app.translation import detect_language
            try:
                lang = await detect_language(text)
                return lang
            except (Exception) as inner_e:
                # Swallowing here is necessary for language fallback reliability
                logger.warning(f"Langdetect and LLM fallback both failed: {inner_e}")
                return getattr(settings, 'DEFAULT_DM_LANGUAGE', 'en')

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
            meta = {"role": role, "timestamp": ts, "chat_id": self.chat_id}
            if extra_meta:
                meta.update({k: v for k, v in extra_meta.items() if k != "content"})
            try:
                asyncio.create_task(self._rag_ingest_async(content, meta))
            except RuntimeError:
                # No running event loop (e.g., sync test context) — skip silently
                pass

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
            results = await asyncio.to_thread(
                lambda: self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(settings.RAG_TOP_K, count),
                    where={"chat_id": self.chat_id},  # Defense-in-depth isolation
                )
            )
            if results["documents"] and results["documents"][0]:
                return "\n".join(results["documents"][0])
        except ValueError as e:
            logger.error(f"RAG retrieval error for {self.chat_id}: {e}")
        except Exception as e:
            logger.error(f"RAG retrieval unexpected error for {self.chat_id}: {e}")
        return ""

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

    async def _update_summary(self):
        if not settings.DYNAMIC_SYSTEM_PROMPT:
            return

        # Count lines
        if not self.history_path.exists():
            return

        with open(self.history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Only summarize every 5 messages
        if len(lines) % 5 != 0:
            return

        # Get last 10 messages
        recent = "".join([json.loads(line)["role"] + ": " + json.loads(line)["content"] + "\n" for line in lines[-settings.MAX_CONTEXT_MESSAGES:]])

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

        context_section = retrieved_context if retrieved_context else "No relevant past memories found."
        system_prompt = f"""[Global Instructions]
{base_prompt}

[User Profile]
Name: {self.profile.get('name', 'Unknown')}
Preferred Language: {lang}
Custom Instructions: {custom_instructions}

[CONTEXT MEMORY]
The following relevant past conversations have been retrieved:
{context_section}

INSTRUCTION: Use this context to maintain continuity. If the user refers to
previous topics, use the information above to answer accurately.
If the context is irrelevant, ignore it.

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

            # 8. Trigger background summary
            await self._update_summary()

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

        context_section = retrieved_context if retrieved_context else "No relevant past memories found."
        system_prompt = f"""[Global Instructions]
{base_prompt}

[User Profile]
Name: {self.profile.get('name', 'Unknown')}
Preferred Language: {lang}
Custom Instructions: {custom_instructions}

[CONTEXT MEMORY]
The following relevant past conversations have been retrieved:
{context_section}

INSTRUCTION: Use this context to maintain continuity. If the user refers to
previous topics, use the information above to answer accurately.
If the context is irrelevant, ignore it.

[Recent Context Summary]
{summary}

[Constraint]
Reply ONLY in {lang}. Be natural, human-like, and concise."""

        # 5. Call LLM
        try:
            ai_reply = await ask_llm(full_text, task_type="generic", system_override=system_prompt)

            # 6. Append AI reply to history
            self._append_history("assistant", ai_reply)

            # 7. Trigger background summary
            await self._update_summary()

            return ai_reply
        except Exception as e:
            logger.error(f"Error during delayed Chatty reply: {e}")
            return None
