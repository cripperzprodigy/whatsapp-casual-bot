# Language Detection Strategies — CJK Disambiguation (LANG-FIX-002)

> **Related ADR:** ADR-039 — Language Mirroring Protocol
> **Status:** Active (Option B implemented; Option C rejected)

---

## Section 1: Overview of the CJK Detection Problem

CJK (Chinese-Japanese-Korean) language detection is a known hard problem for probabilistic n-gram models like `langdetect` because:

1. **Han Unification:** Chinese (Simplified & Traditional), Japanese Kanji, and Korean Hanja all use characters from the same **CJK Unified Ideographs** block (U+4E00–U+9FFF). From a character-set perspective, `繁體字測試` (Traditional Chinese) and `漢字テスト` (Japanese Kanji+Katakana) look identical to a statistical model that lacks script-level features.

2. **Short messages:** WhatsApp group messages are often short — 5–15 characters. `langdetect` builds n-gram profiles from context; a short string like `繁體字測試` (4 characters + 2 punctuation marks) provides insufficient signal, and the model defaults to its nearest match — which is often **Korean (ko)** due to shared Hanja in that training data.

3. **Character-set overlap:** `langdetect`'s Hangul density heuristic can trigger on *any* dense block of non-Latin characters, classifying pure Chinese as Korean with artificially high confidence (~100%).

### Example: Traditional Chinese → Korean misclassification

| Input | langdetect | Confidence | Heuristic (Option B) |
|-------|-----------|------------|----------------------|
| `繁體字測試` | `ko` | 1.000 | `zh` ✅ |
| `您好，我是一個人工智能助手` | `zh-tw` | 1.000 | `zh` ✅ |
| `안녕하세요` | `ko` | 1.000 | `ko` |
| `こんにちは` | `ja` | 1.000 | `ja` |

---

## Section 2: Option B — Heuristic Character Ratio Validation

**Status: [IMPLEMENTED]**  
**File:** `app/utils/lang_detect.py::detect_cjk_heuristics()`

### Algorithm

A **deterministic** O(n) character-scan that counts Unicode script occurrences and applies empirically-tuned threshold rules BEFORE `langdetect` is invoked.

```
For every character in text:
    if U+AC00–U+D7AF or U+1100–U+11FF  → hangul_count++
    if U+3040–U+30FF                    → kana_count++
    if U+4E00–U+9FFF or U+3400–U+4DBF  → cjk_count++

meaningful = count(alphanumeric + fullwidth space)
hangul_ratio = hangul / meaningful
kana_ratio   = kana   / meaningful
cjk_ratio    = cjk    / meaningful

if hangul_ratio > 5%   → return 'ko'
if kana_ratio   > 5%   → return 'ja'
if cjk_ratio    > 50%  → return 'zh'
                        → return None (fall through to langdetect)
```

### Unicode Ranges Used

| Block | Range | Purpose |
|-------|-------|---------|
| Hangul Syllables | U+AC00–U+D7AF | Modern Korean (가–힣) |
| Hangul Jamo | U+1100–U+11FF | Korean Jamo letters (ᄀ–ᇿ) |
| Hiragana | U+3040–U+309F | Japanese (ぁ–ゟ) |
| Katakana | U+30A0–U+30FF | Japanese (゠–ヿ) |
| CJK Unified Ideographs | U+4E00–U+9FFF | Chinese/Japanese Kanji/Korean Hanja (一–鿿) |
| CJK Extension A | U+3400–U+4DBF | Rare Chinese characters (㐀–䶿) |

### Threshold Tuning

| Threshold | Value | Rationale |
|-----------|-------|-----------|
| `_HANGUL_THRESHOLD` | 5% | Even a single Hangul character in a 10-char message triggers Korean. Korean Hangul is *never* used in Chinese text, so any presence of Hangul is a definitive signal. |
| `_KANA_THRESHOLD` | 5% | Similarly definitive — Kana never appears in Chinese or Korean text. |
| `_CJK_THRESHOLD` | 50% | More than half of meaningful characters are CJK ideographs with zero Kana/Hangul → the text is almost certainly Chinese. |

### Priority Order

1. **Hangul first** — prevents Korean with Hanja from being classified as Chinese.
2. **Kana second** — prevents Japanese Kanji from being classified as Chinese.
3. **CJK third** — catches Traditional Chinese before `langdetect` misclassifies it as Korean.

### Pros

- **Fast:** O(n) single-pass character scan with no allocations. Latency < 1ms for typical messages.
- **Deterministic:** Same input always produces the same output — no model stochasticity.
- **Zero new dependencies:** Uses only built-in `ord()` — no model files to download.
- **Mathematically precise:** Unicode ranges are internationally standardized and stable.

### Cons

- Requires maintenance if new Unicode CJK extensions are added (rare — Extension A through H are already in the base block and are rarely used in chat).
- Cannot distinguish Simplified vs Traditional Chinese (both use CJK Ideographs). This is acceptable since both map to 'zh' for our purposes.
- Thresholds (5%, 50%) were chosen empirically; edge cases with < 3 characters of mixed CJK/Latin may still fall through to `langdetect`.

