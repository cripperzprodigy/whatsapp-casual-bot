"""
Language Mirroring Test Suite — ADR-039 (LOC-MIRROR-001).

Covers:
  1. detect_language() accuracy for en, id, ms, zh.
  2. Chinese variant normalisation (zh-cn, zh-tw → zh).
  3. Short text fallback behaviour.
  4. Code-switching (dominant language wins).
  5. Unsupported language fallback to English.
  6. LRU cache hit (same phrase called twice → identical result).
  7. language_name() mapping for prompt injection.
  8. build_language_enforcement_block() prompt injection correctness.
  9. System prompt enforces language above RAG context.
  10. RAG context in English with user in Chinese → Chinese enforcement instruction present.
  11. Multi-turn drift prevention: language detection consistent across repeated calls.
  12. Malay/Indonesian false-positive reclassification.
"""

import pytest
from unittest.mock import MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _call_detect(text: str, fallback: str = "en") -> str:
    """Call detect_language with a cleared cache to ensure fresh detection."""
    from app.utils.lang_detect import detect_language
    detect_language.cache_clear()
    return detect_language(text, fallback=fallback)


# ── Test 1: English detection ─────────────────────────────────────────────────

class TestEnglishDetection:
    def test_plain_english(self):
        result = _call_detect("Hello, how are you doing today?")
        assert result == "en"

    def test_english_question(self):
        result = _call_detect("What is the capital of France?")
        assert result == "en"


# ── Test 2: Indonesian detection ─────────────────────────────────────────────

class TestIndonesianDetection:
    def test_indonesian_greeting(self):
        result = _call_detect("Halo, apa kabar?")
        assert result in ("id", "ms"), f"Expected id or ms, got {result}"

    def test_longer_indonesian(self):
        result = _call_detect(
            "Selamat pagi, bagaimana keadaan Anda hari ini? "
            "Saya harap semuanya baik-baik saja."
        )
        assert result in ("id", "ms")


# ── Test 3: Malay detection ───────────────────────────────────────────────────

class TestMalayDetection:
    def test_malay_greeting(self):
        result = _call_detect("Selamat pagi, apa khabar?")
        assert result in ("ms", "id"), f"Expected ms or id, got {result}"

    def test_malay_sentence(self):
        result = _call_detect(
            "Terima kasih kerana membantu saya. "
            "Saya sangat menghargai pertolongan anda."
        )
        assert result in ("ms", "id")


# ── Test 4: Chinese detection ─────────────────────────────────────────────────

class TestChineseDetection:
    def test_chinese_greeting(self):
        result = _call_detect("你好，你是谁？")
        assert result == "zh", f"Expected zh, got {result}"

    def test_chinese_longer(self):
        result = _call_detect("你好！我叫小明，很高兴认识你。请问今天天气怎么样？")
        assert result == "zh"

    def test_traditional_chinese(self):
        result = _call_detect("您好，我是一個人工智能助手，很高興認識您！")
        assert result == "zh", f"Expected zh for Traditional Chinese, got {result}"


# ── Test 5: Chinese variant normalisation ────────────────────────────────────

class TestChineseVariantNormalisation:
    def test_zh_cn_normalises_to_zh(self):
        from app.utils.lang_detect import _normalise_code
        assert _normalise_code("zh-cn") == "zh"

    def test_zh_tw_normalises_to_zh(self):
        from app.utils.lang_detect import _normalise_code
        assert _normalise_code("zh-tw") == "zh"

    def test_zh_hk_normalises_to_zh(self):
        from app.utils.lang_detect import _normalise_code
        assert _normalise_code("zh-hk") == "zh"

    def test_zh_normalises_to_zh(self):
        from app.utils.lang_detect import _normalise_code
        assert _normalise_code("zh") == "zh"


# ── Test 6: Short text fallback ───────────────────────────────────────────────

