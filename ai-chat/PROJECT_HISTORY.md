# Project History

*Future Agents: Log historical context and state changes here. Document major design decisions, pivots, and the engineering rationale behind the architecture (e.g., database selection, caching strategies) to preserve the core design philosophy for future maintainers.*

## Log
- **2026-06-18:** Initialized the WhatsApp Casual Bot architecture. 
  - **Framework:** Chose FastAPI for fast async Python logic, supplemented by an internal Node.js microservice (`whatsapp-service/`) utilizing `whatsapp-web.js`.
  - **Database:** Used SQLite with SQLAlchemy for simple, file-based persistence suited for small group chats. Ensures state is portable and easy to query without managing a separate database server.
  - **AI Abstraction:** Implemented a unified AI client (`app/ai_client.py`) using the `openai` python package to allow seamless toggling between Local (e.g., Ollama) and Cloud (OpenAI) LLMs based on task complexity.
  - **Node.js Gateway Migration:** Originally assumed an external gateway like Evolution API. Pivoted to building a native, tightly-coupled Node.js microservice to perfectly replicate the OpenClaw QR-login, session persistence, and session-reset flows natively in the repo.
  - **Contact Sync Evolution:** Initially built generic `Contact` and `GroupMember` tables using a purely passive sync model. Pivoted to an **Isolated Ledger** pattern (`GroupContactLedger`), combining an initial "Active Sweep" (fetching the full roster immediately upon joining a group) with continuous "Passive Updates" to securely silo names and statuses per group without ever deleting historical records.
  - **Auto-Translation Cascade:** Evolved from hardcoded per-chat translation toggles to a robust configuration cascade (Explicit Chat Settings -> `.env` Global Settings -> Disabled). Added `!auto global` fallback commands and tuned the prompt instructions to severely punish LLM conversational filler. Added native WhatsApp quoting so translations visually reply to the original message.
