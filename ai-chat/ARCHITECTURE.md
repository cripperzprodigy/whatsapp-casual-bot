# System Architecture & Workflows

This document outlines the core architecture, data flows, and database schemas of the WhatsApp Casual Bot to assist future AI agents in extending the codebase.

---

## 1. High-Level Architecture

The system utilizes a dual-runtime architecture. A lightweight **Node.js Microservice** manages the raw, unstable websocket connection to WhatsApp Web, providing native QR-logins and session persistence. It acts as a dumb proxy, forwarding all business logic to the robust **Python FastAPI Backend**, which handles AI routing and SQLite state management.

```text
+-------------------+       +-----------------------+       +------------------------+
|   WhatsApp App    |       | Node.js Microservice  |       | Python FastAPI Backend |
|   (User's Phone)  | <---> | (whatsapp-service/)   | <---> | (app/)                 |
|                   |       |   - QR Generation     |       |   - AI Translation     |
|   [Linked Device] |       |   - Session Auth      |       |   - Contact Syncing    |
+-------------------+       |   - Webhook Proxy     |       |   - Command Engine     |
                            +-----------------------+       +------------------------+
                                       ^                               |
                                       |                               |
                                       |                               v
                             +-------------------+          +------------------------+
                             |  Local / Cloud    |          |    SQLite Database     |
                             |   AI Models       | <------- |  (bot.db / state.py)   |
                             | (LM Studio/OpenAI)|          +------------------------+
                             +-------------------+          
```

---

## 2. Core Engines & Modules

- **Node.js WhatsApp Microservice (`whatsapp-service/`):** Utilises `whatsapp-web.js` to natively manage the WhatsApp connection, persist the `.wwebjs_auth/` session, serve the QR code locally, and trigger Python webhooks. Sends `instance: 'whatsapp-web-js'` in every webhook payload.
- **Commands Engine:** Parses and executes user commands starting with `!` (`app/commands.py`).
- **Translation Engine:** Handles language detection and auto-translation. Includes a `FULL_NAME_TO_CODE` map for robust LLM output normalisation. Utilises native WhatsApp reply/quoting (`reply_to_msg_id`) to maintain context in busy group chats (`app/translation.py`). Auto-translation replies send only the translated text while quoting the original message.
- **Search Command Engine:** Parses `!search` requests, routes them through the LLM as a simulated search answer, and protects users from mistaken live-web claims by clearly signalling when live search is unavailable (`app/commands.py`).
- **AI Chat Command:** Supports `!a <text>` for a general-purpose AI response from the configured model.
- **AI Client Engine:** A unified, standard `AsyncOpenAI` interface. Supports both Local AI (e.g., LM Studio) and Cloud AI (OpenAI) by swapping `LLM_ENDPOINT` in `.env`. Temperature constants `_TEMP_PRECISE` / `_TEMP_CREATIVE` control task-specific LLM behaviour (`app/ai_client.py`).
- **Contact Sync Engine:** Intercepts incoming webhooks and Gateway APIs to build strictly isolated group rosters. Exports path is configurable via `CONTACTS_EXPORT_DIR` (`app/contact_sync.py`). The roster export throttle now uses timezone-aware UTC timestamps so old naive database values are normalized before comparison.
- **Health Check (`GET /health`):** Endpoint in `router_system.py` that checks DB liveness (`SELECT 1`) and Node.js gateway reachability. Returns `{status, db, gateway}` JSON with HTTP 503 on degradation.
- **Rate Limiting:** `/webhook/whatsapp` is protected by `slowapi` (configurable via `WEBHOOK_RATE_LIMIT`, default 60 req/min per IP). System and health endpoints are exempt.

---

## 3. Data Flow: Contact Synchronization (Isolated Ledger)

The bot utilizes an **Isolated Ledger** pattern. Instead of treating a user as a global entity, every contact is strictly siloed per chat group. This allows a user to have different names or admin statuses across different groups, exactly mirroring native WhatsApp behavior.

### The Two-Pronged Sync Workflow

```text
[Gateway API]                                    [Python Webhook Router]
      |                                                    |
      | 1. Bot added to new Group                          |
      |--------------------------------------------------->|
      |                                                    |
      | 2. Fetch full participant list                     |
      |<---------------------------------------------------|
      |                                                    | 3. process_active_sweep()
      |                                                    |    Bulk insert ALL members
      |                                                    |    into GroupContactLedger.
      |                                                    |    (Captures lurkers)
      |                                                    |
      | 4. User sends a message over time                  |
      |--------------------------------------------------->|
      |                                                    | 5. update_contact()
      |                                                    |    Update last_seen_at and
      |                                                    |    display name.
      |                                                    |
      |                                                    | 6. Throttled File Export
      |                                                    |    Writes CSV/MD to
      |                                                    |    exports/groups/<id>/
```

---

## 4. Database Schema (`app/state.py`)

All state is maintained in SQLite using SQLAlchemy ORM. Direct raw SQLite querying is forbidden by the SOP.

### `ChatSettings`
Manages configuration cascades for auto-translation and throttled IO limits.
- `chat_id` (PK)
- `auto_translate_enabled` (Nullable. If None, falls back to `.env` GLOBAL settings).
- `default_target_language` (Nullable. If None, falls back to `.env` GLOBAL settings).
- `ignored_languages` (JSON, Nullable. If None, falls back to `.env` GLOBAL settings).
- `bot_is_admin` (Updated via Active Sweep).
- `last_roster_export_at` (Used by Contact Sync to throttle disk writes).

### `GroupContactLedger`
The core of the Isolated Ledger pattern. Composite Primary Keys ensure data is siloed per group.
- `chat_id` (PK 1)
- `phone_number` (PK 2)
- `push_name` (WhatsApp display name, updated passively).
- `is_admin`
- `is_active` (If a user leaves, this is set to False. We never delete rows to preserve history).
- `first_seen_at`
- `last_seen_at`

### Helper Tables
- **`Task` / `Note`**: Simple CRUD tables linked to a `chat_id` for the assistant features.
- **`MessageBuffer`**: A rolling window (default size 200, set via `MESSAGE_BUFFER_SIZE`) of the
  most recent messages per chat, utilised by the `!summary` command. Old messages are pruned with
  a `while` loop (not `if`) so burst arrivals never overflow the buffer.