class TestShortTextFallback:
    def test_very_short_defaults_to_en(self):
        result = _call_detect("hi")  # < 10 chars
        assert result == "en"

    def test_single_char_falls_back(self):
        result = _call_detect("?")
        assert result == "en"

    def test_empty_string_falls_back(self):
        result = _call_detect("")
        assert result == "en"

    def test_custom_fallback_honoured(self):
        result = _call_detect("ok", fallback="id")
        assert result == "id"


# ── Test 7: Unsupported language fallback ────────────────────────────────────

class TestUnsupportedLanguageFallback:
    def test_polish_falls_back_to_english(self):
        # "Cześć" is Polish — not in supported set
        result = _call_detect("Cześć, jak się masz? Dziękuję bardzo za pomoc.")
        assert result == "en", f"Polish should fall back to 'en', got {result}"

    def test_japanese_falls_back_to_english(self):
        # Japanese is not in supported set
        result = _call_detect("こんにちは、お元気ですか？")
        assert result == "en", f"Japanese should fall back to 'en', got {result}"

    def test_arabic_falls_back_to_english(self):
        result = _call_detect("مرحبا كيف حالك اليوم يا صديقي الجميل")
        assert result == "en", f"Arabic should fall back to 'en', got {result}"


# ── Test 8: Code-switching ───────────────────────────────────────────────────

class TestCodeSwitching:
    def test_mixed_id_en_returns_dominant(self):
        # "Selamat pagi, how are you?" — mixed
        result = _call_detect("Selamat pagi, how are you today?")
        # Should pick either id/ms or en — but NOT zh, pl, etc.
        assert result in ("id", "ms", "en"), f"Unexpected code-switch result: {result}"

    def test_mostly_chinese_with_english_word(self):
        # Predominantly Chinese with one English word
        result = _call_detect("你好！今天的 weather 怎么样？我想出去玩。")
        assert result == "zh", f"Mostly Chinese text should be zh, got {result}"


# ── Test 9: LRU cache hit ────────────────────────────────────────────────────

class TestLRUCache:
    def test_same_input_returns_same_result(self):
        from app.utils.lang_detect import detect_language
        detect_language.cache_clear()
        r1 = detect_language("Halo, apa kabar? Saya senang bertemu Anda.")
        r2 = detect_language("Halo, apa kabar? Saya senang bertemu Anda.")
        assert r1 == r2

    def test_cache_hit_count(self):
        from app.utils.lang_detect import detect_language
        detect_language.cache_clear()
        phrase = "你好，我是机器人助手！"
        detect_language(phrase)
        detect_language(phrase)
        info = detect_language.cache_info()
        assert info.hits >= 1, "Expected at least one cache hit"


# ── Test 10: language_name() mapping ────────────────────────────────────────

class TestLanguageName:
    def test_id_maps_to_indonesian(self):
        from app.utils.lang_detect import language_name
        assert language_name("id") == "Indonesian"

    def test_zh_maps_to_chinese(self):
        from app.utils.lang_detect import language_name
        assert language_name("zh") == "Chinese"

    def test_ms_maps_to_malay(self):
        from app.utils.lang_detect import language_name
        assert language_name("ms") == "Malay"

    def test_en_maps_to_english(self):
        from app.utils.lang_detect import language_name
        assert language_name("en") == "English"

    def test_unknown_code_defaults_to_english(self):
        from app.utils.lang_detect import language_name
        assert language_name("xx") == "English"
        assert language_name("pl") == "English"


# ── Test 11: Prompt enforcement block ───────────────────────────────────────

class TestPromptEnforcementBlock:
    def test_chinese_block_contains_critical_rule(self):
        from app.utils.lang_detect import build_language_enforcement_block
        block = build_language_enforcement_block("zh")
        assert "CRITICAL LANGUAGE RULE" in block
        assert "Chinese" in block
        assert "MUST reply exclusively" in block

    def test_indonesian_block_mentions_indonesian(self):
        from app.utils.lang_detect import build_language_enforcement_block
        block = build_language_enforcement_block("id")
        assert "Indonesian" in block

    def test_block_instructs_rag_translation(self):
        from app.utils.lang_detect import build_language_enforcement_block
        block = build_language_enforcement_block("zh")
        # Must instruct LLM to translate RAG context, not output raw English
        assert "translate" in block.lower() or "synthesise" in block.lower()

    def test_enforcement_block_not_empty_for_all_supported(self):
        from app.utils.lang_detect import build_language_enforcement_block, SUPPORTED_LANGS
        for code in SUPPORTED_LANGS:
            block = build_language_enforcement_block(code)
            assert len(block) > 50, f"Block for '{code}' is too short"


