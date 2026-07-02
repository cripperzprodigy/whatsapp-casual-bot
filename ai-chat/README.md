# AI-CHAT Protocol & Collaboration Hub

⚠️ **AI AGENTS: Do not start here. Your primary entry point is `ai-chat/SOP.md`. This file is for human context only.**

The `ai-chat/` folder is the central nervous system for autonomous agents operating in this repository. It serves as a strict **collaboration workspace** where agents exchange information, stay up-to-date with active implementation plans, track bugs, and document architectural decisions.

---

## Latest ai-chat Updates (2026-07-02)

- **Language Mirroring Protocol (ADR-039)**: The AI engine now mirrors the user's language — Chinese replies to Chinese input, Indonesian to Indonesian. `[CRITICAL LANGUAGE RULE]` block placed above RAG context to prevent English drift. CJK heuristic (Option B) fixes Traditional Chinese → Korean misclassification. See [LANGUAGE_DETECTION_STRATEGIES.md](./knowledge_base/LANGUAGE_DETECTION_STRATEGIES.md).
- **Isolation Fixes (ADR-036/037/038)**: Snapshot context aligns summary & RAG windows. Per-chat preference scoping prevents DM persona leak to groups. SQLite session durability with optimistic locking. Temp file context manager for per-request cleanup. Tool execution scratchpad isolates internal logs from conversation history. RAG temporal decay with configurable TTL.
- **RAG Active Ingestion Pipeline (ADR-030)**: ChromaDB writes run in thread pool. New config flags: `ENABLE_RAG_INGESTION`, `RAG_TOP_K`, `RAG_DEFAULT_TTL_DAYS`. See [RAG_MEMORY_ENGINE.md](./knowledge_base/RAG_MEMORY_ENGINE.md).
- **Contact Sync Architecture Overhaul**: `!contacts list`, `!contacts global`, and `!contacts export` now query `GroupContactLedger` DB instead of filesystem. Live WhatsApp network resolution via batch endpoint, hierarchical group-sorted output, timestamped CSV exports with group name enrichment. See [CONTACT_SYNC_ARCHITECTURE.md](./knowledge_base/CONTACT_SYNC_ARCHITECTURE.md).
- **Group AI Language Detection Fix**: `_detect_language()` in `ai_memory_engine.py` now performs live detection on the incoming message text for group chats instead of returning a static default. 3-tier fallback: langdetect → LLM → group default.
- **SOP Cleanup**: Removed full duplicate content block, added new mandatory standards for AI Engine Language Detection and Contact Management.

## Previous Updates (2026-06-30)

- **Deep Crawl Search (`!sc`)**: Added in-depth agentic web crawling. Includes SSRF security protection, dynamic LLM context budgeting, configurable crawl depth, and `beautifulsoup4`/`lxml` based HTML parsing. See [AGENTIC_SEARCH_FEATURE.md](./knowledge_base/AGENTIC_SEARCH_FEATURE.md).
- **Message Chunking & Sequential Sending**: Long bot responses (>2500 chars) are now automatically split at natural boundaries and sent as sequential parts. See [MESSAGE_CHUNKING.md](./knowledge_base/MESSAGE_CHUNKING.md).
- **Bot Identity (`!whoami`) Self-Identification**: Fixed critical LID registration bug. Bot now dynamically discovers its own WhatsApp LID using sender-exclusion heuristic. See [WHOAMI_LID_REGISTRATION.md](./knowledge_base/WHOAMI_LID_REGISTRATION.md).
- **Error Handling & Duplicate Prevention**: Established the Single-Response Contract to prevent duplicate messages when LLM calls fail. See [ERROR_HANDLING_DUPLICATE_PREVENTION.md](./knowledge_base/ERROR_HANDLING_DUPLICATE_PREVENTION.md).

## Knowledge Base

| Document | Description |
|---|---|
| [ARCHITECTURE_KNOWLEDGE_BASE.md](./knowledge_base/ARCHITECTURE_KNOWLEDGE_BASE.md) | Full architecture, data flows, DB schema, message routing |
| [WISP_PROTOCOL.md](./knowledge_base/WISP_PROTOCOL.md) | WhatsApp Inter-Service Protocol (Python ↔ Node.js gateway) |
| [CHATTY_FEATURE.md](./knowledge_base/CHATTY_FEATURE.md) | Long-term memory conversational AI (`!chatty`) |
| [RAG_MEMORY_ENGINE.md](./knowledge_base/RAG_MEMORY_ENGINE.md) | Active RAG ingestion, async flow, snapshot context, temporal TTL |
| [PREFERENCE_SCOPING.md](./knowledge_base/PREFERENCE_SCOPING.md) | Per-(user,chat) persona isolation (ADR-036) |
| [TEMP_FILE_HYGIENE.md](./knowledge_base/TEMP_FILE_HYGIENE.md) | Request-scoped temp file cleanup |
| [TOOL_EXECUTOR_SCRATCHPAD.md](./knowledge_base/TOOL_EXECUTOR_SCRATCHPAD.md) | Isolated tool execution logs |
| [LANGUAGE_DETECTION.md](./knowledge_base/LANGUAGE_DETECTION.md) | Translation & mirroring detection, EN/ID/MS linguistic sphere |
| [LANGUAGE_DETECTION_STRATEGIES.md](./knowledge_base/LANGUAGE_DETECTION_STRATEGIES.md) | CJK disambiguation — heuristic vs fasttext (Option B implemented) |
| [AGENTIC_SEARCH_FEATURE.md](./knowledge_base/AGENTIC_SEARCH_FEATURE.md) | Multi-hop agentic search (`!s`) workflow and architecture |
| [COMMAND_REFERENCE.md](./knowledge_base/COMMAND_REFERENCE.md) | Full command reference across all roles |
| [CONFIGURATION_GUIDE.md](./knowledge_base/CONFIGURATION_GUIDE.md) | Environment variables and runtime configuration |
| [SESSION_PERSISTENCE_GUIDE.md](./knowledge_base/SESSION_PERSISTENCE_GUIDE.md) | WhatsApp session storage and recovery |
| [BOT_IDENTITY_AND_ROUTING.md](./knowledge_base/BOT_IDENTITY_AND_ROUTING.md) | JID normalization, LID routing, identity management |
| [CONTACT_SYNC_ARCHITECTURE.md](./knowledge_base/CONTACT_SYNC_ARCHITECTURE.md) | Contact sync, GroupContactLedger, batch resolution |
| [MESSAGE_CHUNKING.md](./knowledge_base/MESSAGE_CHUNKING.md) | Outbound message splitting algorithm |
| [ERROR_HANDLING_DUPLICATE_PREVENTION.md](./knowledge_base/ERROR_HANDLING_DUPLICATE_PREVENTION.md) | Single-Response Contract |
| [WHOAMI_LID_REGISTRATION.md](./knowledge_base/WHOAMI_LID_REGISTRATION.md) | Bot identity discovery, `!whoami` |
| [GATEWAY_API.md](./knowledge_base/GATEWAY_API.md) | Node.js WhatsApp Gateway API endpoints |
| [BACKUP_RESTORE_FEATURE.md](./knowledge_base/BACKUP_RESTORE_FEATURE.md) | Migration and backup utilities |
| [SEARXNG_DEPLOYMENT_GUIDE.md](./knowledge_base/SEARXNG_DEPLOYMENT_GUIDE.md) | SearXNG Docker installation for Agentic Search |


