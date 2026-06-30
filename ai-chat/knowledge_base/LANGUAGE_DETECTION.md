# Language Detection Strategy

This document details the hybrid language detection algorithm and the **EN/ID/MS Linguistic Sphere** policy used by the auto-translation feature in `app/translation.py`.

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