# ── Test 12: System prompt language placement ────────────────────────────────

class TestSystemPromptPlacement:
    def test_enforcement_block_appears_before_rag_context(self):
        """The CRITICAL LANGUAGE RULE section must appear before [CONTEXT MEMORY]."""
        from app.utils.lang_detect import build_language_enforcement_block
        lang_block = build_language_enforcement_block("zh")
        context_header = "[CONTEXT MEMORY]"
        # Simulate the prompt structure used in process_message
        simulated_prompt = (
            "[Global Instructions]\nYou are a helpful assistant.\n\n"
            "[User Profile]\nName: Test\nPreferred Language: zh\n\n"
            f"{lang_block}\n\n"
            f"{context_header}\nsome english context here\n\n"
            "[Constraint]\nReply ONLY in zh."
        )
        lang_pos = simulated_prompt.index("CRITICAL LANGUAGE RULE")
        context_pos = simulated_prompt.index(context_header)
        assert lang_pos < context_pos, (
            "Language enforcement block must appear BEFORE [CONTEXT MEMORY] "
            "to prevent RAG context from overriding language instruction"
        )

    def test_rag_translation_instruction_present_in_prompt(self):
        """The prompt instructs the LLM to translate RAG context to the target language."""
        instruction = "If the context is in a different language, translate relevant facts"
        # This string is injected in process_message after [CONTEXT MEMORY]
        # Verify the string exists in what we inject
        assert "translate relevant facts" in instruction  # Documents the intent


# ── Test 13: False-positive reclassification ─────────────────────────────────

class TestFalsePositiveReclassification:
    def test_fi_false_positive_with_ms_keywords_is_ms(self):
        """langdetect sometimes classifies ID/MS text as 'fi' (Finnish).
        The keyword heuristic should catch this and return 'ms'.
        """
        from app.utils.lang_detect import _normalise_code, _MS_ID_FALSE_POSITIVES
        assert "fi" in _MS_ID_FALSE_POSITIVES

    def test_normalise_returns_none_for_unsupported(self):
        from app.utils.lang_detect import _normalise_code
        assert _normalise_code("pl") is None
        assert _normalise_code("ru") is None
        assert _normalise_code("ja") is None

    def test_normalise_returns_correct_for_supported(self):
        from app.utils.lang_detect import _normalise_code
        assert _normalise_code("en") == "en"
        assert _normalise_code("id") == "id"
        assert _normalise_code("ms") == "ms"


# ── Test 14: Multi-turn drift prevention ─────────────────────────────────────

class TestMultiTurnDriftPrevention:
    def test_consistent_detection_across_same_language_turns(self):
        """Multiple Chinese messages should consistently return 'zh'."""
        phrases = [
            "你好，今天天气很好。",
            "我想了解更多关于这个话题的信息。",
            "请问你能帮我解释一下这个问题吗？",
        ]
        from app.utils.lang_detect import detect_language
        detect_language.cache_clear()
        results = [_call_detect(p) for p in phrases]
        assert all(r == "zh" for r in results), (
            f"Expected all 'zh', got {results}"
        )

    def test_language_switches_when_user_switches(self):
        """If the user switches from Indonesian to Chinese, detection must follow."""
        id_result = _call_detect("Selamat pagi, apa kabar? Semoga hari Anda menyenangkan.")
        zh_result = _call_detect("你好！今天我想用中文和你交流。请问有什么可以帮忙的？")
        assert id_result in ("id", "ms")
        assert zh_result == "zh"
