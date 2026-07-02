# Language Detection Strategy

> **Updated:** 2026-07-02 — ADR-039 Language Mirroring added a second detection module.
> There are now **two distinct detection contexts**:
> - **Translation detection** (`app/translation.py`) — determines if a message should be auto-translated.
> - **Language Mirroring detection** (`app/utils/lang_detect.py`) — determines which language the AI should *reply in*.
>
> They serve different purposes and have different supported-language sets.
> See also: [PREFERENCE_SCOPING.md](PREFERENCE_SCOPING.md) for per-user language preferences.

---

## 0. Language Mirroring Detection (ADR-039) — `app/utils/lang_detect.py`

The AI Chatty engine uses a separate, optimised module for language mirroring:

| Module | `app/utils/lang_detect.py` |
|--------|--------------------------|
| **Purpose** | Determines the language the bot should reply in |
| **Supported** | `en`, `id`, `ms`, `zh` |
| **Fallback** | `en` for all unsupported languages |
| **Chinese** | zh-cn, zh-tw, zh-hk all normalised to `zh` |
| **Caching** | LRU cache (maxsize=1024) — repeated phrases ≈ 0ms |
| **CJK guard** | Each ideograph counts as 3 effective chars for length guard |

### Prompt Injection

`build_language_enforcement_block(lang_code)` produces a `[CRITICAL LANGUAGE RULE]` section injected **above** `[CONTEXT MEMORY]` in the system prompt:

```
[CRITICAL LANGUAGE RULE]
The user is communicating in Indonesian. You MUST reply exclusively in Indonesian.
Do not switch to English or any other language unless the user explicitly switches first.
If the context memory below contains information in a different language, extract the
relevant facts and synthesise your answer in Indonesian. Never output raw English context
verbatim when replying in Indonesian.
```

This placement ensures the language constraint has higher positional priority than
any English-language RAG documents, preventing context-induced drift.

---

---

## 1. Linguistic Sphere Policy (ADR-028)

English (`en`), Indonesian (`id`), and Malay (`ms`) are treated as a **single shared linguistic sphere**. Messages detected as any of these three languages are **NEVER translated**, regardless of the group's target language setting.

This policy exists because:
- Users in multilingual groups naturally mix EN, ID, and MS and consider them mutually intelligible.
- `langdetect` is unreliable for short ms/id texts, causing false translations.
- Code-switching sentences (e.g., "I nak go to school") are natural and should not trigger translation.

**Configuration:**
```env
GLOBAL_IGNORED_LANGUAGES=en,id,ms
TRANSLATION_EQUIVALENT_LANGS=en,id,ms
```

Only truly foreign languages (Arabic, Chinese, Japanese, French, German, Spanish, etc.) trigger translation.

## 2. Hybrid Detection Algorithm

The `detect_language_safe()` function uses a three-tier approach:

### Tier 1: Keyword Heuristic (All Text Lengths)

Before invoking `langdetect`, the function tokenizes the input and compares against `COMMON_MS_ID_WORDS` — a curated set of ~80 high-frequency Malay/Indonesian words spanning pronouns, verbs, nouns, particles, and adjectives.

**Trigger condition:** ≥ 50% of tokens match the keyword set.

```text
Input: "saya nak makan"
Tokens: ["saya", "nak", "makan"]
Matches: 3/3 = 100% → Detected as ms/id
→ ms/id is in GLOBAL_IGNORED_LANGUAGES → SKIP translation
```

If the heuristic fires and the detected language is in the ignored set, `langdetect` is completely bypassed and `None` is returned (translation skipped).

### Tier 2: langdetect with False-Positive Guard

For texts where the keyword heuristic does NOT match, the standard `langdetect` library is used with confidence thresholds (`TRANSLATION_CONFIDENCE_THRESHOLD`, default 0.70).

A **false-positive guard** catches common `langdetect` misidentifications: if the detected language is in `_MS_ID_FALSE_POSITIVE_LANGS` (`fi`, `tl`, `so`, `sw`, `hr`, `ro`) AND the keyword heuristic also matches, the detection is overridden to `ms`.

### Tier 3: Ignored Languages Check

After `langdetect` returns a result, the detected language is checked against `GLOBAL_IGNORED_LANGUAGES`. If it's in the set, translation is skipped immediately. This catches cases where `langdetect` correctly identifies `en`, `id`, or `ms` on longer texts.

## 3. Detection Flow Diagram

