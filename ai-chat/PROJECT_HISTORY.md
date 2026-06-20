# Project History

*Future Agents: Log historical context and state changes here. Document major design decisions, pivots, and the engineering rationale behind the architecture (e.g., database selection, caching strategies) to preserve the core design philosophy for future maintainers.*

## Log
- **2026-06-18:** Initialized the WhatsApp Casual Bot architecture. 
  - **Framework:** Chose FastAPI for fast async Python logic, supplemented by an internal Node.js microservice (`whatsapp-service/`) utilizing `whatsapp-web.js`.
  - **Database:** Used SQLite with SQLAlchemy for simple, file-based persistence suited for small group chats. Ensures state is portable and easy to query without managing a separate database server.
  - **AI Abstraction:** Evolved from maintaining separate Cloud/Local LLM logic to a pure Single-Client Architecture (`app/ai_client.py`). Because Local engines (LM Studio, vLLM, Ollama) and Cloud engines (OpenAI) adhere to the same API standard, the bot relies on a single configuration block (`LLM_ENDPOINT`, `LLM_API_KEY`, `DEFAULT_MODEL_NAME`), completely decoupling the logic from the provider.
  - **Node.js Gateway Migration:** Originally assumed an external gateway like Evolution API. Pivoted to building a native, tightly-coupled Node.js microservice to perfectly replicate the OpenClaw QR-login, session persistence, and session-reset flows natively in the repo.
  - **Contact Sync Evolution:** Initially built generic `Contact` and `GroupMember` tables using a purely passive sync model. Pivoted to an **Isolated Ledger** pattern (`GroupContactLedger`), combining an initial "Active Sweep" (fetching the full roster immediately upon joining a group) with continuous "Passive Updates" to securely silo names and statuses per group without ever deleting historical records.
  - **Auto-Translation Cascade:** Evolved from hardcoded per-chat translation toggles to a robust configuration cascade (Explicit Chat Settings -> `.env` Global Settings -> Disabled). Added `!auto global` fallback commands and tuned the prompt instructions to severely punish LLM conversational filler. Added native WhatsApp quoting so translations visually reply to the original message.
- **2026-06-19 (Antigravity):** Critical refactor pass — addressed 16 identified issues across 4 phases.
  - **Blocker Fix (Issue 1):** Discovered that the Python `WhatsAppWebhookPayload` model required `instance: str` as a mandatory field, but the Node.js gateway never sent it. This caused HTTP 422 on every single incoming webhook, meaning the bot had never successfully processed a message. Fixed by making `instance: Optional[str] = None` and having Node.js send `instance: 'whatsapp-web-js'`.
  - **Memory Fix (Issue 2):** The message buffer pruning logic used `if count > size` (deletes only one per call). A burst of messages could overflow the buffer indefinitely. Changed to a `while` loop with a guard for empty results.
  - **LLM Output Robustness (Issue 3):** Language detection was fragile — LLMs sometimes return `" en "` (spaces) or `"English"` (full name), both of which were incorrectly treated as `"unknown"`. Added whitespace stripping and a `FULL_NAME_TO_CODE` fallback map for 20 languages.
  - **Deprecated API (Issue 4):** Replaced all 8 occurrences of `datetime.utcnow()` with `datetime.now(timezone.utc)` ahead of Python 3.12+ removal.
  - **Architecture additions:** Added `GET /health` endpoint (DB + gateway check), `slowapi` rate limiting on the webhook endpoint (configurable), and made the contact export directory configurable via `CONTACTS_EXPORT_DIR`.
  - **SOP Compliance:** Per SOP testing requirement, created `tests/test_fixes.py` with 11 unit tests. All five AI-CHAT protocol documents were read before code changes began.
- **2026-06-20:** Applied multiple stability and UX fixes.
  - Ensured `ChatSettings.last_roster_export_at` is stored and compared as UTC-aware `DateTime(timezone=True)`.
  - Added normalization for existing naive timestamps before throttle comparisons in `app/contact_sync.py`.
  - Improved auto-translation replies to quote the original message and send only the translated text.
  - Enhanced group reply quoting by passing `quoted_participant` metadata into the internal gateway when replying to quoted group messages.
  - Added the public `!a <text>` command for general AI responses and documented it in `!help`.
  - Added a persistent Owner/Admin permission system backed by a new `bot_admins` table, with dynamic `!help` output, an environment-based bootstrap owner, and a private-chat `!claim_ownership` fallback.
  - Hardened the `!search` command prompt to avoid claims of live web search access and to provide a helpful fallback when search access is unavailable.
  - Added contact export enhancements: Updated `GroupContactLedger` to use a `jid` composite primary key, added `db_migration.py` for SQLite table migrations, sanitized export folder names, included extra fields in CSV exports, and implemented role-restricted `!contacts list` and `!contacts global` admin commands.
  - Updated `ai-chat` documentation and agent registry to log the active fix.

