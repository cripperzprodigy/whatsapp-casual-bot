# WhatsApp Casual Bot

A highly capable, passive WhatsApp bot built with Python and FastAPI, designed specifically for small private groups. It provides powerful AI translation, an assistant mode for tasks/notes, and silent contact synchronization to maintain an offline roster.

## Core Features

- **Native QR Login:** Replicates the seamless OpenClaw QR-login and linked-device experience without relying on heavy external gateways.
- **Auto-Translation:** Automatically detect and translate incoming messages to a default language (e.g., all messages translated to English). Configurable globally or per group.
- **Assistant Tools:** Generate summaries of recent group chats using AI, assign tasks, and write notes.
- **Unified AI Client:** Seamlessly toggle between local LLMs (e.g., Ollama) and cloud-based LLMs (e.g., OpenAI) depending on task complexity.
- **Silent Contact Synchronization:** Passively learns the names and numbers of users as they message the group. The bot is self-aware of its admin status and exports beautiful CSV and Markdown rosters to `exports/groups/<group_id>/` automatically.
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

---

## ⚙️ Configuration (`.env`)

Create a `.env` file in the root directory.

```env
# Security: Comma separated list of allowed chat IDs (e.g. 123@g.us). Leave empty to allow all.
WHITELISTED_CHATS=

# Bot Identity (Important: Prevents the bot from responding to itself)
BOT_NUMBER=1234567890

# Global Translation Settings
# These act as the defaults if a specific chat has not overridden them.
GLOBAL_AUTO_TRANSLATE=False
GLOBAL_TARGET_LANGUAGE=en
GLOBAL_IGNORED_LANGUAGES=id,es

# AI Configuration
USE_LOCAL_LLM=False
LOCAL_LLM_ENDPOINT=http://localhost:11434/v1
CLOUD_LLM_ENDPOINT=https://api.openai.com/v1
CLOUD_LLM_API_KEY=sk-your-openai-key
DEFAULT_MODEL_NAME_CLOUD=gpt-3.5-turbo
DEFAULT_MODEL_NAME_LOCAL=llama2

# Contact Sync (Default is True)
AUTO_SYNC_CONTACTS=True
```

---

## 🛠 Commands Reference

Type `!help` in the WhatsApp chat to see the list of available commands.

### Translation & Language
**Understanding the cascade:** Any settings changed via these commands only apply to the specific group or chat they are sent in. If you want a chat to stop using its custom settings and fall back to the `.env` file's `GLOBAL_` variables, use the `global` arguments.

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