```text
       [Incoming Text]
             |
     Length < MIN_LENGTH?
        /         \
     [YES]       [NO]
       |           |
    [SKIP]    Alphanumeric < 2?
                /       \
            [YES]      [NO]
              |          |
           [SKIP]   Keyword Heuristic
                    (COMMON_MS_ID_WORDS)
                      /        \
                  [MATCH]    [NO MATCH]
                    |           |
              ms/id in         langdetect()
              ignored?             |
              /    \         Confidence OK?
          [YES]   [NO]        /       \
            |       |      [YES]     [NO]
         [SKIP]  Return     |        |
                 'ms'    False-Pos  [SKIP]
                         Guard?
                          /   \
                       [YES] [NO]
                         |     |
                      Override Standard
                      to 'ms' Detection
                         |     |
                         +--+--+
                            |
                    In IGNORED_LANGS?
                      /          \
                   [YES]        [NO]
                     |            |
                  [SKIP]    Equivalence?
                              /      \
                           [YES]    [NO]
                             |        |
                          [SKIP]   Exact match?
                                    /     \
                                 [YES]   [NO]
                                   |       |
                                [SKIP]  TRANSLATE
                                        (foreign)
```

## 4. Configuration

All detection parameters are configurable via `.env`:

| Variable | Default | Description |
|---|---|---|
| `GLOBAL_IGNORED_LANGUAGES` | `"en,id,ms"` | Languages that are NEVER translated (linguistic sphere) |
| `TRANSLATION_EQUIVALENT_LANGS` | `"en,id,ms"` | Languages treated as mutually equivalent |
| `TRANSLATION_MIN_LENGTH` | `4` | Minimum text length to attempt detection |
| `TRANSLATION_CONFIDENCE_THRESHOLD` | `0.70` | Minimum langdetect confidence to accept |
| `TRANSLATION_SKIP_KEYWORDS_FILE` | `"data/translation_skip_keywords.txt"` | External keyword dictionary file path |

## 5. Keyword Set (External File)

Keywords are stored in `data/translation_skip_keywords.txt` (one per line, `#` for comments). The file is loaded at startup by `load_skip_keywords()` in `config.py` and cached as a `frozenset` for O(1) lookup.

**Current count:** ~172 keywords across these categories:

| Category | Examples |
|---|---|
| **Pronouns** | saya, aku, awak, kamu, dia, kami, kita, mereka, anda, beliau |
| **Verbs** | makan, minum, pergi, datang, buat, ambil, beli, jual, cari, mulai, kerja, tidur, bangun, tolong, tunggu |
| **Nouns** | orang, rumah, hari, masa, waktu, tempat, nasi, ayam, ikan, duit, wang, kereta, jalan, sekolah, kawan |
| **Particles** | tak, tidak, nak, ke, di, dan, atau, ya, lah, kan, leh, pun, dah, ada, ini, itu, jer, je, kot, gak, dong, sih |
| **Adjectives** | baik, besar, kecil, banyak, cantik, bagus, mahal, murah, cepat, lambat, sedap |
| **Greetings** | selamat, pagi, petang, malam, terima, kasih, maaf, sorry, hai |
| **Time** | sekarang, nanti, semalam, esok, lusa, tadi |
| **Location** | sini, situ, sana, dekat, jauh, atas, bawah, depan, belakang |

To expand the keyword set:
1. Edit `data/translation_skip_keywords.txt` directly
2. Add words under the appropriate category comment header
3. Restart the bot (keywords are cached at startup)
4. Only add words that are **unambiguous** — avoid words common in non-target languages

## 6. Edge Cases

| Scenario | Behavior | Rationale |
|---|---|---|
| Code-switching: "I nak go to school" | SKIP | Keyword "nak" triggers heuristic → ms/id in sphere |
| Proper nouns: "Budi pergi ke Jakarta" | SKIP | "pergi" and "ke" in keyword set |
| Ambiguous: "bisa" (can/poison) | SKIP | In context with other keywords |
| Pure Japanese: "こんにちは" | TRANSLATE | No keyword match, langdetect returns "ja" (not ignored) |
| Pure Arabic: "مرحبا" | TRANSLATE | No keyword match, langdetect returns "ar" (not ignored) |
| Short English: "ok" | SKIP | Length < MIN_LENGTH (4) |

## 7. References

- ADR-027 in `decisions.md` — Keyword heuristic decision
- ADR-028 in `decisions.md` — Linguistic sphere policy
- ADR-029 in `decisions.md` — Hierarchical control and external keyword dictionary
- `data/translation_skip_keywords.txt` — External keyword dictionary
- `app/translation.py` — Implementation source
- `app/config.py` — Settings definitions and keyword loader
