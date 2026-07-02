"""
Language Detection Utility — Language Mirroring Protocol (ADR-039).

Provides a single, reliable `detect_language()` function used by the AI engine
to enforce output language mirroring.  The bot replies in the same language the
user is speaking — no drift into English or unrelated languages.

Supported languages (primary set):
    en  — English
    id  — Indonesian
    ms  — Malay
    zh  — Chinese (Simplified & Traditional, both normalised to 'zh')

Fallback: Any unsupported or undetectable language returns 'en'.

Design decisions:
    - LRU cache (maxsize=1024) keeps latency for repeated phrases to ~0ms.
    - Uses langdetect.detect_langs() (probability list) rather than detect()
      (single guess) so we can inspect confidence and handle code-switching.
    - Chinese variants (zh-cn, zh-tw, zh-hk, zh_Hans, zh_Hant) are all
      normalised to 'zh'.
    - Malay/Indonesian false-positives from langdetect (fi, tl, so, sw, hr)
      are resolved via the keyword heuristic already in translation.py.
    - Short text (<10 chars after stripping) defaults to 'en' (or a supplied
      session fallback) to avoid noisy single-word detections.

SOP compliance:
    - All public APIs carry full type hints (strict mode).
    - All configurable values use settings from app/config.py — no magic numbers.
"""

import logging
import re
from functools import lru_cache
from typing import Optional

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0  # Deterministic results

logger = logging.getLogger(__name__)

# ── Supported language set ────────────────────────────────────────────────────

SUPPORTED_LANGS: frozenset[str] = frozenset({"en", "id", "ms", "zh"})

# Full names for LLM prompt injection  (ADR-039 §4)
LANG_NAMES: dict[str, str] = {
    "en": "English",
    "id": "Indonesian",
    "ms": "Malay",
    "zh": "Chinese",
}

# Minimum detection confidence to trust the top result.
# Below this threshold we apply additional checks before committing.
_MIN_CONFIDENCE: float = 0.80

# Minimum effective text length before we attempt detection.
# CJK characters carry far more language signal per character than Latin script,
# so we weight them more heavily in the length calculation.
_MIN_TEXT_LENGTH: int = 10
_CJK_LENGTH_WEIGHT: int = 3  # each CJK char counts as 3 towards the threshold

# Chinese variant codes → unified 'zh'
_CHINESE_VARIANTS: frozenset[str] = frozenset({
    "zh-cn", "zh-tw", "zh-hk", "zh_hans", "zh_hant", "zh",
})

# CJK Unicode ranges: CJK Unified, CJK Extension A, CJK Compatibility Ideographs
_CJK_RANGES = (
    ("\u4e00", "\u9fff"),   # CJK Unified Ideographs
    ("\u3400", "\u4dbf"),   # CJK Extension A
    ("\u20000", "\u2a6df"), # CJK Extension B (surrogate pairs in CPython)
    ("\uf900", "\ufaff"),   # CJK Compatibility Ideographs
    ("\u3040", "\u309f"),   # Hiragana (Japanese — useful for distinguishing zh vs ja)
    ("\u30a0", "\u30ff"),   # Katakana
)


def _is_cjk(ch: str) -> bool:
    """Return True if the character falls in a CJK / Kana range."""
    for lo, hi in _CJK_RANGES:
        if lo <= ch <= hi:
            return True
    return False


def _effective_length(text: str) -> int:
    """Calculate effective length, weighting CJK characters more heavily.

    One CJK ideograph carries far more language signal than one Latin letter,
    so we multiply each CJK character by ``_CJK_LENGTH_WEIGHT`` when comparing
    against ``_MIN_TEXT_LENGTH``.  This ensures a 4-character Chinese phrase
    such as "你好，谢谢" (5 chars) is treated as length 15 and passes the guard.
    """
    cjk_count = sum(_CJK_LENGTH_WEIGHT for c in text if _is_cjk(c))
    non_cjk = sum(1 for c in text if not _is_cjk(c))
    return cjk_count + non_cjk

