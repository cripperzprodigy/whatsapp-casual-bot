**🛑 NO AI AGENT IS PERMITTED TO MODIFY THIS FILE WITHOUT EXPLICIT APPROVAL FROM A HUMAN.**

# Master Governance Document (SOP)

## Registration Protocol
Any agents starting work in this repository must log their presence in `agents/AGENT_REGISTRY.md` before executing any code changes.

## Coding Constraints
Strict adherence to the project's architecture is required.
- **Language Purism:** [Placeholder for specific language rules]
- **Modularity:** Ensure code is well-structured and separated into logical, independent modules.
- **Interface Parity:** Interfaces should remain consistent across modules.
- **Error Handling:** Implement robust error handling strategies.
- **Command Routing:** Command handlers must return immediately after execution to prevent fall-through into other domain handlers (e.g., the DM Chatty engine). Command prefix matching must be robust against whitespace (e.g., `text.strip().startswith("!")`).

## Testing & Deployment
- **Unit Testing:** Agents must write unit tests for any new logic introduced.
- **Validation:** Code must be verified (e.g., tests pass, linter passes) prior to committing code.

## 4.2 Shell Scripting & Idempotent Installation
- **Safe Cleanup:** Cleanup traps must explicitly preserve persistent state markers (e.g., .bot_ready_state) and only remove runtime artifacts.
- All LLM prompts for translation must explicitly forbid meta-commentary and enforce 'output-only' constraints.
- **Input Validation:** All user-facing commands must validate inputs and provide sensible defaults or clear error messages. Never greedily assume user input matches a parameter just based on length.
- All token limits, context window sizes, and model parameters must be configurable via .env; no magic numbers in code. Hardcoded token counts and fixed conversation slices are strictly prohibited.
- Long-form translations must use semantic chunking with context awareness to prevent data loss. Never silently truncate text.
- Config values used for substring matching must be validated for emptiness before use.

- **Feature Interaction Suppression:** When a message is explicitly directed at the bot (detected via `is_explicitly_tagged`), background enhancement features (auto-translation, auto-summary, etc.) must be suppressed. Direct interactions take exclusive priority to prevent duplicate or conflicting output.

- **Context-Aware Replies & Anti-Spoofing:** When processing Threaded Conversations (users replying to the bot via the WhatsApp "Reply" feature), the bot must extract `quotedMessage` context. To prevent malicious context injection/spoofing, the quoted `participant` JID MUST be securely validated against the `BotIdentityManager` (checking `BOT_NUMBER` and known LIDs) before injecting it into the AI's prompt. The context must be clearly prepended to the user's message string to guarantee the LLM attributes it correctly (e.g. `User is replying to your previous message: '{quoted}' "{message}"`).
- **Group Message Attribution (MANDATORY):** All group message replies that quote a previous message MUST include the `quotedParticipant` parameter.
  - **VALIDATION:** Code review checklist item for any message-sending changes.
  - **TESTING:** Test plans must explicitly include both DM (where participant is `None`) and group scenarios to verify attribution.
  - **REFERENCE:** See [CHATTY_FEATURE.md](knowledge_base/CHATTY_FEATURE.md) and [WISP_PROTOCOL.md](knowledge_base/WISP_PROTOCOL.md).

- **Domain Separation:** Any new features affecting message processing MUST consider DM/Group domain separation and should be implemented within the respective dedicated handler (`_handle_dm_message` or `_handle_group_message`). The main webhook router should only contain shared early-exit guards.

- **JID Normalization:** Node.js gateway implementations must normalize all incoming unofficial or device-specific JID suffixes (such as `@c.us` and `@lid`) to the official `@s.whatsapp.net` suffix before forwarding payloads to the Python backend. This ensures domain guard rails and mention detection logic function correctly against standardized JIDs.

