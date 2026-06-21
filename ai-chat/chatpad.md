# Chatpad

1. **Purpose:** Active conversation, debugging, and brainstorming platform for all active AI agents.
2. **Entry Lifecycle:** Upon task completion, agents SHOULD condense their working blocks into a clean summary and provide hand-off clues for the next agent.
3. **Immutability of Others' Work:** Agents may only edit or delete their *own* entries. Modifying the active blocks of other AI agents is strictly forbidden.
4. **Size Constraint:** This file MUST stay under 2000 lines. Archive older summaries to `chatpad_archive.md` to prevent context window bloat.
5. **Formatting Requirement:** Every entry MUST begin with a strict timestamp: `### [Your Agent ID] - [YYYY-MM-DD HH:MM UTC]`.

---

### [Jules] - [2026-06-18 13:04 UTC]
AI-CHAT Protocol initialization is complete. Scaffolding for multi-agent collaboration has been successfully created.

### [Jules] - [2026-06-18 13:19 UTC]
Completed implementation of the core WhatsApp bot architecture.
- Added FastAPI app with webhook routing.
- Implemented SQLite DB state for ChatSettings, Notes, Tasks, and Message Buffers.
- Implemented a unified AI client supporting local and cloud LLMs.
- Implemented command parsing, auto-translation logic, and a WhatsApp gateway HTTP client wrapper.
- Setup `docker-compose.yml`, `Dockerfile`, and `README.md` for easy deployment.

### [Jules] - [2026-06-18 13:34 UTC]
- Created `start.sh` (Linux/macOS) and `start.bat` (Windows) scripts to automatically handle Python virtual environment creation, dependency installation, and server launching.
- Updated `README.md` instructions accordingly.

### [Jules] - [2026-06-18 13:46 UTC]
- Implemented "self-awareness" and passive contact syncing.
- Added `fetch_group_metadata` to the gateway wrapper so the bot knows if it is an admin and knows the group name.
- Added `Contact` and `GroupMember` tables to the SQLite database.
- Created `app/contact_sync.py` to passively ingest user details from webhooks and continuously export `contacts.csv` and `summary.md` to `exports/groups/<id>/`.
- Completely rewrote `README.md` to be a comprehensive guide.

### [Jules] - [2026-06-18 14:04 UTC]
- Updated configuration to allow `GLOBAL_AUTO_TRANSLATE` and `GLOBAL_TARGET_LANGUAGE` to be set in `.env`.
- Modified `ChatSettings` model so per-chat configurations fall back to the `.env` settings if not explicitly overriden.
- Updated `!auto` and `!target` commands to support a `global` argument to reset the local chat config to the global defaults.

### [Jules] - [2026-06-18 14:19 UTC]
- Pivoted from an assumed external gateway to a custom, integrated Node.js microservice (`whatsapp-service/`) using `whatsapp-web.js`.
- This replicates the exact OpenClaw linked-device experience: serving a QR login directly from our app, persisting the session in `.wwebjs_auth/`, and easily resetting sessions via an HTTP endpoint.
- Added `WHITELISTED_CHATS` to `.env` and implemented a security filter to drop webhooks from unauthorized chats.
- Updated `docker-compose.yml` and the OS shell scripts to effortlessly start both the Python API and the Node.js service together.
- Fully updated the README and Architectural files to reflect this major structural pivot.

### [Jules] - [2026-06-18 14:30 UTC]
- Enhanced `start.sh` and `start.bat` to perform pre-flight checks (detecting if `venv` or `node_modules` exist).
- If dependencies are missing, the scripts will now interactively ask the user for permission to install them.
- Improved terminal UX by adding clear status logging markers.

### [Jules] - [2026-06-18 14:43 UTC]
- Extended the global settings cascade by adding `GLOBAL_IGNORED_LANGUAGES` to the `.env` logic.
- Updated the database schema so `ignored_languages` can be nullable (indicating fallback to global).
- Updated the webhook router and `!ignore` commands to comprehensively handle this logic.
- Documented the entire explicit vs global settings cascade natively in the `README.md`.

### [Jules] - [2026-06-18 14:50 UTC]
- Audited the auto-translation flows for reliability.
- Tuned the LLM translation prompt in `app/translation.py` to be much stricter against returning conversational filler (e.g. "Here is the translation...").
- Fixed `!t auto` in `app/commands.py` so it properly cascades to `GLOBAL_TARGET_LANGUAGE` if the chat setting is `None`.


### [Jules] - [2026-06-18 15:04 UTC]
- Updated `README.md` to include a clear visualization example explaining the passive auto-translation logic to the end user.

### [Jules] - [2026-06-18 16:11 UTC]
- Updated the auto-translation logic to natively reply/quote the original WhatsApp message it is translating.
- Enhanced the `whatsapp-service` internal Node.js API to accept a `quoted` option and proxy it to `whatsapp-web.js`.
- Enhanced `send_text_message` in Python to format the message ID securely for the Node.js service.

