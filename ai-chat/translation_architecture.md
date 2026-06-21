# Auto-Translation Architecture & Flow

This document summarizes the end-to-end behavior of the WhatsApp Casual Bot's auto-translation system after the latest performance and reliability refactor.

## 1. Triggering Translation (The Fast-Path Guards)

When a message is received, the `app/router_webhook.py` processes it and checks if auto-translation is enabled for the chat (falling back to global defaults if unconfigured). Before querying any expensive detection APIs or translation LLMs, the message must pass through `should_translate(text, target_lang)` inside `app/translation.py`.

The fast-path sequentially checks:
1. **Length**: Is the message shorter than `TRANSLATION_MIN_LENGTH` (default: 4 chars)? If yes, skip translation. (Fixes false positives on words like "Hi", "Ok").
2. **Density**: Is the message mostly emojis, symbols, or links? (Requires > 20% alphanumeric characters). If not, skip translation.
3. **Probabilistic Detection**: Uses `langdetect.detect_langs()` to score the language.
4. **Confidence**: Is the primary language prediction confidence below `TRANSLATION_CONFIDENCE_THRESHOLD` (default: 0.70)? If yes, assume it's the target language and skip.
5. **Lexical Equivalence**: Does the detected language and target language both belong to `TRANSLATION_EQUIVALENT_LANGS` (default: `id,ms`)? If yes, treat as a match and skip.
6. **Exact Match**: Is the detected language identical to the target language? If yes, skip.

Only if ALL guards are passed does `should_translate` return `True`.

## 2. Ignore List Filtering

If `should_translate` returns `True`, the router checks the chat's explicitly ignored languages (configured via `!ignore add <code>`). 
- If the detected language matches a code on the ignore list, the translation is silently aborted.

## 3. The LLM Translation Call

If the message requires translation, `app/translation.py:translate_text` invokes the primary Unified AI Client via `ask_llm`.
- The prompt instructs the LLM to translate strictly to the ISO 639-1 `target_lang`, preserving tone, formatting, and emojis.
- The prompt also aggressively forbids conversational filler (e.g., "Here is the translation:").
- A fallback error (`MSG_TRANSLATION_ERROR`) is returned if the LLM fails or is unavailable.

## 4. Delivery

The translated text is prefixed with the detected language code (e.g., `[ES] Translated text`) and sent back to the chat using the internal Node.js Gateway. The message natively replies to the exact user's message using the `quoted_participant` and `reply_to_msg_id` attributes.

## 5. Configuration Settings

The bot's translation engine is highly tunable via `.env` (which drives `app.config.Settings`):

**Global Defaults**
- `GLOBAL_AUTO_TRANSLATE`: Default ON/OFF state for new chats.
- `GLOBAL_TARGET_LANGUAGE`: Default target (e.g., `en`).
- `GLOBAL_IGNORED_LANGUAGES`: Comma-separated list of globally ignored ISO codes.

**Sensitivity Checks**
- `TRANSLATION_MIN_LENGTH`: Character threshold for detection.
- `TRANSLATION_CONFIDENCE_THRESHOLD`: Probability score required for `langdetect` to trigger the LLM.
- `TRANSLATION_EQUIVALENT_LANGS`: Comma-separated languages treated as interchangeable.

## 6. User Commands

Users can override global settings locally within any chat using:
- `!auto on|off|global`
- `!target <code>|global`
- `!ignore add|remove|list|global <code>`
- `!t <code> <text>` (Manual translation override)
