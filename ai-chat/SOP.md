**🛑 NO AI AGENT IS PERMITTED TO MODIFY THIS FILE WITHOUT EXPLICIT APPROVAL FROM A HUMAN.**

# Master Governance Document (SOP)

## Registration Protocol
Any agents starting work in this repository must log their presence in `AGENT_REGISTRY.md` before executing any code changes.

## Coding Constraints
Strict adherence to the project's architecture is required.
- **Language Purism:** [Placeholder for specific language rules]
- **Modularity:** Ensure code is well-structured and separated into logical, independent modules.
- **Interface Parity:** Interfaces should remain consistent across modules.
- **Error Handling:** Implement robust error handling strategies.

## Testing & Deployment
- **Unit Testing:** Agents must write unit tests for any new logic introduced.
- **Validation:** Code must be verified (e.g., tests pass, linter passes) prior to committing code.

**🛑 NO AI AGENT IS PERMITTED TO MODIFY THIS FILE WITHOUT EXPLICIT APPROVAL FROM A HUMAN.**

# Master Governance Document (SOP)

## Registration Protocol
Any agents starting work in this repository must log their presence in `AGENT_REGISTRY.md` before executing any code changes.

## Coding Constraints
Strict adherence to the project's architecture is required.
- **Language Purism:** [Placeholder for specific language rules]
- **Modularity:** Ensure code is well-structured and separated into logical, independent modules.
- **Interface Parity:** Interfaces should remain consistent across modules.
- **Error Handling:** Implement robust error handling strategies.

## Testing & Deployment
- **Unit Testing:** Agents must write unit tests for any new logic introduced.
- **Validation:** Code must be verified (e.g., tests pass, linter passes) prior to committing code.

## 4.2 Shell Scripting & Idempotent Installation
- **Safe Cleanup:** Cleanup traps must explicitly preserve persistent state markers (e.g., .bot_ready_state) and only remove runtime artifacts.
-   A l l   L L M   p r o m p t s   f o r   t r a n s l a t i o n   m u s t   e x p l i c i t l y   f o r b i d   m e t a - c o m m e n t a r y   a n d   e n f o r c e   ' o u t p u t - o n l y '   c o n s t r a i n t s .
 -   * * I n p u t   V a l i d a t i o n : * *   A l l   u s e r - f a c i n g   c o m m a n d s   m u s t   v a l i d a t e   i n p u t s   a n d   p r o v i d e   s e n s i b l e   d e f a u l t s   o r   c l e a r   e r r o r   m e s s a g e s .   N e v e r   g r e e d i l y   a s s u m e   u s e r   i n p u t   m a t c h e s   a   p a r a m e t e r   j u s t   b a s e d   o n   l e n g t h .
 -   A l l   t o k e n   l i m i t s ,   c o n t e x t   w i n d o w   s i z e s ,   a n d   m o d e l   p a r a m e t e r s   m u s t   b e   c o n f i g u r a b l e   v i a   . e n v ;   n o   m a g i c   n u m b e r s   i n   c o d e .   H a r d c o d e d   t o k e n   c o u n t s   a n d   f i x e d   c o n v e r s a t i o n   s l i c e s   a r e   s t r i c t l y   p r o h i b i t e d .
 -   L o n g - f o r m   t r a n s l a t i o n s   m u s t   u s e   s e m a n t i c   c h u n k i n g   w i t h   c o n t e x t   a w a r e n e s s   t o   p r e v e n t   d a t a   l o s s .   N e v e r   s i l e n t l y   t r u n c a t e   t e x t .
 - Config values used for substring matching must be validated for emptiness before use.

- **Feature Interaction Suppression:** When a message is explicitly directed at the bot (detected via `is_explicitly_tagged`), background enhancement features (auto-translation, auto-summary, etc.) must be suppressed. Direct interactions take exclusive priority to prevent duplicate or conflicting output.

- **Domain Separation:** Any new features affecting message processing MUST consider DM/Group domain separation and should be implemented within the respective dedicated handler (`_handle_dm_message` or `_handle_group_message`). The main webhook router should only contain shared early-exit guards.

- **JID Normalization:** Node.js gateway implementations must normalize all incoming unofficial or device-specific JID suffixes (such as `@c.us` and `@lid`) to the official `@s.whatsapp.net` suffix before forwarding payloads to the Python backend. This ensures domain guard rails and mention detection logic function correctly against standardized JIDs.

## 4.3 WhatsApp Gateway Session Health Monitoring
- **Gateway State Management & WISP Protocol:** The Node.js gateway and Python backend communicate via the WhatsApp Inter-Service Protocol (WISP). The Gateway operates in three states: CONNECTED, RECOVERING, and DISCONNECTED. In the RECOVERING state, messages are acknowledged with HTTP 202 (QUEUED_FOR_RECOVERY) and kept in a silent queue (`recoveryMessageQueue`) to be processed upon recovery. Unrecoverable states return HTTP 503 (SESSION_CORRUPT). The Python backend expects strict Pydantic/JSON schema structures (GatewaySendResult, DeliveryResponse) and must silently queue commands (like `!claim_ownership` or `!pm`) rather than notifying the user during transient recovery.
- **Gateway State Management & WISP Protocol:** The Node.js gateway and Python backend communicate via the WhatsApp Inter-Service Protocol (WISP). The Gateway operates in three states: CONNECTED, RECOVERING, and DISCONNECTED. In the RECOVERING state, messages are acknowledged with HTTP 202 (QUEUED_FOR_RECOVERY) and kept in a silent queue (`recoveryMessageQueue`) to be processed upon recovery. Unrecoverable states return HTTP 503 (SESSION_CORRUPT). The Python backend expects strict Pydantic/JSON schema structures (GatewaySendResult, DeliveryResponse) and must silently queue commands (like `!claim_ownership` or `!pm`) rather than notifying the user during transient recovery.
- **Tiered Session Auto-Recovery:** The Node.js gateway must actively track consecutive send failures and implement a graceful, tiered recovery strategy to avoid unnecessary manual QR scans:
  - **Tier 1 (Puppeteer Restart):** Attempt to reload the underlying Puppeteer page context to resolve transient execution context errors without destroying the session.
  - **Tier 2 (Client Reinitialization):** Destroy and recreate the `whatsapp-web.js` client instance while preserving the `.wwebjs_auth` directory.
  - **Tier 3 (Nuclear Purge):** As a last resort, purge the `.wwebjs_auth` directory via `fs.rmSync` and prompt for a new QR scan.
- **Error Pattern Matching:** The gateway MUST actively monitor `sendMessage` API errors for specific patterns indicating session corruption (e.g., "No LID for user", "session corrupt", "invalid session", "ExecutionContext").
- **Immediate Recovery Strategy:** When a known session corruption pattern is detected, the gateway MUST bypass the standard N-consecutive-failures threshold and trigger an *immediate* escalation through the recovery tiers.
- **Delayed Recovery Strategy:** General timeout or disconnect errors should respect the standard consecutive failures threshold (e.g., 3 failures) before forcing a recovery escalation, to prevent unnecessary resets during transient network blips.