### [Jules] - [2026-06-20 12:00 UTC]
- Added a persistent permission system with Owner/Admin/Public roles stored in `bot_admins`.
- Implemented `!owner` and `!admin` management commands, `!broadcast`, `!stats`, `!export ledger`, and dynamic `!help` visibility.
- Added a hybrid bootstrap strategy: `BOT_OWNER_ID` env owner auto-creation, and a one-time private-chat `!claim_ownership` as fallback.

### [Jules] - [2026-06-19 08:18 UTC]
- Restructured the Contact Synchronization engine into an "Isolated Ledger" pattern.
- Removed `Contact` and `GroupMember` tables in favor of a single `GroupContactLedger` with composite primary keys (`chat_id`, `phone_number`), ensuring contact data is strictly siloed per chat group.
- Implemented an `Active Sweep` function (`process_active_sweep`). Now, the moment a group is seen, all participants are bulk-inserted into the DB to capture "lurkers" who never speak.
- Added `is_active` flags. We no longer delete contacts when they leave; we mark them inactive to preserve historical logs.
- Optimized the disk I/O in `export_group_contacts` to throttle CSV/MD file writing to a maximum of once per 60 seconds per group.
- Restored and updated the `Contact Exports` section of the `README.md` to reflect these advanced features.

### [Jules] - [2026-06-19 08:44 UTC]
- Replaced the hardcoded README `.env` block with a dedicated `.env.example` file.
- The `.env.example` file is strictly configured out-of-the-box to interface with LM Studio, using specific `google/gemma-4-12b-qat` mapping and OpenAI-compatible endpoints to ensure the translation logic seamlessly routes to the local model.
- Added `LOCAL_LLM_API_KEY` to `app/config.py` to allow passing the local token natively to the `AsyncOpenAI` client.

### [Jules] - [2026-06-19 16:43 UTC]
- Conducted an architecture, security, and stability audit of the `fix/critical-refactor-and-stability` branch.
- Validated that the HTTP 422 webhook bug was correctly mitigated.
- Approved and fully merged the branch into `main`.

### [Jules] - [2026-06-19 17:39 UTC]
- Enhanced `start.sh` to explicitly verify and install OS-level libraries strictly required by Puppeteer (headless Chrome) under Debian/Ubuntu systems (`libgbm1`, `libatk1.0-0`, `libnss3`, etc.).
- The script now interactively prompts the user before attempting to run the large `sudo apt-get install` array, preventing silent crashes when booting `whatsapp-web.js` on clean VMs.

### [Jules] - [2026-06-19 09:15 UTC]
- Comprehensively updated `ai-chat/ARCHITECTURE.md` and `ai-chat/PROJECT_HISTORY.md` for future agents.
- Added ASCII diagrams visualizing the dual-runtime architecture and the Two-Pronged Contact Sync data flow.
- Fully documented the Database Schemas (`ChatSettings`, `GroupContactLedger`).
- Summarized the historical evolutionary pivots (Node.js migration, Isolated Ledgers, and Translation cascades) so future agents understand *why* the codebase is structured this way.

### [Jules] - [2026-06-19 10:48 UTC]
- Executed a major refactor of the AI logic to use a "Single-Client Architecture".
- Stripped out all hardcoded Local/Cloud separation variables from `app/config.py` and `app/ai_client.py`.
- The bot now elegantly uses one `AsyncOpenAI` client pointing to three unified `.env` variables (`LLM_ENDPOINT`, `LLM_API_KEY`, `DEFAULT_MODEL_NAME`), exploiting the fact that Local instances (LM Studio) and Cloud instances (OpenAI) conform to the same API standard.
- Updated `ARCHITECTURE.md`, `PROJECT_HISTORY.md`, and `README.md` to document this vastly cleaner pattern.

### [Jules] - [2026-06-19 11:10 UTC]
- Further enhanced `start.sh` to deal with clean Linux VM environments (like Ubuntu).
- The script now dynamically checks if `node`, `npm`, or `python3-venv` are entirely missing from the OS.
- If they are missing and `apt` is available, it interactively prompts the user to automatically install the underlying OS packages via `sudo apt install` before attempting to boot the bot dependencies.

### [Antigravity] - [2026-06-19 15:12 UTC]
Executed a 16-issue critical refactor and stability pass across all Python and Node.js modules.
Worked under full AI-CHAT SOP protocol compliance (read all 5 docs before writing any code).

**Phase 1 — Critical Blockers (bot was non-functional before these):**
- **Issue 1:** Made `instance` field `Optional` in `WhatsAppWebhookPayload` (was causing HTTP 422 on every webhook, bot received zero messages). Also patched Node.js to send `instance: 'whatsapp-web-js'`.
- **Issue 2:** Changed `if` → `while` in `add_message_to_buffer` to properly drain overflow during message bursts. Added `if not oldest: break` guard.
- **Issue 3:** Fixed `detect_language` to strip whitespace before validation and added `FULL_NAME_TO_CODE` mapping for 20 common languages so LLM responses like `"English"` correctly return `"en"`.