---

## Section 3: Option C — Dual-Model Verification (fasttext)

**Status: [REJECTED]**

### Approach

Use `fasttext-langdetect` (based on Facebook's fastText) as a secondary model. The 176-language pre-trained model (`lid.176.bin`, ~128 MB uncompressed, ~50 MB compressed) would verify `langdetect` results for CJK inputs.

```
if langdetect → ko or ja:
    verify with fasttext
    if fasttext disagrees AND fasttext confidence > 0.80:
        use fasttext result
    else:
        use langdetect result
```

FastText uses character n-gram features which are inherently better at CJK disambiguation than `langdetect`'s word-level features.

### Pros

- Higher accuracy on ambiguous short CJK text.
- Well-tested on the LID benchmark (96.8% accuracy overall, strong CJK results).
- Would handle rare CJK Extension characters that the heuristic may miss.

### Cons

- **~50 MB model file** that must be downloaded at first run. Unacceptable for a lightweight WhatsApp bot.
- **Additional import-time latency:** fastText model loading adds ~200 ms to startup.
- **Inference latency:** ~3–10 ms per call in `predict` mode, adding > 50% to total detection time.
- **New pip dependency:** `fasttext` (via `fasttext-wheel`) or `fasttext-langdetect` adds complexity to the dependency tree.
- **Overkill:** The heuristic (Option B) solves the specific edge case with zero additional cost. Dual-model verification would duplicate effort for a problem that only manifests on a single code path (Traditional Chinese → ko).

### Decision Rationale

Option C was rejected because **Option B achieves the same CJK disambiguation accuracy with zero new dependencies, zero added latency, and deterministic results.** fastText would be worth investigating only if:

1. The bot needs to support sub-dialect distinction (Simplified vs Traditional Chinese as separate reply languages).
2. `langdetect` is replaced entirely by a faster, more accurate model.
3. Model size is acceptable (e.g., Docker deployment with pre-cached models).

For the current scope (supported languages: en, id, ms, zh), Option B is sufficient.

---

## Section 4: Detection Pipeline (After Fix)

```
User Input ("繁體字測試")
        │
        ▼
[Step 1]  Short-text guard (CJK-aware effective length)
        │  eff_len=4×3=12 ≥ 10 → proceed
        ▼
[Step 2]  CJK Heuristic Pre-Check (Option B — LANG-FIX-002)
        │  hangul=0, kana=0, cjk=3
        │  meaningful=6, cjk_ratio=0.50 → 'zh' ✅
        │
        └── Return 'zh' immediately (skip langdetect)
```

**Korean and Japanese detection paths:**
```
User Input ("안녕하세요")
        │
        ▼
[Step 2]  CJK Heuristic Pre-Check
        │  hangul=5, kana=0, cjk=0
        │  hangul_ratio=1.0 > 5% → 'ko'
        │
        └── Return 'ko' (ko not in SUPPORTED_LANGS → falls back to 'en'
                          downstream in detect_language, as expected)

User Input ("こんにちは")
        │
        ▼
[Step 2]  CJK Heuristic Pre-Check
        │  kana=5, kana_ratio=1.0 > 5% → 'ja'
        │
        └── Return 'ja' (ja not in SUPPORTED_LANGS → falls back to 'en'
                          downstream in detect_language, as expected)
```

**Non-CJK path (unchanged):**
```
User Input ("Halo, apa kabar?")
        │
        ▼
[Step 1]  Short-text guard → passes
[Step 2]  CJK Heuristic → None (no CJK chars)
        ▼
[Step 3]  Keyword heuristic → 'ms' ✅
```

---

## Section 5: Test Coverage

All CJK heuristic tests are in `tests/test_language_mirroring.py::TestCJKHeuristics`:

| Test | Input | Expected | Status |
|------|-------|----------|--------|
| `test_traditional_chinese_short` | `繁體字測試` | `zh` | ✅ |
| `test_traditional_chinese_longer` | `繁體中文是華人地區使用的語言…` | `zh` | ✅ |
| `test_simplified_chinese_still_zh` | `你好，你是谁？…` | `zh` | ✅ |
| `test_korean_hangul_detected` | `안녕하세요` | `ko` (heuristic) | ✅ |
| `test_japanese_kana_detected` | `こんにちは` | `ja` (heuristic) | ✅ |
| `test_mixed_japanese_kanji_kana` | `漢字とひらがな` | `ja` (heuristic) | ✅ |
| `test_pure_english_bypasses` | `Hello, how are you?` | `None` | ✅ |
| `test_indonesian_bypasses` | `Halo, apa kabar?` | `None` | ✅ |
| `test_empty_string_returns_none` | `""` | `None` | ✅ |
| `test_heuristic_mixed_cjk_latin` | `你好 today 天气很好` | `zh` | ✅ |
| `test_korean_with_hanja_still_ko` | `안녕하세요 學生입니다` | `ko` | ✅ |
| `test_integration_traditional_cn` | `繁體中文測試，你好世界。` | `zh` | ✅ |
