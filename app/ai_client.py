from typing import Literal, Optional
from dataclasses import dataclass
from openai import AsyncOpenAI
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class TokenExhaustedError(Exception):
    pass

class TranslationError(Exception):
    pass

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
    image_path: Optional[str] = None,
    max_tokens_override: Optional[int] = None
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
            "max_tokens": max_tokens_override or settings.LLM_MAX_TOKENS,
        }

        # Support JSON mode if requested
        if task_type == "json":
            kwargs["response_format"] = { "type": "text" }

        response = await llm_client.chat.completions.create(**kwargs)

        # Robust Parsing: Check if choices exists and is non-empty
        if not hasattr(response, 'choices') or not response.choices:
            raw_resp = response.model_dump_json() if hasattr(response, 'model_dump_json') else str(response)
            logger.error(f"LLM returned no choices. Raw response: {raw_resp}")
            raise TranslationError("LLM returned no choices.")

        choice = response.choices[0]
        content = choice.message.content
        finish_reason = getattr(choice, 'finish_reason', None)

        # Logic Update based on finish_reason
        if finish_reason == "length":
            logger.warning("Token limit hit during translation")
            raise TokenExhaustedError("Token limit hit.")

        # Handle Refusals / Empty Content
        if not content or content.strip() == "":
            if finish_reason != "stop":
                raw_resp = response.model_dump_json() if hasattr(response, 'model_dump_json') else str(response)
                logger.error(f"LLM returned empty content. Raw response: {raw_resp}")
                raise TranslationError("LLM returned empty content.")
            else:
                return ""

        if finish_reason == "stop" or finish_reason is None:
            return content.strip()

        return content.strip()
    except TokenExhaustedError:
        raise
    except TranslationError:
        raise
    except Exception as exc:
        # Fallback: Extract raw response if it's an API error
        raw_body = ""
        if hasattr(exc, 'response'):
            try:
                raw_body = f" Raw response body: {exc.response.text}"
            except Exception:
                pass

        logger.error(f"Error calling LLM: {exc}.{raw_body}")
        raise TranslationError(f"Could not process request with AI: {exc}")