**Phase 2 — Stability:**
- **Issue 4:** Replaced all 8 × `datetime.utcnow()` with `datetime.now(timezone.utc)` in `state.py` and `contact_sync.py`.
- **Issue 5:** Added `@model_validator(mode='after')` to `Settings` to `logger.warning` on empty `BOT_NUMBER` / `LLM_API_KEY` at startup.
- **Issue 6:** Wrapped `init_db()` in `try/except` in `startup_event`; logs `CRITICAL` and re-raises on failure.
- **Issue 7:** Replaced magic string `"false_"` with named constant `_INCOMING_MSG_PREFIX` and improved docstring.

**Phase 3 — Architecture:**
- **Issue 8:** Integrated `slowapi` rate limiter on `/webhook/whatsapp` (configurable via `WEBHOOK_RATE_LIMIT`, default 60/min). System/health routes are exempt.
- **Issue 9:** Added `GET /health` endpoint to `router_system.py` — checks DB (`SELECT 1`) and gateway reachability; returns `{status, db, gateway}` with HTTP 503 on degradation.
- **Issue 10:** Replaced hardcoded `"exports/groups/"` with `settings.CONTACTS_EXPORT_DIR` (configurable via `.env`).
- **Issue 11:** Replaced generic `except Exception` in `process_message` with structured handlers for `httpx.HTTPError` (warning), `SQLAlchemyError` (error), and `Exception` (error + traceback).

**Phase 4 — Code Quality:**
- **Issue 12:** Reformatted all files to ≤80-char lines.
- **Issue 13:** Added `-> None` return types to `add_message_to_buffer`, `update_contact`, `process_active_sweep`, `export_group_contacts`, `handle_command`.
- **Issue 14:** Replaced magic numbers: `30→SUMMARY_MESSAGE_LIMIT`, `1024→LLM_MAX_TOKENS`, `60→ROSTER_EXPORT_THROTTLE_SECONDS`, `0.3/0.7→_TEMP_PRECISE/_TEMP_CREATIVE`.
- **Issue 15:** Wrapped `int(args[1])` in `!task done` with `try/except ValueError` → user-friendly error message instead of generic crash.
- **Issue 16:** Replaced `logging.basicConfig` with `logging.config.dictConfig` using structured format `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. Honouring `LOG_LEVEL` env var.

**Phase 5 — Tests (SOP required):** Created `tests/test_fixes.py` with 11 unit tests covering Issues 1, 2, 3, 15.

**Handoff clues for next agent:**
- The `_INCOMING_MSG_PREFIX` for quoted messages (`false_`) may need updating if group reply quoting is broken — see `whatsapp_gateway.py`.
- `CONTACTS_EXPORT_DIR` defaults to `"exports/groups"` — Docker users should mount this as a volume.
- The `/health` endpoint pings the Node.js gateway with a 3-second timeout — adjust if gateway is slow.
- `tests/test_fixes.py` uses `pytest-asyncio` — run with `pytest tests/ -v`.


### [Jules] - [2026-06-19 17:39 UTC]
- Enhanced `start.sh` to explicitly verify and install OS-level libraries strictly required by Puppeteer (headless Chrome) under Debian/Ubuntu systems (`libgbm1`, `libatk1.0-0`, `libnss3`, etc.).
- The script now interactively prompts the user before attempting to run the large `sudo apt-get install` array, preventing silent crashes when booting `whatsapp-web.js` on clean VMs.

### [Jules] - [2026-06-19 18:14 UTC]
- Fixed a bug in the `start.sh` Puppeteer dependency installer where `libasound2` was causing an installation error on modern OS's like Ubuntu 24.04 (where it was replaced by a virtual package).
- `start.sh` now dynamically checks `apt-cache` and uses `libasound2t64` if available, gracefully supporting both old and new Linux distributions.

### [Jules] - [2026-06-19 22:59 UTC]
- Audited the latest changes merged to `main` by another agent, which included improvements to `!a` general AI queries, timezone-aware datetimes in `state.py`, robust web search responses for missing live access, and test expansions.
- Validated that `pytest` completes successfully on all 15 tests.

### [GitHub Copilot] - [2026-06-20 00:00 UTC]
Applied a set of stability and UX fixes for the WhatsApp bot.
- Fixed timezone mismatch in contact roster export throttling by making `ChatSettings.last_roster_export_at` UTC-aware and normalizing legacy naive timestamps in `app/contact_sync.py`.
- Updated auto-translation behavior so replies quote the original message and send only the translated text.
- Added support for passing the group participant ID into the internal reply quoting path so quoted replies work more reliably in groups.
- Hardened the `!search` command prompt in `app/commands.py` to avoid misleading live-search claims and to show a clear fallback message when live search is unavailable.
- Documented the latest fixes across `ai-chat/README.md`, `ARCHITECTURE.md`, and `PROJECT_HISTORY.md`.

### [Antigravity] - [2026-06-21 14:18 UTC]
- Fixed a false-negative Python installation verification bug in `install_deps.sh` where `MISSING_PKGS` was not cleared after a successful source compilation.
- Refactored the verification block in `start.sh` to dynamically use `$PYTHON_BIN` and functionally test binary execution, `sys.version_info` matching 3.12, `import sqlite3`, and `import venv`.
- Standardized the source compilation target prefix in `start.sh` to `$HOME/.local` so the binary aligns exactly with `$HOME/.local/bin/python3.12`.
