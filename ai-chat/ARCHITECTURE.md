# Architecture

## Core Engines
- **Commands Engine:** Parses and executes user commands starting with `!` (`app/commands.py`).
- **Translation Engine:** Handles language detection and auto-translation using an LLM (`app/translation.py`).
- **AI Client Engine:** A unified interface routing requests to local or cloud-based Large Language Models depending on task and configuration (`app/ai_client.py`).
- **Contact Sync Engine:** Passively intercepts incoming webhook events to extract caller info, update the SQLite database, and export `CSV`/`MD` rosters to the filesystem (`app/contact_sync.py`).

## Interfaces
- **Node.js WhatsApp Microservice (`whatsapp-service/`):** Utilizes `whatsapp-web.js` to manage the WhatsApp Web connection, persist the session, generate QR codes, and trigger the Python webhooks.
- **Webhooks & System APIs:** FastAPI exposes `POST /webhook/whatsapp` to receive events, and `GET /whatsapp/qr`, `GET /whatsapp/status` to interact with the Node.js microservice (`app/router_webhook.py`, `app/router_system.py`).
- **WhatsApp Gateway Wrapper:** HTTP client implementation to send messages, and fetch group metadata back from the internal Node.js Gateway (`app/whatsapp_gateway.py`).

## Data Flow
1. **Inbound:** Internal Node.js Gateway intercepts WhatsApp messages and sends JSON payloads to Python via `/webhook/whatsapp`.
2. **Processing:** Payloads are parsed. Contact Sync Engine passively updates the database. Messages are logged to `MessageBuffer` (SQLite), and routed either to the Command Engine (if prefixed with `!`) or the Auto-Translate Engine.
3. **State Management:** SQLite via SQLAlchemy stores `ChatSettings` (auto-translate config, ignore lists, bot admin status), `Tasks`, `Notes`, `Contacts`, `GroupMembers`, and recent `MessageBuffers` (`app/state.py`).
4. **Outbound (Local Storage):** Contact Sync engine writes `.csv` and `.md` files to the `exports/` directory.
5. **Outbound (Network):** Responses are sent via the WhatsApp Gateway Wrapper to the WhatsApp Gateway API.
