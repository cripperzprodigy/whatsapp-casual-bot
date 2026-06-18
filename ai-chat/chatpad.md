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
