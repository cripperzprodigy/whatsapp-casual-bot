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

VALID_TARGET_LANGUAGES = set(FULL_NAME_TO_CODE.values())

# ------------------------------------------------------------------ #
#  Heuristic Keyword Set for Short Malay/Indonesian Text Detection
#  langdetect is unreliable for texts < 20 chars in ms/id, often
#  returning 'fi' (Finnish), 'tl' (Tagalog), or 'en' (English).
#  This curated set provides a fast O(1) fallback.
# ------------------------------------------------------------------ #
COMMON_MS_ID_WORDS: set[str] = {
    # Pronouns & address
    "saya", "aku", "awak", "kamu", "dia", "kami", "kita", "mereka",
    # Common verbs
    "makan", "minum", "pergi", "datang", "buat", "ambil", "beli",
    "jual", "cari", "mulai", "kerja", "tidur", "bangun", "duduk",
    "baca", "tulis", "dengar", "lihat", "tahu", "boleh", "mahu",
    # Common nouns
    "orang", "rumah", "hari", "masa", "waktu", "tempat", "air",
    "nasi", "ayam", "ikan", "duit", "wang", "kereta", "jalan",
    # Particles & connectors
    "tak", "tidak", "nak", "ke", "di", "dan", "atau", "ya",
    "lah", "kan", "leh", "pun", "dah", "ada", "ini", "itu",
    "apa", "mana", "bila", "siapa", "kenapa", "macam", "dengan",
    "untuk", "dari", "dalam", "sudah", "belum", "akan", "sedang",
    # Common adjectives
    "baik", "besar", "kecil", "banyak", "sedikit", "cantik",
    "bagus", "mahal", "murah", "cepat", "lambat", "panas", "sejuk",
}

# Languages that langdetect commonly confuses with ms/id on short texts
_MS_ID_FALSE_POSITIVE_LANGS = {"fi", "tl", "so", "sw", "hr", "ro"}


def _heuristic_ms_id_check(text: str) -> bool:
    """
    Returns True if the text is likely Malay/Indonesian based on keyword matching.
    Used as a fast heuristic for short texts where langdetect is unreliable.
    """
    tokens = re.findall(r'[a-zA-Z]+', text.lower())
    if not tokens:
        return False
    match_count = sum(1 for t in tokens if t in COMMON_MS_ID_WORDS)
    return match_count / len(tokens) >= 0.5


def is_valid_language_code(code: str) -> bool:
    """Check if the provided language code is explicitly supported."""
    if not code:
        return False
    return code.lower() in VALID_TARGET_LANGUAGES


def split_text_smart(text: str, max_chars: int) -> list[str]:
    """Splits text intelligently by paragraphs, then lines, then sentences, then characters."""
    def split_by(text_to_split: str, delimiters: list) -> list[str]:
        if len(text_to_split) <= max_chars or not delimiters:
            return [text_to_split[i:i+max_chars] for i in range(0, len(text_to_split), max_chars)]

        delimiter = delimiters[0]
        if isinstance(delimiter, str):
            parts = text_to_split.split(delimiter)
            parts = [p + delimiter for p in parts[:-1]] + [parts[-1]] if len(parts) > 1 else parts
        else:
            parts = [p + " " for p in delimiter.split(text_to_split) if p]
            if parts:
                parts[-1] = parts[-1].rstrip() # remove trailing space from last part

        result = []
        current_chunk = ""
        for part in parts:
            if not part:
                continue
            if len(current_chunk) + len(part) <= max_chars:
                current_chunk += part
            else:
                if current_chunk:
                    result.append(current_chunk)
                if len(part) > max_chars:
                    result.extend(split_by(part, delimiters[1:]))
                    current_chunk = ""
                else:
                    current_chunk = part
        if current_chunk:
            result.append(current_chunk)
        return result

    delimiters = ["\n\n", "\n", re.compile(r'(?<=[.!?])\s+')]
    return split_by(text, delimiters)