- **Language Detection Standards & Linguistic Sphere (ADR-027, ADR-028):** Auto-translation MUST enforce the EN/ID/MS Linguistic Sphere: English (`en`), Indonesian (`id`), and Malay (`ms`) are treated as a single shared language group. No translation may EVER occur between these three languages. `GLOBAL_IGNORED_LANGUAGES` MUST default to `"en,id,ms"`. The keyword heuristic (`COMMON_MS_ID_WORDS`) MUST be checked before invoking `langdetect` and MUST return a skip (not translate) when ms/id is detected and is in the ignored set. If `langdetect` returns a known false-positive language (`fi`, `tl`, `so`, `sw`) for text that matches the keyword set, the result MUST be overridden to `ms`. Only truly foreign languages (Arabic, Chinese, Japanese, etc.) should trigger translation. See [LANGUAGE_DETECTION.md](knowledge_base/LANGUAGE_DETECTION.md).

- **DM Reply Quoting Prohibition (MANDATORY):** Direct Message (DM) chatty replies MUST NOT include `quotedMsgId` in the send payload. DMs should appear as natural conversational messages without WhatsApp quote bubbles. Only group replies triggered by explicit `@bot` tags or threaded reply contexts should use quoted messages.

- **External Keyword Dictionary (MANDATORY):** Translation skip keywords MUST reside in `data/translation_skip_keywords.txt`, NOT hardcoded in source. The file format supports comments (`#`) and blank lines. Keywords are loaded at startup and cached. Any expansion to the keyword set MUST be done by editing this file, not by modifying `translation.py`. See ADR-029.

- **Hierarchical Translation Control (MANDATORY):** Translation follows a strict hierarchy: (1) Global toggle (`GLOBAL_AUTO_TRANSLATE` / `!globaltrans`) must be ON. (2) Group toggle (`!auto on/off`) must be ON. (3) Keyword heuristic must NOT match. (4) Detected language must NOT be in `GLOBAL_IGNORED_LANGUAGES`. Only if all four checks pass does translation proceed. Global OFF overrides all group settings.

## 4.3 Session Storage Paths
- All session/authentication files MUST use absolute paths resolved via `path.resolve(__dirname, '...')` in Node.js
- Python services MUST use `Path(__file__).resolve().parent` for relative path resolution
- Never use relative paths like `'./.folder'` for persistent storage

## 4.4 WhatsApp Gateway Session Health Monitoring
- **Session Path Normalization:** All services, including the Node.js Gateway, must resolve file paths for persistent storage (like `.wwebjs_auth`) using absolute paths (e.g. `path.resolve(__dirname, '...')`) rather than purely relative strings. Docker deployments must use named volumes for these paths to ensure state survives container teardowns.
- **Gateway State Management & WISP Protocol:** The Node.js gateway and Python backend communicate via the WhatsApp Inter-Service Protocol (WISP). The Gateway operates in three states: CONNECTED, RECOVERING, and DISCONNECTED. In the RECOVERING state, messages are acknowledged with HTTP 202 (QUEUED_FOR_RECOVERY) and kept in a silent queue (`recoveryMessageQueue`) to be processed upon recovery. Unrecoverable states return HTTP 503 (SESSION_CORRUPT). The Python backend expects strict Pydantic/JSON schema structures (GatewaySendResult, DeliveryResponse) and must silently queue commands (like `!claim_ownership` or `!pm`) rather than notifying the user during transient recovery.
- **Tiered Session Auto-Recovery:** The Node.js gateway must actively track consecutive send failures and implement a graceful, tiered recovery strategy to avoid unnecessary manual QR scans:
  - **Tier 1 (Puppeteer Restart):** Attempt to reload the underlying Puppeteer page context to resolve transient execution context errors without destroying the session.
  - **Tier 2 (Client Reinitialization):** Destroy and recreate the `whatsapp-web.js` client instance while preserving the `.wwebjs_auth` directory.
  - **Tier 3 (Nuclear Purge):** As a last resort, purge the `.wwebjs_auth` directory via `fs.rmSync` and prompt for a new QR scan.
- **Error Pattern Matching:** The gateway MUST actively monitor `sendMessage` API errors for specific patterns indicating session corruption (e.g., "No LID for user", "session corrupt", "invalid session", "ExecutionContext").
- **Immediate Recovery Strategy:** When a known session corruption pattern is detected, the gateway MUST bypass the standard N-consecutive-failures threshold and trigger an *immediate* escalation through the recovery tiers.
- **Delayed Recovery Strategy:** General timeout or disconnect errors should respect the threshold (e.g., 3 failures) before forcing a recovery escalation, to prevent unnecessary resets during transient network blips.