# langdetect codes known to be false-positives for Malay / Indonesian
_MS_ID_FALSE_POSITIVES: frozenset[str] = frozenset({"fi", "tl", "so", "sw", "hr", "ro"})

# Core Malay / Indonesian signal words used as an emergency fallback heuristic
# when the external skip-keywords file is unavailable.  Kept intentionally small
# to avoid false positives.  The external keyword file takes precedence.
_CORE_MS_ID_WORDS: frozenset[str] = frozenset({
    "apa", "kabar", "selamat", "pagi", "siang", "malam", "sore",
    "terima", "kasih", "bagaimana", "baik", "tidak", "yang", "dengan",
    "untuk", "anda", "saya", "kamu", "mereka", "kita", "ini", "itu",
    "ada", "sudah", "belum", "akan", "bisa", "mau", "juga", "atau",
    "halo", "hai", "ya", "iya", "kenapa", "siapa", "dimana", "kapan",
})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _normalise_code(raw: str) -> Optional[str]:
    """Map a raw langdetect code to one of the supported codes, or None."""
    lower = raw.lower().strip()

    # Chinese: any zh variant → 'zh'
    if lower in _CHINESE_VARIANTS or lower.startswith("zh"):
        return "zh"

    if lower in SUPPORTED_LANGS:
        return lower

    return None


def _is_likely_ms_id(text: str) -> bool:
    """
    Keyword-heuristic check for Malay / Indonesian text.
    Merges the external skip-keywords file with the built-in _CORE_MS_ID_WORDS
    so both sources contribute to detection — the built-in set covers common
    greetings/colloquials that may be absent from the curated external file.
    Uses ≥40% token-ratio matching to handle short phrases gracefully.
    """
    # Always start with core built-in words
    combined_keywords: set[str] = set(_CORE_MS_ID_WORDS)

    # Augment with external keyword file when available
    try:
        from app.config import load_skip_keywords
        loaded = load_skip_keywords()
        if loaded:
            combined_keywords |= loaded
    except Exception:
        pass

    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens:
        return False

    match_count = sum(1 for t in tokens if t in combined_keywords)
    return (match_count / len(tokens)) >= 0.40


# ── CJK Heuristic Validation — Option B (LANG-FIX-002) ─────────────────────
#
# Probabilistic detectors (langdetect) frequently misclassify Traditional
# Chinese as Korean because both share CJK Unified Ideographs and Hanja.
# Short messages lack sufficient n-gram context for statistical models.
#
# This deterministic pre-filter analyses Unicode character ranges to
# disambiguate Chinese (zh), Japanese (ja), and Korean (ko) before falling
# back to langdetect.  Architecture decision: Option B — lightweight,
# O(n) character-scan; Option C (fasttext dual-model) was REJECTED due to
# ~50 MB dependency and added latency.  See ADR-039 appendix and
# LANGUAGE_DETECTION_STRATEGIES.md for full rationale.

# Unicode ranges used for CJK disambiguation:
#   Hangul Syllables:   U+AC00–U+D7AF  (가–힣)
#   Hangul Jamo:        U+1100–U+11FF  (ᄀ–ᇿ)
#   Hiragana:           U+3040–U+309F  (ぁ–ゟ)
#   Katakana:           U+30A0–U+30FF  (゠–ヿ)
#   CJK Unified:        U+4E00–U+9FFF  (一–鿿)  ← covers >99 % of common usage
#   CJK Extension A:    U+3400–U+4DBF  (㐀–䶿)

# Thresholds (empirically tuned for short chat messages):
_HANGUL_THRESHOLD: float = 0.05     # > 5 % Hangul → Korean
_KANA_THRESHOLD:   float = 0.05     # > 5 % Kana   → Japanese
_CJK_THRESHOLD:    float = 0.50     # > 50 % CJK without Kana/Hangul → Chinese


def _count_meaningful(text: str) -> int:
    """Return the count of characters that carry orthographic signal."""
    return sum(1 for c in text if c.isalnum() or c in "　。")


