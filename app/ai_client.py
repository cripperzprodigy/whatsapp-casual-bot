from typing import Literal
from openai import AsyncOpenAI
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Issue 14: named constants instead of inline magic numbers
_TEMP_PRECISE = 0.3   # translation / language detection tasks
_TEMP_CREATIVE = 0.7  # summary / search / generic tasks

llm_client = AsyncOpenAI(
    base_url=settings.LLM_ENDPOINT,
    api_key=settings.LLM_API_KEY or "placeholder-key",
)

_PRECISE_TASKS = {"translation", "language_detection"}


async def ask_llm(
    prompt: str,
    task_type: Literal[
        "translation",
        "summary",
        "search_answer",
        "generic",
        "language_detection",
    ] = "generic",
) -> str:
    """
    Unified interface to call the LLM based on task type and
    configuration. Supports both local (LM Studio / Ollama) and
    cloud (OpenAI / Groq) endpoints via LLM_ENDPOINT in .env.
    """
    temperature = (
        _TEMP_PRECISE if task_type in _PRECISE_TASKS else _TEMP_CREATIVE
    )
    try:
        response = await llm_client.chat.completions.create(
            model=settings.DEFAULT_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            # Issue 14: use LLM_MAX_TOKENS instead of magic 1024
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("Error calling LLM: %s", exc)
        return "Error: Could not process request with AI."
