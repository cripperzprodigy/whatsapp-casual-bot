import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from langdetect import detect
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
import pdfplumber

from app.config import settings

# Since AIMemoryEngine interacts with ai_client.py, we might have to import it
from app.ai_client import ask_llm

logger = logging.getLogger(__name__)

class AIMemoryEngine:
    def __init__(self, chat_id: str, sender_name: str):
        self.chat_id = chat_id
        self.sender_name = sender_name
        self.safe_id = chat_id.replace('@', '_').replace('.', '_')
        self.user_dir = Path(f"./data/contacts/{self.safe_id}")
        self.user_dir.mkdir(parents=True, exist_ok=True)

        self.profile_path = self.user_dir / "profile.json"
        self.history_path = self.user_dir / "chat_history.jsonl"
        self.vector_db_path = self.user_dir / "vector_db"
        self.vector_db_path.mkdir(parents=True, exist_ok=True)

        self.profile = self._load_profile()

        # Load local embedding model
        # Try to use TINY fallback if specified, otherwise default to config
        model_name = settings.RAG_EMBEDDING_MODEL
        try:
            self.embedding_model = SentenceTransformer(model_name)
        except Exception as e:
            logger.warning(f"Failed to load embedding model {model_name}. Fallback to all-MiniLM-L3-v2. Error: {e}")
            self.embedding_model = SentenceTransformer('all-MiniLM-L3-v2')

        # Init ChromaDB strictly inside user folder
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.vector_db_path),
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.chroma_client.get_or_create_collection("user_memory")

    def _load_profile(self) -> Dict[str, Any]:
        if self.profile_path.exists():
            with open(self.profile_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "name": self.sender_name,
            "lang_pref": None,
            "system_prompt": None,
            "conversation_summary": None,
            "chatty_status": settings.CHATTY_GROUP_DEFAULT if "@g.us" in self.chat_id else settings.CHATTY_DEFAULT
        }

    def _save_profile(self):
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, indent=2)

    def _detect_language(self, text: str) -> str:
        try:
            lang = detect(text)
            self.profile["lang_pref"] = lang
            self.profile["name"] = self.sender_name # Update name just in case
            self._save_profile()
            return lang
        except Exception as e:
            logger.warning(f"Langdetect failed: {e}")
            # LLM Fallback (Simulated here due to prompt constraints, but can use ask_llm)
            # For brevity and safety in webhook loop, default to global target if completely fails
            return settings.GLOBAL_TARGET_LANGUAGE

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
                    "Describe this image in detail.",
                    task_type="vision",
                    image_path=media_path
                )
                return f"[Image uploaded by user: {description}]"
            except Exception as e:
                logger.error(f"Vision error: {e}")
                return "[Image uploaded by user, but failed to analyze]"

        elif ext == 'pdf':
            try:
                text = ""
                with pdfplumber.open(media_path) as pdf:
                    for page in pdf.pages[:3]: # limit to 3 pages for speed
                        text += page.extract_text() + "\n"
                return f"[PDF uploaded by user. Contents: {text[:1000]}]"
            except Exception as e:
                logger.error(f"PDF extraction error: {e}")
                return "[PDF uploaded by user, but failed to read]"

        return f"[Unsupported media uploaded: {media_path}]"

    def _embed_text(self, text: str) -> List[float]:
        return self.embedding_model.encode(text).tolist()

    def _append_history(self, role: str, content: str):
        msg = {"role": role, "content": content, "timestamp": int(time.time())}
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg) + "\n")

        # Ingest to RAG if it's user message or assistant message
        if content.strip():
            doc_id = f"msg_{int(time.time() * 1000)}"
            embedding = self._embed_text(content)
            self.collection.add(
                documents=[content],
                embeddings=[embedding],
                metadatas=[{"role": role, "timestamp": int(time.time())}],
                ids=[doc_id]
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
        recent = "".join([json.loads(line)["role"] + ": " + json.loads(line)["content"] + "\n" for line in lines[-10:]])

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
        except Exception as e:
            logger.error(f"Failed to update summary: {e}")

    async def process_message(self, text: str, media_path: Optional[str] = None) -> Optional[str]:
        # 1. Process Language
        lang = self._detect_language(text)

        # 2. Process Media
        media_desc = await self._process_media(media_path)
        full_text = text
        if media_desc:
            full_text += f"\n\n{media_desc}"

        # 3. Save to history & RAG
        self._append_history("user", full_text)

        # 4. Retrieve RAG Context
        retrieved_context = ""
        try:
            if self.collection.count() > 0:
                query_embedding = self._embed_text(full_text)
                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(5, self.collection.count())
                )
                if results['documents'] and results['documents'][0]:
                    retrieved_context = "\n".join(results['documents'][0])
        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")

        # 5. Build System Prompt
        base_prompt_path = Path("./data/system_prompts/default.txt")
        base_prompt = "You are a helpful assistant."
        if base_prompt_path.exists():
            with open(base_prompt_path, "r", encoding="utf-8") as f:
                base_prompt = f.read()

        custom_instructions = self.profile.get("system_prompt") or "None"
        summary = self.profile.get("conversation_summary") or "{}"

        system_prompt = f"""[Global Instructions]
{base_prompt}

[User Profile]
Name: {self.profile.get('name', 'Unknown')}
Preferred Language: {lang}
Custom Instructions: {custom_instructions}

[Long Term Memory (RAG)]
{retrieved_context}

[Recent Context Summary]
{summary}

[Constraint]
Reply ONLY in {lang}. Be natural, human-like, and concise."""

        # 6. Call LLM
        # For Chatty, we just pass the system prompt and the current full_text
        # We don't need to pass chat history again because RAG + Summary covers it
        try:
            ai_reply = await ask_llm(full_text, task_type="generic", system_override=system_prompt)

            # 7. Append AI reply to history
            self._append_history("assistant", ai_reply)

            # 8. Trigger background summary
            await self._update_summary()

            return ai_reply
        except Exception as e:
            logger.error(f"LLM API Error during Chatty reply: {e}")
            return None