def detect_cjk_heuristics(text: str) -> Optional[str]:
    """Determine CJK language from character-ratio analysis alone.

    Algorithm (Option B)
    --------------------
    1. Scan every character in *text* and count Hangul, Kana, and CJK
       Unified Ideograph occurrences.
    2. Compute the ratio of each script relative to meaningful characters.
    3. Priority order:
       a. Hangul ratio > _HANGUL_THRESHOLD  → 'ko'
       b. Kana   ratio > _KANA_THRESHOLD    → 'ja'
       c. CJK    ratio > _CJK_THRESHOLD     → 'zh'
       d. Otherwise                          → None (fall through to langdetect)

    Parameters
    ----------
    text:
        Raw (un-stripped) message text.

    Returns
    -------
    Optional[str]
        'zh', 'ja', 'ko', or None when the text does not contain sufficient
        CJK signal for a definitive heuristic decision.
    """
    if not text:
        return None

    hangul = 0
    kana = 0
    cjk = 0

    for ch in text:
        code = ord(ch)
        # Hangul Syllables (AC00–D7AF) and Jamo (1100–11FF)
        if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            hangul += 1
        # Hiragana + Katakana (3040–30FF)
        elif 0x3040 <= code <= 0x30FF:
            kana += 1
        # CJK Unified Ideographs (4E00–9FFF) and Extension A (3400–4DBF)
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            cjk += 1

    total = _count_meaningful(text)
    if total == 0:
        return None

    hangul_ratio = hangul / total
    kana_ratio = kana / total
    cjk_ratio = cjk / total

    # Priority: Hangul first (avoid misclassifying Korean as Chinese),
    #           Kana second (avoid misclassifying Japanese as Chinese),
    #           CJK third  (catch Traditional Chinese before it hits langdetect).

    if hangul_ratio > _HANGUL_THRESHOLD:
        logger.debug(
            f"[CJK Heuristic] hangul={hangul}/{total} ({hangul_ratio:.2f}) "
            f"→ 'ko'"
        )
        return "ko"

    if kana_ratio > _KANA_THRESHOLD:
        logger.debug(
            f"[CJK Heuristic] kana={kana}/{total} ({kana_ratio:.2f}) "
            f"→ 'ja'"
        )
        return "ja"

    if cjk_ratio > _CJK_THRESHOLD:
        logger.debug(
            f"[CJK Heuristic] cjk={cjk}/{total} ({cjk_ratio:.2f}) "
            f"→ 'zh'"
        )
        return "zh"

    logger.debug(
        f"[CJK Heuristic] ambiguous — cjk={cjk_ratio:.2f} "
        f"hangul={hangul_ratio:.2f} kana={kana_ratio:.2f} → fall-through"
    )
    return None


