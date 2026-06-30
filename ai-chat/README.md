# AI-CHAT Protocol & Collaboration Hub

The `ai-chat/` folder is the central nervous system for all autonomous agents operating in this repository. It serves as a strict **collaboration workspace** where agents exchange information, stay up-to-date with active implementation plans, track bugs, and document architectural decisions to drive progressive codebase improvements.

Welcome. Any newly attached AI agent must read the workspace documents in this exact execution order before modifying any system code:

1. `SOP.md`
2. `agents/AGENT_REGISTRY.md`
3. `chatpad.md`
4. `knowledge_base/ARCHITECTURE.md`
5. `PROJECT_HISTORY.md`

---

## Latest ai-chat Updates (2026-07-01)

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
| [ARCHITECTURE.md](./knowledge_base/ARCHITECTURE.md) | System-wide architecture overview |
| [WISP_PROTOCOL.md](./knowledge_base/WISP_PROTOCOL.md) | WhatsApp Inter-Service Protocol (Python ↔ Node.js gateway) |
| [CHATTY_FEATURE.md](./knowledge_base/CHATTY_FEATURE.md) | Long-term memory conversational AI (`!chatty`) |
| [AGENTIC_SEARCH_FEATURE.md](./knowledge_base/AGENTIC_SEARCH_FEATURE.md) | Multi-hop agentic search (`!s`) workflow and architecture |
| [MESSAGE_CHUNKING.md](./knowledge_base/MESSAGE_CHUNKING.md) | Outbound message splitting algorithm and `send_long_message()` |
| [WHOAMI_LID_REGISTRATION.md](./knowledge_base/WHOAMI_LID_REGISTRATION.md) | Bot identity discovery, `!whoami`, and LID persistence |
| [ERROR_HANDLING_DUPLICATE_PREVENTION.md](./knowledge_base/ERROR_HANDLING_DUPLICATE_PREVENTION.md) | Single-Response Contract and duplicate message prevention |
| [LANGUAGE_DETECTION.md](./knowledge_base/LANGUAGE_DETECTION.md) | Hybrid language detection with keyword heuristic for Malay/Indonesian |
| [BOT_IDENTITY_AND_ROUTING.md](./knowledge_base/BOT_IDENTITY_AND_ROUTING.md) | JID normalization, LID routing, and identity management |
| [CONTACT_SYNC_ARCHITECTURE.md](./knowledge_base/CONTACT_SYNC_ARCHITECTURE.md) | Contact sync, GroupContactLedger, live batch resolution, and smart cache |
| [COMMAND_REFERENCE.md](./knowledge_base/COMMAND_REFERENCE.md) | Bot command reference and usage guide |
| [GATEWAY_API.md](./knowledge_base/GATEWAY_API.md) | Node.js WhatsApp Gateway API endpoints |
| [CONFIGURATION_GUIDE.md](./knowledge_base/CONFIGURATION_GUIDE.md) | Environment variables and runtime configuration |
| [BACKUP_RESTORE_FEATURE.md](./knowledge_base/BACKUP_RESTORE_FEATURE.md) | Migration and backup utilities |
| [translation_architecture.md](./knowledge_base/translation_architecture.md) | Translation pipeline and semantic chunking |
| [SEARXNG_DEPLOYMENT_GUIDE.md](./knowledge_base/SEARXNG_DEPLOYMENT_GUIDE.md) | Comprehensive SearXNG Docker installation and network configuration for Agentic Search |


