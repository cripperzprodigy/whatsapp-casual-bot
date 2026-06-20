from app.ai_client import ask_llm
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException

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


async def detect_language(text: str) -> str:
    """
    Detects the primary language of the given text using langdetect.
    Falls back to LLM if langdetect fails.
    Returns the ISO 639-1 two-letter lowercase language code
    (e.g. 'en', 'id', 'es'). Returns 'unknown' if detection fails.
    """
    try:
        # Fast path
        return detect(text)
    except LangDetectException:
        # Slow path fallback
        prompt = (
            "Detect the primary language of the following text. "
            "Respond ONLY with the ISO 639-1 two-letter lowercase language "
            "code (e.g. 'en', 'es', 'id'). "
            "If you are unsure, respond with 'unknown'.\n\n"
            f"Text: {text}"
        )
        result = await ask_llm(prompt, task_type="language_detection")

        # Issue 3: strip whitespace FIRST, then lower, so " En " -> "en"
        code = result.strip().lower()

        if len(code) == 2 or code == "unknown":
            return code

        # Issue 3: fallback — LLM returned a full name like "english"
        if code in FULL_NAME_TO_CODE:
            return FULL_NAME_TO_CODE[code]

        return "unknown"


async def translate_text(text: str, target_language: str, source_lang: str = None) -> str:
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
    result = await ask_llm(prompt, task_type="translation")
    return result
