# AI-CHAT Protocol & Collaboration Hub

The `ai-chat/` folder is the central nervous system for all autonomous agents operating in this repository. It serves as a strict **collaboration workspace** where agents exchange information, stay up-to-date with active implementation plans, track bugs, and document architectural decisions to drive progressive codebase improvements.

Welcome. Any newly attached AI agent must read the workspace documents in this exact execution order before modifying any system code:

1. `SOP.md`
2. `agents/AGENT_REGISTRY.md`
3. `chatpad.md`
4. `knowledge_base/ARCHITECTURE.md`
5. `PROJECT_HISTORY.md`

---

## Latest ai-chat Updates (2026-06-21)

- **Chatty Human-Simulation**: Integrated async debouncing and throttling into the Chatty webhook to simulate human typing delays, completely configurable via `.env` and `!chatty_delay`.
- **Dynamic Token Boundaries**: Lifted hardcoded token limits across `translation.py` and `ai_client.py` allowing proper utilization of high-context 131k local models.
- **Robustness Upgrades**: Added hierarchical semantic chunking for massive translation texts to prevent data loss.
- Applied a timezone-aware fix for `ChatSettings.last_roster_export_at` to ensure contact roster export throttling compares UTC-aware timestamps consistently.
- Updated auto-translation replies so the bot quotes the original WhatsApp message and provides only the translated text.
- Added strict Chatty vs Auto-Translation mutual exclusion: messages processed by Chatty are now blocked from being auto-translated in the same webhook event.
- Improved group reply quoting by passing participant metadata into the internal gateway when replying to quoted group messages.
- Added a persistent Owner/Admin permissions system with dynamic `!help` output and bootstrap ownership claim flow.

## Chatty Feature
We recently integrated a highly sophisticated long-term memory conversational assistant called `!chatty`. See [CHATTY_FEATURE.md](./knowledge_base/CHATTY_FEATURE.md) for architectural details and execution flow.

## Backup & Restore Utilities
For migrating the bot to new machines without losing active WhatsApp sessions or local RAG memory, see [BACKUP_RESTORE_FEATURE.md](./knowledge_base/BACKUP_RESTORE_FEATURE.md).
\n- [AGENTIC_SEARCH_FEATURE.md](knowledge_base/AGENTIC_SEARCH_FEATURE.md): Deep dive into the multi-hop Agentic Search (!s) workflow, architecture, and feature toggles.
