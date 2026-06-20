# Chatty Feature & Persistent RAG Memory

The **Chatty** feature elevates the passive, translation-focused WhatsApp bot into a highly contextual, multimodal, long-term conversational assistant. It leverages a Retrieval-Augmented Generation (RAG) architecture powered by ChromaDB and sentence-transformers.

## 🗂️ Directory & Path Isolation
Privacy and context separation are fundamental. All user data is stringently isolated inside `./data/contacts/{id}/`.

```text
./data/
├── config.json                 <-- Global dynamic config
├── system_prompts/
│   └── default.txt             <-- Base persona prompt
└── contacts/
    └── {user_id_or_group_id}/  <-- Strict Isolation Layer
        ├── profile.json        <-- Tracks lang_pref, summary, status
        ├── chat_history.jsonl  <-- Append-only log
        ├── media/              <-- Local media downloads
        │   └── 17000000_image.jpeg
        └── vector_db/          <-- Local ChromaDB persistence
            └── chroma.sqlite3
```

## ⚙️ Variables & Configurations

### Global Settings (`.env`)
- `CHATTY_DEFAULT` (bool): Default state for DMs (true).
- `CHATTY_GROUP_DEFAULT` (bool): Default state for Groups (false).
- `DYNAMIC_SYSTEM_PROMPT` (bool): Enable LLM rolling summaries (true).
- `RAG_EMBEDDING_MODEL` (str): Local model for vector DB (default: `all-MiniLM-L6-v2`).
- `VISION_ENABLED` (bool): Process media via vision LLMs.

### Local Contact Profile (`profile.json`)
- `chatty_status`: Can override the `.env` default on a per-chat basis.
- `lang_pref`: The `langdetect` ISO string to force the LLM to output that language.
- `conversation_summary`: A condensed JSON state of the chat updated every 5 messages.

---

## 🛠️ Commands
Users and Admins interact with the Chatty memory engine using the `!chatty` command.

| Command | Permission | Description |
|---|---|---|
| `!chatty on` | Public (DM), Admin/Owner (Group) | Enables Chatty mode for the current chat window. |
| `!chatty off` | Public (DM), Admin/Owner (Group) | Disables Chatty mode for the current chat window. |

---

## 🔁 RAG Context Pipeline (Flow Diagram)

```text
         [ WhatsApp User ]
                │
                ▼ (Incoming Message via Node.js Gateway)
┌─────────────────────────────────────────┐
│        app/router_webhook.py            │
│ 1. Receives Base64 media & text payload │
│ 2. Downloads Media to ./data/media/     │
│ 3. Instantiates AIMemoryEngine          │
└───────────────┬─────────────────────────┘
                │
                ▼ (Engine Processing)
┌─────────────────────────────────────────┐
│     app/services/ai_memory_engine.py    │
│                                         │
│  A. Language Detection (langdetect)     │
│     => Logs 'es', 'en', 'id', etc.      │
│                                         │
│  B. Media Analysis (pdfplumber/Vision)  │
│     => Converts files to text context   │
│                                         │
│  C. Vector Embedding (ChromaDB)         │
│     => sentence-transformers encodes    │
│     => text into local SQLite DB        │
│                                         │
│  D. RAG Retrieval                       │
│     => Queries top 5 similar messages   │
│                                         │
│  E. Prompt Construction                 │
│     => Joins Profile + Memory + RAG     │
└───────────────┬─────────────────────────┘
                │
                ▼ (Unified Generation)
┌─────────────────────────────────────────┐
│           app/ai_client.py              │
│  Sends constructed system prompt and    │
│  user input to LLM Endpoint             │
└───────────────┬─────────────────────────┘
                │
                ▼ (Rolling Context Task)
┌─────────────────────────────────────────┐
│      AIMemoryEngine (Background)        │
│ Every 5 messages, triggers a JSON       │
│ summary generation to update the        │
│ profile.json `conversation_summary`     │
└─────────────────────────────────────────┘
```

## 🏗️ Architecture Design Choices

1. **Local Embeddings (Privacy):** Vector embeddings are generated locally using `sentence-transformers` rather than the main Chat LLM endpoints. This ensures absolute privacy (no data leak during indexing) and eliminates embedding latency issues if a slow local LLM is used.
2. **Node.js Media Pass-through:** To prevent double-fetching media chunks, the `whatsapp-web.js` microservice captures the binary blob, converts it to Base64, and pushes it up to the Python FastAPI via webhook. FastAPI handles the local file saving synchronously.
3. **Rolling Summary vs Generic Context:** Instead of feeding raw Chat History back to the LLM (which exceeds max context and gets expensive), the system leverages a combination of **Top-K RAG Matching** and a **Rolling JSON State Summary**. This allows the bot to remember specific instructions from weeks ago without hallucinating current conversation flow.
