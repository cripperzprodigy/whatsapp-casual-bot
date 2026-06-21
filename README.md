# WhatsApp Casual Bot

A highly capable, passive WhatsApp bot built with Python and FastAPI, designed specifically for small private groups. It provides powerful AI translation, an assistant mode for tasks/notes, and silent contact synchronization to maintain an offline roster.

## Core Features

- **Native QR Login:** Replicates the seamless OpenClaw QR-login and linked-device experience without relying on heavy external gateways.
- **Auto-Translation:** Automatically detect and translate incoming messages to a default language (e.g., all messages translated to English). Configurable globally or per group.
- **Assistant Tools:** Generate summaries of recent group chats using AI, assign tasks, and write notes.
- **Unified AI Architecture:** Configure a single, OpenAI-compatible AI endpoint. Easily switch between Local AI (LM Studio, Ollama) and Cloud AI (OpenAI, Groq) directly via the `.env` file without changing code.
- **Isolated Roster Ledgers:** Maintains a completely isolated contact ledger per group. If a user joins Group A, their name and details are tracked completely independently of Group B. The bot automatically sweeps the entire group upon joining to build the ledger, passively updates it as users speak (never deleting anyone), and silently exports beautifully formatted CSV and Markdown rosters to `exports/groups/<group_id>/` (throttled for performance).
- **Security Whitelist:** Configure exactly which chats the bot is allowed to interact with.

---

## 🚀 Setup & Installation

The bot relies on a Python (FastAPI) backend for logic, and a lightweight internal Node.js microservice (`whatsapp-service/`) to handle the WhatsApp Web QR connection using `whatsapp-web.js`.

### Option 1: Quick Launch Scripts (Recommended)

Make sure you have both **Python 3.10+** and **Node.js 18+** installed on your system.

1. Clone the repository.
2. Setup your `.env` file (see the Configuration section below).
3. Run the OS-specific launch script. It will automatically setup both the Python environment and the Node.js service.

**Linux / macOS:**
```bash
./start.sh
```

**Windows:**
```cmd
start.bat
```

### Option 2: Docker Compose

If you prefer containerization (this handles the Node.js and Python dependencies for you automatically):
```bash
docker-compose up -d --build
```

---

## 📱 Linking to WhatsApp via QR

Once the servers are running, you need to link the bot to your WhatsApp account:

1. Open your browser and go to `http://localhost:8000/whatsapp/qr`.
2. Wait a few seconds for the QR code to appear.
3. Open WhatsApp on your phone -> Settings -> Linked Devices -> Link a Device.
4. Scan the QR code on your screen.

**Session Persistence:** The session keys will be saved securely to the `.wwebjs_auth/` folder. If you restart the bot, it will instantly reconnect without needing to scan the QR code again.

**Resetting:** If you ever need to log out and link a different number, simply run an HTTP POST to `http://localhost:8000/whatsapp/reset-session` or delete the `.wwebjs_auth/` folder manually.

**Health Check:** A readiness endpoint is available at `http://localhost:8000/health`. It checks the database and gateway connectivity and is suitable for use in Docker `healthcheck` directives.

---

## ⚙️ Configuration (`.env`)

To configure the bot, simply rename `.env.example` to `.env` and fill in your details. 

If you want to bootstrap an initial bot owner without using the claim flow, set `BOT_OWNER_ID` to a WhatsApp JID like `1234567890@s.whatsapp.net`.


The repository includes a ready-to-go template designed perfectly for **LM Studio** and Local AI models (like Gemma, Llama, etc.).

If you are using LM Studio:
1. Start the Local Server in LM Studio.
2. Note your IP address, Port, and the Model Name you have loaded.
3. Open the `.env` file and set `LLM_ENDPOINT`, `LLM_API_KEY`, and `DEFAULT_MODEL_NAME` to match
   what LM Studio is broadcasting (e.g. `LLM_ENDPOINT=http://localhost:1234/v1`).
4. If your local server requires no key, set `LLM_API_KEY=lm-studio`.

*See `.env.example` for a complete breakdown of every variable.*

---

## 🛠 Commands Reference

Type `!help` in the WhatsApp chat to see the list of available commands.

### Translation & Language

