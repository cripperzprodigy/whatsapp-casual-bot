from app.ai_client import ask_llm
from langdetect import detect, detect_langs, DetectorFactory
DetectorFactory.seed = 0
from langdetect.lang_detect_exception import LangDetectException
import re
from app.config import settings

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


def should_translate(text: str, target_lang: str) -> tuple[bool, str]:
    """
    Determines if text should be translated based on length, emojis, 
    and probabilistic language detection.
    Returns (should_translate, original_text).
    """
    # 1. Length Guard
    if len(text.strip()) < settings.TRANSLATION_MIN_LENGTH:
        return False, text
        
    # 2. Emoji/Pattern Guard (Skip if >80% non-alphanumeric)
    alphanumeric_count = sum(c.isalnum() for c in text)
    if alphanumeric_count / max(len(text), 1) < 0.2:
        return False, text

    # 3. Detection with Confidence
    try:
        langs = detect_langs(text)
        if not langs:
            return False, text
            
        detected = langs[0]
        conf = detected.prob
        
        # 4. Confidence Guard
        if conf < settings.TRANSLATION_CONFIDENCE_THRESHOLD:
            return False, text
            
        det_code = detected.lang
        
        # 5. ID/MS Equivalence
        equivalent_langs = {lang.strip().lower() for lang in settings.TRANSLATION_EQUIVALENT_LANGS.split(',')}
        if det_code in equivalent_langs and target_lang in equivalent_langs:
            return False, text
            
        # 6. Exact Match
        if det_code == target_lang:
            return False, text
            
        # 7. Mismatch confirmed
        return True, text
        
    except LangDetectException:
        # Fail safe: Do not translate if detection fails
        return False, text
    except Exception as e:
        logger.error(f"Error in should_translate: {e}")
        return False, text

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


import logging

logger = logging.getLogger(__name__)

async def translate_text(text: str, target_language: str, source_lang: str = None, chat_id: str = None, msg_id: str = None) -> str:
    """
    Translates text to the target language using the LLM.
    Optionally accepts a source_lang to improve accuracy and reduce guessing.
    """
    source_hint = ""
    if source_lang and source_lang != "unknown":
        source_hint = f"from the language represented by the ISO 639-1 code '{source_lang}' "

    prompt = (
        f"Translate the following text {source_hint}to the language represented "
        f"by the ISO 639-1 code '{target_language}'.\n"
        "Rules:\n"
        "1. Preserve the exact original tone and formatting "
        "(formal/casual, emojis, line breaks).\n"
        "2. DO NOT add any conversational filler, introductions, or "
        "explanations like 'Here is the translation' or "
        "'Sure, here it is'.\n"
        "3. Output ONLY the translated text and nothing else.\n"
        "4. If it is a short message, you may optionally prefix it "
        "with the original language name in brackets, like "
        "'[Spanish] Translated text here'.\n\n"
        f"Text to translate:\n{text}"
    )

    from app.config import settings
    try:
        result = await ask_llm(prompt, task_type="translation")
        if not result or result.startswith("Error:"):
            logger.error(f"Translation failed silently or returned error. chat_id={chat_id}, msg_id={msg_id}, response={result}")
            return f"{text}\n\n{settings.MSG_TRANSLATION_ERROR}"
        return result
    except Exception as e:
        logger.error(f"Critical error during translation API call. chat_id={chat_id}, msg_id={msg_id}, error={str(e)}")
        return f"{text}\n\n{settings.MSG_TRANSLATION_ERROR}"
