# AI-CHAT Protocol Welcome Directive

Welcome. Any newly attached AI agent must read the workspace documents in this exact execution order before modifying any system code:

1. `SOP.md`
2. `AGENT_REGISTRY.md`
3. `chatpad.md`
4. `ARCHITECTURE.md`
5. `PROJECT_HISTORY.md`

---

## Latest ai-chat Updates (2026-06-20)

- Applied a timezone-aware fix for `ChatSettings.last_roster_export_at` to ensure contact roster export throttling compares UTC-aware timestamps consistently.
- Updated auto-translation replies so the bot quotes the original WhatsApp message and provides only the translated text.
- Improved group reply quoting by passing participant metadata into the internal gateway when replying to quoted group messages.
- Hardened `!search` behavior with a safer prompt that avoids claiming live web access, reduces truncated answer risks, and provides a clear fallback message when search access is unavailable.
- Documented the latest fixes and operational behavior across `ARCHITECTURE.md`, `PROJECT_HISTORY.md`, and `chatpad.md`.
