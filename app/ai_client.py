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


import base64
from typing import Optional

async def ask_llm(
    prompt: str,
    task_type: Literal[
        "translation",
        "summary",
        "search_answer",
        "generic",
        "language_detection",
        "vision",
        "json"
    ] = "generic",
    system_override: Optional[str] = None,
    image_path: Optional[str] = None
) -> str:
    """
    Unified interface to call the LLM based on task type and
    configuration. Supports both local (LM Studio / Ollama) and
    cloud (OpenAI / Groq) endpoints via LLM_ENDPOINT in .env.
    """
    temperature = (
        _TEMP_PRECISE if task_type in _PRECISE_TASKS else _TEMP_CREATIVE
    )

    messages = []
    if system_override:
        messages.append({"role": "system", "content": system_override})

    if task_type == "vision" and image_path:
        # Load image as base64
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                ext = image_path.split('.')[-1].lower()
                if ext == 'jpg':
                    ext = 'jpeg'
                image_url = f"data:image/{ext};base64,{encoded_string}"

                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                })
        except Exception as e:
            logger.error(f"Failed to read image for vision LLM: {e}")
            messages.append({"role": "user", "content": prompt})
    else:
        messages.append({"role": "user", "content": prompt})

    try:
        kwargs = {
            "model": settings.DEFAULT_MODEL_NAME,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }

        # Support JSON mode if requested
        if task_type == "json":
            kwargs["response_format"] = { "type": "json_object" }

        response = await llm_client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("Error calling LLM: %s", exc)
        return "Error: Could not process request with AI."
