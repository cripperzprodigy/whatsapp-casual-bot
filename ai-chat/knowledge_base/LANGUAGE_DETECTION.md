# Language Detection Strategy

This document details the hybrid language detection algorithm used by the auto-translation feature in `app/translation.py`.

---

## 1. Problem Statement

The `langdetect` library is unreliable for short texts (< 20 characters), particularly for Malay (`ms`) and Indonesian (`id`). Common conversational words like "mulai", "makan", "saya", and "tak" are frequently misidentified as Finnish (`fi`), Tagalog (`tl`), or English (`en`), causing auto-translation to skip when it should translate.

## 2. Hybrid Detection Algorithm

The `detect_language_safe()` function in `app/translation.py` uses a two-tier approach:

### Tier 1: Keyword Heuristic (Short Texts < 20 chars)

Before invoking `langdetect`, the function checks if the text is short (< 20 characters). If so, it tokenizes the input and compares against `COMMON_MS_ID_WORDS` — a curated set of ~80 high-frequency Malay/Indonesian words spanning pronouns, verbs, nouns, particles, and adjectives.

**Trigger condition:** ≥ 50% of tokens match the keyword set.

```text
Input: "saya nak makan"
Tokens: ["saya", "nak", "makan"]
Matches: 3/3 = 100% → Detected as 'ms'
```

If the heuristic fires, `langdetect` is completely bypassed. The standard equivalence and exact-match guards still apply (e.g., if `target_lang` is `ms`, no translation is needed).

### Tier 2: langdetect with False-Positive Guard (Longer Texts)

For texts ≥ 20 characters, the standard `langdetect` library is used with confidence thresholds (`TRANSLATION_CONFIDENCE_THRESHOLD`, default 0.70).

A **secondary guard** catches common `langdetect` false positives: if the detected language is in `_MS_ID_FALSE_POSITIVE_LANGS` (`fi`, `tl`, `so`, `sw`, `hr`, `ro`) AND the keyword heuristic also matches, the detection is overridden to `ms`.

```text
Input: "saya pergi ke rumah makan hari ini"
langdetect returns: 'fi' (confidence 0.85)
Keyword check: 7/7 tokens match → Override to 'ms'
```

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
           [SKIP]   Length < 20 chars?
                      /        \
                  [YES]       [NO]
                    |           |
             Keyword Match    langdetect()
             >= 50%?             |
              /    \         Confidence OK?
          [YES]   [NO]        /       \
            |       |      [YES]     [NO]
      Return 'ms'   |       |        |
                     |   False-Positive  [SKIP]
                     |   Guard (fi/tl?)
                     |     /       \
                     |  [YES]     [NO]
                     |    |         |
                     | Override   Standard
                     | to 'ms'   Detection
                     |    |         |
                     +----+---------+
                          |
                    Equivalence Check
                    (id ≈ ms skip)
                          |
                    Exact Match Check
                          |
                    Return detected code
```

## 4. Configuration

All detection parameters are configurable via `.env`:

| Variable | Default | Description |
|---|---|---|
| `TRANSLATION_MIN_LENGTH` | `4` | Minimum text length to attempt detection |
| `TRANSLATION_CONFIDENCE_THRESHOLD` | `0.70` | Minimum langdetect confidence to accept |
| `TRANSLATION_EQUIVALENT_LANGS` | `"id,ms"` | Comma-separated codes treated as equivalent |

## 5. Keyword Set Maintenance

The `COMMON_MS_ID_WORDS` set is defined at module level in `app/translation.py`. When adding new words:

1. Only add words that are **unambiguous** — they should not commonly appear in English or other target languages.
2. Avoid single-letter words or words shorter than 2 characters.
3. Group words by category (pronouns, verbs, nouns, particles, adjectives) for readability.

## 6. References

- ADR-027 in `ai-chat/decisions.md` — Documents the decision to use heuristic word-matching
- `app/translation.py` — Implementation source
- `app/config.py` — Settings definitions