def detect_language_safe(text: str, target_lang: str) -> Optional[str]:
    """
    Determines if text should be translated based on length, emojis,
    and probabilistic language detection. Returns detected code or None if skipped.

    Implements the EN/ID/MS Linguistic Sphere policy (ADR-028):
    - Languages in GLOBAL_IGNORED_LANGUAGES are NEVER translated.
    - Short texts (< 20 chars) use a keyword heuristic for ms/id detection.
    - langdetect false positives (fi/tl) are corrected via keyword override.
    """
    # 0. Load the ignored languages set (EN/ID/MS sphere)
    ignored_langs = {
        lang.strip().lower()
        for lang in settings.GLOBAL_IGNORED_LANGUAGES.split(',')
        if lang.strip()
    }

    # 1. Length Guard
    if len(text.strip()) < settings.TRANSLATION_MIN_LENGTH:
        logger.debug(f"Skipping translation: Length < {settings.TRANSLATION_MIN_LENGTH}")
        return None

    # 2. Emoji/Pattern Guard
    alphanumeric_count = sum(c.isalnum() for c in text)
    if alphanumeric_count < 2:
        logger.debug("Skipping translation: Less than 2 alphanumeric characters")
        return None

    # 3. Short-Text Heuristic for Malay/Indonesian (Early Exit)
    stripped = text.strip()
    if _heuristic_ms_id_check(stripped):
        logger.debug(f"Keyword heuristic detected ms/id for: '{stripped}'")
        # ms is in the ignored set → skip translation entirely
        if "ms" in ignored_langs or "id" in ignored_langs:
            logger.debug("Skipping translation: ms/id detected and is in ignored languages (linguistic sphere)")
            return None
        # If ms/id were somehow NOT ignored, return the code for translation
        return "ms"

    # 4. Target language in ignored set — if target itself is ignored,
    #    only translate if source is a truly foreign language (handled below)

    # 5. Detection with Confidence (standard langdetect path)
    try:
        langs = detect_langs(text)
        if not langs:
            logger.debug("Skipping translation: No language detected")
            return None

        detected = langs[0]
        conf = detected.prob

        # 6. Confidence Guard
        if conf < settings.TRANSLATION_CONFIDENCE_THRESHOLD:
            logger.debug(f"Skipping translation: Low confidence ({conf:.2f})")
            return None

        code = detected.lang

        # 7. False-Positive Guard: langdetect returns fi/tl/so for ms/id text
        if code in _MS_ID_FALSE_POSITIVE_LANGS and _heuristic_ms_id_check(stripped):
            logger.info(f"Overriding langdetect false positive: '{code}' -> 'ms' (keyword match)")
            code = "ms"

        # 8. Linguistic Sphere Check (GLOBAL_IGNORED_LANGUAGES)
        if code in ignored_langs:
            logger.debug(f"Skipping translation: Detected language '{code}' is in ignored languages (linguistic sphere)")
            return None

        # 9. Equivalence Check (backwards compat — also catches sphere langs)
        equivalent_langs = {lang.strip().lower() for lang in settings.TRANSLATION_EQUIVALENT_LANGS.split(',')}
        if code in equivalent_langs and target_lang in equivalent_langs:
            logger.debug(f"Skipping translation: Equivalent languages ({code} -> {target_lang})")
            return None

        # 10. Exact Match
        if code == target_lang:
            logger.debug(f"Skipping translation: Exact match ({code})")
            return None

        # 11. Confirmed foreign language — proceed to translation
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
    if not text.strip():
        logger.warning("translate_text called with empty text.")
        return text

    if target_language != "auto" and not is_valid_language_code(target_language):
        logger.warning(f"Invalid target language '{target_language}'. Falling back to default.")
        target_language = settings.GLOBAL_TARGET_LANGUAGE or "en"

    source_lang = detect_language_safe(text, target_language)

    if source_lang is None:
        return text

    if ignore_list and source_lang in ignore_list:
        logger.debug(f"Skipping translation: Source language '{source_lang}' is explicitly ignored")
        return text

    # Chunking Guard Rails
    chunks = split_text_smart(text, settings.TRANSLATION_CHUNK_SIZE)
    if len(chunks) > settings.TRANSLATION_MAX_CHUNKS:
        logger.warning(f"Message requires {len(chunks)} chunks, exceeding max of {settings.TRANSLATION_MAX_CHUNKS}.")
        return f"{text}\n\n[⚠️ Message too long for translation service]"

    translated_parts = []
    last_sentence = ""

    for i, chunk in enumerate(chunks):
        if i == 0:
            prompt = (
                f"Translate to {target_language}. Auto-detect source. Output ONLY translation.\n\n"
                f"Text to translate:\n{chunk}"
            )
        else:
            prompt = (
                f"Translate to {target_language}. Context: Previous chunk ended with '{last_sentence}'. "
                f"Ensure continuity in tone, pronouns, and style. Output ONLY translation.\n\n"
                f"Text to translate:\n{chunk}"
            )

        max_retries = 1
        current_multiplier = 1.0
        success = False

        for attempt in range(max_retries + 1):
            try:
                max_tokens = int(settings.LLM_MAX_TOKENS * current_multiplier)
                response_content = await ask_llm(prompt, task_type="translation", max_tokens_override=max_tokens)
                translated_parts.append(response_content.strip())

                # Extract the last sentence for the next chunk's context
                last_sentence_match = re.search(r'([^.!?]+[.!?]+)\s*$', response_content.strip())
                if last_sentence_match:
                    last_sentence = last_sentence_match.group(1).strip()
                else:
                    last_sentence = response_content.strip()[-100:] # fallback to last 100 chars

                success = True
                break

            except TokenExhaustedError:
                if attempt < max_retries:
                    logger.warning(f"Translation hit token limit on chunk {i+1} (attempt {attempt + 1}). Retrying.")
                    current_multiplier = 1.5
                    continue
                else:
                    logger.error(f"Translation failed on chunk {i+1} due to token exhaustion.")
                    return f"{text}\n\n[⚠️ Translation failed at part {i+1}/{len(chunks)}]"

            except TranslationError as e:
                logger.error(f"Translation failed silently on chunk {i+1}. error={str(e)}")
                return f"{text}\n\n[⚠️ Translation failed at part {i+1}/{len(chunks)}]"

            except Exception as e:
                logger.error(f"Critical error during translation API call on chunk {i+1}. error={str(e)}")
                return f"{text}\n\n[⚠️ Translation failed at part {i+1}/{len(chunks)}]"

        if not success:
            return f"{text}\n\n[⚠️ Translation failed at part {i+1}/{len(chunks)}]"

    final_translation = " ".join(translated_parts)
    return f"[{source_lang.upper()}] {final_translation}"
