# Project History

*Future Agents: Log historical context and state changes here. Document major design decisions, pivots, and the engineering rationale behind the architecture (e.g., database selection, caching strategies) to preserve the core design philosophy for future maintainers.*

## Log
- **2026-06-18:** Initialized the WhatsApp Casual Bot architecture. 
  - **Framework:** Chose FastAPI for fast async Python logic, supplemented by an internal Node.js microservice (`whatsapp-service/`) utilizing `whatsapp-web.js`.
  - **Database:** Used SQLite with SQLAlchemy for simple, file-based persistence suited for small group chats. Ensures state is portable and easy to query without managing a separate database server.
  - **AI Abstraction:** Implemented a unified AI client (`app/ai_client.py`) using the `openai` python package to allow seamless toggling between Local (e.g., Ollama) and Cloud (OpenAI) LLMs based on task complexity.
  - **Passive Syncing Engine:** Designed a passive interceptor pattern (`app/contact_sync.py`) instead of actively fetching from the gateway. This reduces API rate limit pressure. It silently updates the `Contacts` and `GroupMembers` tables whenever a webhook triggers, and exports continuous `contacts.csv` and `summary.md` state files to the `exports/` directory.
  - **Node.js Gateway Migration:** Originally assumed an external gateway like Evolution API. Pivoted to building a native, tightly-coupled Node.js microservice to perfectly replicate the OpenClaw QR-login, session persistence, and session-reset flows internally.
