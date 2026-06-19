from typing import Literal
from openai import AsyncOpenAI
from app.config import settings
import logging

logger = logging.getLogger(__name__)

llm_client = AsyncOpenAI(
    base_url=settings.LLM_ENDPOINT,
    api_key=settings.LLM_API_KEY or "placeholder-key"
)

async def ask_llm(prompt: str, task_type: Literal["translation", "summary", "search_answer", "generic", "language_detection"] = "generic") -> str:
    """
    Unified interface to call the LLM based on task type and configuration.
    """
    try:
        response = await llm_client.chat.completions.create(
            model=settings.DEFAULT_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3 if task_type in ["translation", "language_detection"] else 0.7,
            max_tokens=1024
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error calling LLM: {e}")
        return "Error: Could not process request with AI."