## Configuration Management Standards

### Runtime-Detected Identifiers
For any system identity that is only known after a service connects
(e.g., WhatsApp JIDs, OAuth client IDs returned at runtime), prefer
runtime detection with caching over static ENV configuration. 
For opaque multi-device identifiers like `@lid`, implement Owner-Registered 
Identity flows (e.g., `!whoami`) to securely learn mapping contextually.
See ADR-014 and ADR-017 in decisions.md.

### LID Registration Requirements
- On first group deployment, the bot owner MUST run `@Bot !whoami` to register the bot's LID for mention detection.
- `bot_known_lids.json` MUST be auto-created on first access with an empty array.
- The `!whoami` handler MUST register ALL JIDs in the `mentioned_jids` array, not just the first.
- Debug logging MUST dump `mentioned_jids` vs `known_ids` on every mention check for traceability.

### 6.4 Docker Installation
- `start.sh` MUST check for Docker installation before attempting docker-compose operations
- Docker installation MUST be automated with proper GPG key setup and repository configuration
- Post-installation: user MUST be added to `docker` group and daemon MUST be started/enabled

### Code Maintenance and Hygiene
- **Dead code and backup files must be removed immediately upon refactoring, not batched.** Do not leave `*-backup.*`, `*.bak`, `*.old`, `*~`, or commented-out deprecated logic blocks in the codebase.

### Agentic Workflows and Loop Guards
- **Command Taxonomy**: New agentic commands like `!s` should live alongside existing commands (`!search`) as premium commands for deep research rather than replacing them. Quick lookups should remain accessible via low latency variants.
- **Graceful Degradation**: All agentic loops must have hard iteration limits and timeout guards. If advanced reasoning logic fails (such as an LLM Gap Analysis phase), the system must log the failure but immediately fallback to synthesize a final answer using the available accumulated context, rather than completely failing.
- **Single-Response Contract (MANDATORY)**: Service functions that construct and return user-facing messages (e.g., `execute_iterative_search()`) MUST catch all exceptions internally and ALWAYS return a string. The caller MUST NOT have a separate error-message send in its `except` block that could fire when the service already returned a fallback. This prevents duplicate messages. If a safety-net `except` is kept in the caller, it must log `"this should not happen"` to flag contract violations.
- **Outbound Message Chunking (MANDATORY)**: Any code path that sends potentially long text (LLM responses, search results, AI replies) MUST use `send_long_message()` from `app/utils/message_splitter.py` instead of raw `send_text_message()`. Short, fixed-length messages (help text, error messages, confirmations) may use `send_text_message()` directly. Chunks must not exceed 2500 characters and must be split at natural boundaries (paragraphs, sentences, words). Sequential chunks must have a 1-second inter-chunk delay to prevent rate limiting.

### Feature Flag Implementation Standards
- **Runtime vs ENV Configuration Priority**: When implementing feature flags, the system should always prioritize a verified runtime database state first (e.g. via `FeatureFlagService`), and fall back to a strictly typed ENV default if no override exists.
- **Experimental Features**: All experimental features must have an ENV kill-switch and RBAC guard. Do not deploy resource-heavy features universally without a means for the owner to toggle them off dynamically at runtime.

### Agentic Feature Documentation Standards
- **Knowledge Base Extensibility**: When introducing new large-scale architectural features (like RAG, Agentic Search, or Backup systems), create a dedicated markdown file in `ai-chat/knowledge_base/` and explicitly detail the ASCII flow, constraints, failovers, and feature toggle states, linking it back to the `ai-chat/README.md` hub.
- **Search Infrastructure**: All external search deployments (e.g., SearXNG) must be strictly documented using the Copy-Paste-Deploy pattern. See [SEARXNG_DEPLOYMENT_GUIDE.md](knowledge_base/SEARXNG_DEPLOYMENT_GUIDE.md) as the standard.
