# Architectural Decisions

- **Token Limits for Reasoning Models:** Decided to use 8192 default tokens and strict prompting for high-context local reasoning models. This prevents models from exhausting tokens on verbose reasoning tracks.
- **Custom Exceptions:** Introduced `TokenExhaustedError` and `TranslationError` instead of returning dataclasses from `ask_llm`. This enables precise error handling and clean retry mechanisms.
