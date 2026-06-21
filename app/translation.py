from app.ai_client import ask_llm, TokenExhaustedError, TranslationError
from langdetect import detect, detect_langs, DetectorFactory
DetectorFactory.seed = 0
from langdetect.lang_detect_exception import LangDetectException
import re
from typing import Optional
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Issue 3: fallback map for LLMs that return full language names
# instead of ISO 639-1 codes (e.g. "English" -> "en").
FULL_NAME_TO_CODE: dict[str, str] = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "dutch": "nl",
    "russian": "ru",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "arabic": "ar",
    "hindi": "hi",
    "indonesian": "id",
    "malay": "ms",
    "thai": "th",
    "vietnamese": "vi",
    "turkish": "tr",
    "polish": "pl",
    "swedish": "sv",
}


def detect_language_safe(text: str, target_lang: str) -> Optional[str]:
    """
    Determines if text should be translated based on length, emojis,
    and probabilistic language detection. Returns detected code or None if skipped.
    """
    # 1. Length Guard
    if len(text.strip()) < settings.TRANSLATION_MIN_LENGTH:
        logger.debug(f"Skipping translation: Length < {settings.TRANSLATION_MIN_LENGTH}")
        return None

    # 2. Emoji/Pattern Guard (Skip if >80% non-alphanumeric)
    alphanumeric_count = sum(c.isalnum() for c in text)
    if alphanumeric_count / max(len(text), 1) < 0.2:
        logger.debug("Skipping translation: High non-alphanumeric density")
        return None

    # 3. Detection with Confidence
    try:
        langs = detect_langs(text)
        if not langs:
            logger.debug("Skipping translation: No language detected")
            return None

        detected = langs[0]
        conf = detected.prob

        # 4. Confidence Guard
        if conf < settings.TRANSLATION_CONFIDENCE_THRESHOLD:
            logger.debug(f"Skipping translation: Low confidence ({conf:.2f})")
            return None

        code = detected.lang

        # 5. ID/MS Equivalence
        equivalent_langs = {lang.strip().lower() for lang in settings.TRANSLATION_EQUIVALENT_LANGS.split(',')}
        if code in equivalent_langs and target_lang in equivalent_langs:
            logger.debug(f"Skipping translation: Equivalent languages ({code} -> {target_lang})")
            return None

        # 6. Exact Match
        if code == target_lang:
            logger.debug(f"Skipping translation: Exact match ({code})")
            return None

        # 7. Confirmed Mismatch
        return code

    except LangDetectException:
        # Safe Fail: Do not translate if detection fails
        logger.debug("Skipping translation: LangDetectException")
        return None
    except Exception as e:
        logger.error(f"Error in detect_language_safe: {e}")
        return None

async def detect_language(text: str) -> str:
    """
    Detects the primary language of the given text using langdetect.
    Returns the ISO 639-1 two-letter lowercase language code.
    Returns 'unknown' if detection fails.
    (LLM fallback removed for performance and reliability).
    """
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"




async def translate_text(text: str, target_language: str, ignore_list: list = None, chat_id: str = None, msg_id: str = None) -> str:
    """
    Translates text to the target language using the LLM.
    Returns the original text immediately if safe language detection fails or matches target.
    """
    source_lang = detect_language_safe(text, target_language)

    if source_lang is None:
        return text

    if ignore_list and source_lang in ignore_list:
        logger.debug(f"Skipping translation: Source language '{source_lang}' is explicitly ignored")
        return text

    # Guard Rails: Truncate input > 2000 characters
    if len(text) > 2000:
        logger.warning(f"Truncating text from {len(text)} to 2000 characters before translation")
        text_to_translate = text[:2000]
    else:
        text_to_translate = text

    prompt = (
        "You are a precise translation engine.\n"
        f"Translate the input text to {target_language}. Automatically detect the actual source language (ignore any provided ISO codes if they conflict). Output ONLY the translated text.\n"
        "NO explanations. NO prefixes like 'Here is the translation'. NO meta-commentary. Preserve all emojis, slang, and formatting exactly.\n\n"
        f"Text to translate:\n{text_to_translate}"
    )

    max_retries = 1
    current_multiplier = 1.0
    
    for attempt in range(max_retries + 1):
        try:
            max_tokens = int(settings.LLM_MAX_TOKENS * current_multiplier)
            response_content = await ask_llm(prompt, task_type="translation", max_tokens_override=max_tokens)
            return f"[{source_lang.upper()}] {response_content}"
            
        except TokenExhaustedError:
            if attempt < max_retries:
                logger.warning(f"Translation hit token limit (attempt {attempt + 1}). Retrying with 50% more tokens.")
                current_multiplier = 1.5
                continue
            else:
                logger.error("Translation failed after 1 retry due to token exhaustion.")
                return f"{text}\n\n{settings.MSG_TRANSLATION_ERROR}"
                
        except TranslationError as e:
            logger.error(f"Translation failed silently or returned error. chat_id={chat_id}, msg_id={msg_id}, error={str(e)}")
            return f"{text}\n\n{settings.MSG_TRANSLATION_ERROR}"
            
        except Exception as e:
            logger.error(f"Critical error during translation API call. chat_id={chat_id}, msg_id={msg_id}, error={str(e)}")
            return f"{text}\n\n{settings.MSG_TRANSLATION_ERROR}"
            
    return f"{text}\n\n{settings.MSG_TRANSLATION_ERROR}"
