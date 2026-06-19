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

### Group Assistant
- `!summary [short|full]` - Uses the AI to summarize the last 30 messages in the group.
- `!search <query>` - Ask the AI to perform a simulated web search to answer a query.
- `!task add <desc>` - Add an open task.
- `!task list` - List open tasks.
- `!task done <id>` - Mark a task as completed.
- `!note add <text>` - Add a permanent note.
- `!note list` - List all notes.

---

## 📁 Contact Exports

If `AUTO_SYNC_CONTACTS` is enabled, the bot employs an advanced **Isolated Ledger System**.

1. **Active Sweep:** The moment the bot receives a message in a new group, it hits the WhatsApp gateway, pulls the full participant list, and instantly builds a full database ledger for that specific group (even for lurkers who haven't spoken).
2. **Passive Updates:** As people send messages over time, the bot securely updates their `last_seen` timestamp and their display name *only within the context of that specific group*.
3. **No Deletions:** If someone leaves the group, they are simply marked as `Inactive` so you never lose the historical record of who was there.
4. **Throttled Exports:** To maintain high performance during busy chats, the bot will automatically write changes to your filesystem (maximum once per minute).

It exports two files per group in the directory configured by `CONTACTS_EXPORT_DIR` (default: `exports/groups/<group_id>/`):
- `contacts.csv` - Includes Phone Number, Name, Admin Status, and Active Status. Ideal for importing into Excel or Google Contacts.
- `summary.md` - A neat Markdown overview showing the group name, total members, active members, and a table of synced users.