# ── Primary public API ────────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
def detect_language(text: str, fallback: str = "en") -> str:
    """Detect the dominant language of *text* and return a supported ISO 639-1 code.

    Algorithm
    ---------
    1. Short-text guard: text < 10 chars → return *fallback*.
    2. Keyword heuristic: if the text matches the Malay/Indonesian keyword set
       (≥50% token overlap), return 'ms' immediately — avoids the common
       langdetect false-positive where short ID/MS text is classified as Finnish.
    3. langdetect.detect_langs() → probability-ordered list.
    4. Iterate candidates by descending probability:
       a. Normalise Chinese variants → 'zh'.
       b. Reclassify known MS/ID false-positives → 'ms' when heuristic matches.
       c. Accept the first candidate that maps to a supported language.
    5. Code-switching: if the top candidate confidence < _MIN_CONFIDENCE and
       multiple languages are present, check if the second candidate resolves
       to a supported language and prefer it if it has ≥0.3 probability.
    6. No supported language found → return *fallback*.

    Parameters
    ----------
    text:
        Raw user message text.
    fallback:
        Language code to return when detection is impossible or yields an
        unsupported language.  Defaults to 'en'.

    Returns
    -------
    str
        ISO 639-1 code from SUPPORTED_LANGS, or *fallback*.
    """
    stripped = text.strip()

    # 1. Short-text guard (CJK-aware: each ideograph counts as 3 units)
    if _effective_length(stripped) < _MIN_TEXT_LENGTH:
        logger.debug(
            f"[LangDetect] Short text ({len(stripped)} chars, "
            f"eff={_effective_length(stripped)}) → fallback '{fallback}'"
        )
        return fallback

    # 1.5 CJK heuristic pre-check (LANG-FIX-002 — Option B).
    #     Must run BEFORE keyword heuristic so Traditional Chinese (which
    #     langdetect classifies as ko) is caught by character-ratio analysis.
    cjk_result = detect_cjk_heuristics(stripped)
    if cjk_result is not None:
        # Only return if the result is in our supported set; otherwise
        # fall through so langdetect has a chance to find a supported lang.
        if cjk_result in SUPPORTED_LANGS:
            return cjk_result
        logger.debug(
            f"[LangDetect] CJK heuristic → '{cjk_result}' (not in supported set) "
            f"— falling through to langdetect"
        )

    # 2. Keyword heuristic (fast-path for Malay/Indonesian)
    if _is_likely_ms_id(stripped):
        logger.debug(f"[LangDetect] Keyword heuristic matched → 'ms'")
        return "ms"

    # 3. Probability-based detection
    try:
        candidates = detect_langs(stripped)  # returns list of Language(lang, prob)
    except (LangDetectException, Exception) as exc:
        logger.warning(f"[LangDetect] Detection failed: {exc} → fallback '{fallback}'")
        return fallback

    if not candidates:
        return fallback

    # 4. Walk candidates in probability order
    top_lang = candidates[0]
    top_raw: str = top_lang.lang
    top_prob: float = top_lang.prob

    # Reclassify known false-positives via keyword heuristic
    if top_raw in _MS_ID_FALSE_POSITIVES and _is_likely_ms_id(stripped):
        logger.debug(
            f"[LangDetect] '{top_raw}' false-positive reclassified to 'ms' via heuristic"
        )
        return "ms"

    normalised = _normalise_code(top_raw)

    # 5. Code-switching: if confidence is low, check second candidate
    if (normalised is None or top_prob < _MIN_CONFIDENCE) and len(candidates) > 1:
        second = candidates[1]
        second_norm = _normalise_code(second.lang)
        if second_norm and second.prob >= 0.30:
            logger.debug(
                f"[LangDetect] Code-switch: top='{top_raw}'({top_prob:.2f}) "
                f"second='{second.lang}'({second.prob:.2f}) → '{second_norm}'"
            )
            return second_norm

    if normalised:
        logger.debug(
            f"[LangDetect] '{top_raw}'({top_prob:.2f}) → '{normalised}'"
        )
        return normalised

    # 6. Nothing matched
    logger.debug(
        f"[LangDetect] '{top_raw}'({top_prob:.2f}) unsupported → fallback '{fallback}'"
    )
    return fallback


def language_name(code: str) -> str:
    """Return the human-readable language name for prompt injection.

    Examples
    --------
    >>> language_name('id')
    'Indonesian'
    >>> language_name('xx')
    'English'
    """
    return LANG_NAMES.get(code, "English")


def build_language_enforcement_block(lang_code: str) -> str:
    """Build the CRITICAL LANGUAGE RULE system prompt block for the given code.

    This block is injected **above** RAG context in the system prompt so that
    the language instruction is prioritised over any English-language retrieved
    documents (ADR-039 §4, §5).

    Parameters
    ----------
    lang_code:
        Detected language code from detect_language().

    Returns
    -------
    str
        Formatted multi-line prompt section.
    """
    name = language_name(lang_code)
    return (
        f"[CRITICAL LANGUAGE RULE]\n"
        f"The user is communicating in {name}. "
        f"You MUST reply exclusively in {name}. "
        f"Do not switch to English or any other language unless the user "
        f"explicitly switches first.\n"
        f"If the context memory below contains information in a different language, "
        f"extract the relevant facts and synthesise your answer in {name}. "
        f"Never output raw English context verbatim when replying in {name}."
    )