**How Auto-Translation Works (Visualization):**
Imagine your `.env` is configured as:
`GLOBAL_AUTO_TRANSLATE=True`, `GLOBAL_TARGET_LANGUAGE=en`, and `GLOBAL_IGNORED_LANGUAGES=en,id`.
Here is how the bot passively reacts to messages in your WhatsApp group:
* **User A:** *"Hola, ¿cómo estás?"* (Spanish) -> The bot detects Spanish (`es`), sees it's not ignored, and replies: `[ES] Hello, how are you?`
* **User B:** *"Saya baik-baik saja"* (Indonesian) -> The bot detects Indonesian (`id`), sees it on the ignore list, and **stays silent**.
* **User C:** *"That's great to hear!"* (English) -> The bot detects English (`en`), sees it on the ignore list (and it's the target language anyway), and **stays silent**.

**Understanding the cascade:** Any settings changed via the commands below only apply to the specific group or chat they are sent in. If you want a chat to stop using its custom settings and fall back to the `.env` file's `GLOBAL_` variables, use the `global` arguments.

- `!auto on|off|global` - Toggle auto-translation explicitly for the chat, or reset it to the global configuration.
- `!target <lang>|global` - Set the default target language for the chat, or reset it to the global configuration.
- `!ignore add|remove <lang>` - Add or remove explicit languages from the auto-translate ignore list for this chat.
- `!ignore global` - Reset the ignore list to use the `GLOBAL_IGNORED_LANGUAGES` environment configuration.
- `!ignore list` - Show explicitly ignored languages, or indicate if it's following the global config.
- `!t <lang> <text>` - Manually translate text to a specific language.
- `!t auto <text>` - Manually translate text to the default target language.
- `!a <text>` - Ask the AI any general question or request.

### Group Assistant
- `!summary [short|full]` - Uses the AI to summarize the last 30 messages in the group.
- `!search <query>` - Ask the AI to perform a simulated web search to answer a query.
- `!task add <desc>` - Add an open task.
- `!task list` - List open tasks.
- `!task done <id>` - Mark a task as completed.
- `!note add <text>` - Add a permanent note.
- `!note list` - List all notes.

### Permission System
The bot supports three roles:
- **Public:** available to anyone.
- **Admin:** elevated privileges for maintenance commands.
- **Owner:** full control, including role management and lifecycle commands.

#### Public commands
- `!help` - Shows commands available to your current role.
- `!ping` - Check whether the bot is responsive.
- `!a <text>` - Ask the AI any general question or request.
- `!t <lang> <text>` - Translate text to a specific language.
- `!t auto <text>` - Translate text to the chat's default target language.
- `!summary [short|full]` - Summarize recent messages via AI.
- `!search <query>` - Simulate a web search answer.
- `!task add <desc>` / `!task list` / `!task done <id>` - Create, list, and complete tasks.
- `!note add <text>` / `!note list` - Add and view notes.
- `!ignore list` - View the chat's currently ignored languages.

#### Admin + Owner commands
- `!auto on|off` - Enable or disable auto-translation for the chat.
- `!auto global` - Reset this chat's auto-translate setting to the global `.env` configuration.
- `!target <lang>` - Set the chat's default target language for auto-translation.
- `!target global` - Reset this chat's target language to the global `.env` configuration.
- `!ignore add|remove <lang>` - Manage the chat-level ignored-language list.
- `!ignore global` - Reset the chat's ignored-language list to the global `.env` configuration.
- `!broadcast <message>` - Broadcast a message to all active chats.
- `!stats` - Show system statistics.
- `!export ledger` - Export the active contact ledger to CSV.
- `!contacts list` - View active contacts in the current group.
- `!pm @user <text>` - Send a direct message to a specific user.
- `!pm group <text>` - Send a direct message to all members in the current group.

#### Owner-only commands
- `!contacts global` - View a global summary of all active contacts across all groups.
- `!pm global <text>` - Send a direct message to all members across all groups.
- `!pm flood limit|interval <val>` - Update PM flood control settings.
- `!owner grant <jid>` - Grant owner privileges.
- `!owner revoke <jid>` - Revoke owner privileges.
- `!owner list` - Show active owners.
- `!owner transfer <jid>` - Transfer ownership to another user.
- `!admin grant <jid>` - Grant admin privileges.
- `!admin revoke <jid>` - Revoke admin privileges.
- `!admin list` - Show active admins.
- `!shutdown` / `!restart` - Control the bot process lifecycle.

#### Bootstrap ownership
- `!claim_ownership` - Available to anyone in a private chat only when no owner exists yet. Use this to claim the initial owner role if `BOT_OWNER_ID` is not set.

---

## 📁 Contact Exports

If `AUTO_SYNC_CONTACTS` is enabled, the bot employs an advanced **Isolated Ledger System**.

1. **Active Sweep:** The moment the bot receives a message in a new group, it hits the WhatsApp gateway, pulls the full participant list, and instantly builds a full database ledger for that specific group (even for lurkers who haven't spoken).
2. **Passive Updates:** As people send messages over time, the bot securely updates their `last_seen` timestamp and their display name *only within the context of that specific group*.
3. **No Deletions:** If someone leaves the group, they are simply marked as `Inactive` so you never lose the historical record of who was there.
4. **Throttled Exports:** To maintain high performance during busy chats, the bot will automatically write changes to your filesystem (maximum once per minute).

It exports two files per group in the directory configured by `CONTACTS_EXPORT_DIR` (default: `exports/groups/<group_id>_<sanitized_group_name>/`):
- `contacts.csv` - Includes Group ID, Group Name, JID, Phone Number, Name, Admin Status, and Active Status. Ideal for importing into Excel or Google Contacts.
- `summary.md` - A neat Markdown overview showing the group name, total members, active members, and a table of synced users.

---

## ⚡ Critical Configuration & Backup

### Important Files to Back Up

As the bot owner, these files contain irreplaceable data. **Back them up regularly:**

1. **`bot.db`** (SQLite database - **CRITICAL**)
   - Contains all ownership and admin role assignments
   - Stores chat settings (auto-translation toggles, target languages, ignored languages)
   - Holds all tasks, notes, and message buffers
   - **Location:** Project root directory
   - **Size:** Grows over time as the bot accumulates chat history
   - **Backup strategy:** Copy before VM reboots, version control backups before major updates

2. **`.env`** (Configuration file)
   - Stores your LLM endpoint, API keys, and global translation settings
   - Contains `BOT_OWNER_ID` (if set) for bootstrap ownership
   - **⚠️ WARNING:** Never commit this file to git. Keep it private and version-controlled separately (e.g., in a secure password manager or encrypted backup)
   - **Backup strategy:** Store in a secure, encrypted location outside the repository

3. **`.wwebjs_auth/`** (WhatsApp session directory)
   - Contains encrypted session tokens for your linked WhatsApp account
   - **⚠️ WARNING:** Keep this directory completely private—do not share or expose
   - **Location:** Project root directory
   - **Backup strategy:** Optional (if you need to migrate to a different machine and avoid re-linking)

### Configuration Persistence Across Restarts

**Ownership and Admin Roles:** All role assignments are stored in `bot.db` and persist automatically across:
- Bot restarts
- Server shutdowns
- VM reboots
- Docker container restarts (as long as the volume isn't deleted)

**No data is lost on shutdown.** Your admins and owners remain assigned indefinitely until explicitly revoked via `!owner revoke` or `!admin revoke` commands.

### First-Time Setup Checklist

1. ✅ Configure `.env` with your LLM endpoint and API keys
2. ✅ Run `./start.bat` (Windows) or `./start.sh` (Linux/macOS)
3. ✅ Scan the QR code at `http://localhost:8000/whatsapp/qr`
4. ✅ Set `BOT_OWNER_ID` in `.env` to your WhatsApp JID (e.g., `1234567890@s.whatsapp.net`), **OR** send `!claim_ownership` in a private chat to the bot to claim initial ownership
5. ✅ Grant additional admins/owners via `!owner grant <jid>` or `!admin grant <jid>`
6. ✅ **Back up `bot.db` and `.env` immediately** after initial setup
7. ✅ Set up regular backups of `bot.db` to preserve role assignments and chat data

### Recovery Procedures

**If `bot.db` is lost or corrupted:**
- The bot will create a fresh database on next startup
- **All role assignments, tasks, notes, and custom chat settings will be lost**
- You must re-run bootstrap ownership and re-grant all admin roles
- Recovery is only possible if you have a backed-up copy of `bot.db`

**If `.wwebjs_auth/` is lost:**
- The bot will prompt you to scan the QR code again to re-link
- No user data is lost; only the session token is reset

**If `.env` is lost:**
- Use your backup to restore it
- The bot will not function without this configuration file

---

## 🧠 Chatty Mode & Persistent Memory (RAG)

The bot features a highly sophisticated "Chatty Mode" that allows it to hold open-ended, continuous conversations with users, leveraging both Short-Term Context and Long-Term Memory (RAG).

### 📐 Architecture & Data Flow

1. **Incoming Message:** The user sends a text or media message via WhatsApp.
2. **Language Detection:** The engine detects the language (via `langdetect` or LLM fallback) and locks the response language to preserve natural conversation flow.
3. **Media Pipeline:**
   - **Images:** Sent to the Vision LLM (if enabled) to generate descriptive text.
   - **Documents:** Processed via `pdfplumber` to extract raw text context.
4. **RAG Ingestion:** The combined text (message + media context) is embedded locally using `sentence-transformers` and stored in a user-specific ChromaDB vector database.
5. **Prompt Construction:** The bot combines:
   - System Profile (Name, preferred language).
   - Long-Term Memory (Relevant chunks retrieved from ChromaDB).
   - Short-Term Summary (An LLM-generated rolling summary of the recent state of conversation).
   - The immediate user input.
6. **LLM Generation:** The unified context is sent to your configured Chat LLM to generate a natural, context-aware reply.

### ⚙️ Configuration & Storage

Chatty Mode configuration can be found in your `.env` file under the `CHATTY FEATURE & PERSISTENT MEMORY (RAG)` section. You can toggle the feature globally for DMs (`CHATTY_DEFAULT`) and Groups (`CHATTY_GROUP_DEFAULT`), and configure the Embedding model.

**Important:** The RAG implementation is completely independent of your Chat LLM provider.
- **Embeddings:** All embeddings are generated completely locally using `sentence-transformers` on your machine (e.g. `all-MiniLM-L6-v2`).
- **Chat/Generation:** The actual text generation is handled by whatever provider you have configured in `.env` (Local LM Studio, Ollama, Cloud OpenAI, etc.).
This ensures that your RAG pipeline functions perfectly, regardless of what chat backend you hook the bot up to!

### 🔒 Privacy First

The bot employs an **Isolated Ledger System**. All data related to a user (Logs, Media, Vector DB, Profiles) is isolated explicitly within the local `./data/contacts/{id}/` folder.

- **No data leaves your local machine** unless you have specifically configured a Cloud Provider (e.g. OpenAI) as your Chat LLM.
- **RAG embeddings** never hit the cloud; they are always processed strictly on your host machine.

---

## 🧳 Backup & Migration

If you are moving the bot to a new server, the repository includes a self-contained Python script to easily pack and unpack your authentication keys (`.wwebjs_auth`), database (`bot.db`), configuration (`.env`), and RAG memory files (`data/`).

**To Backup:**
```bash
python3 backup_restore.py --mode backup
```
*This will generate a ZIP file containing everything you need, securely skipping bloat like `node_modules` or `.git`.*

**To Restore (on the new server):**
```bash
# After git clone, place the ZIP in the root directory
python3 backup_restore.py --mode restore --file <your_backup_file>.zip
```
*The script will safely restore your environment and verify no data is unintentionally overwritten. See [ai-chat/BACKUP_RESTORE_FEATURE.md](ai-chat/BACKUP_RESTORE_FEATURE.md) for full architectural details.*

---

## 🐍 Python Version Compatibility

This bot strictly requires **Python 3.12**, which is the current stable LTS for AI/ML dependencies like PyTorch CPU.

If your system runs newer versions (e.g., Python 3.13 or 3.14), do not worry! The `start.sh` script is designed to safely handle side-by-side installations. It will automatically detect if `python3.12` is missing and provide installation instructions, and it will safely isolate the bot's virtual environment (`venv/`) strictly to 3.12 without disrupting your default system Python binaries.

---

## 🤖 Smart Chatty Control & Frequency
By default, enabling `!chatty` does not mean the bot will reply to every single message in a group (which creates spam). It natively integrates a **Frequency Counter** and **Mention Detection**.

- **Mentions:** If you tag the bot using `@` in a group chat, it will respond instantaneously, bypassing all frequency delays and appending context into RAG.
- **Frequency:** If unprompted, it silently listens, stores memory, and automatically generates a response every X messages (Default: 10). Group Admins can live-tune this using `!chatty_freq 20` or adjust sequential replies using `!chatty_burst`.

## 🌐 Dynamic Summaries & Language
The `!summary` feature is fully capable of dynamically processing vast contexts. Modify the `SUMMARY_MESSAGE_LIMIT` inside `.env` to analyze between 10 and 2000 recent messages at once depending on the capacities of your chosen LLM.

For Private DM users, the bot supports completely freezing linguistic outputs to your preference without triggering costly auto-detection algorithms on subsequent messages. Just send `!lang set fr` to lock your profile to French.
