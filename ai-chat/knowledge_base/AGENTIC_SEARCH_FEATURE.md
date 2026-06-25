# Agentic Search Feature (`!s`)

The Agentic Search feature introduces multi-hop reasoning capabilities to the WhatsApp Casual Bot. Instead of executing a single linear search query like the legacy `!search` command, the `!s` command leverages an LLM to evaluate search results, identify information gaps, and refine subsequent queries to build a comprehensive answer.

## Architectural Overview

The feature is orchestrated via the `AgenticSearchOrchestrator` and controlled via the new `FeatureFlagService` which uses Role-Based Access Control (RBAC).

### Key Files
1. **`app/services/agentic_search_service.py`**: The core orchestrator holding the loop limits, gap analysis parsing, and synthesis logic.
2. **`app/prompts/search_prompts.py`**: Contains the strict system prompts (`GAP_ANALYZER_SYSTEM`, `SYNTHESIZER_SYSTEM`) enforcing structured JSON outputs for decision making.
3. **`app/services/search_service.py`**: The underlying `HybridSearchService`, now enhanced with URL deduplication to optimize LLM context window tokens.
4. **`app/services/feature_flag_service.py`**: The SQLite database-backed service that manages the runtime enablement of the feature to prevent uncontrolled resource exhaustion.
5. **`app/commands.py`**: Houses the message handlers and the dynamic `!help` menu rendering.

## Configuration & Feature Flags

Because Agentic loops consume significantly more API tokens and take longer to execute, the feature is disabled by default and guarded by two layers:
1. **Environment Config**: `ENABLE_AGENTIC_SEARCH=false` inside `.env`.
2. **Runtime Toggle**: The Bot Owner can run `!config toggle agentic_search on|off` to dynamically turn the feature on or off without restarting the container. This state is saved directly into `bot.db` via `GlobalSettings`.

## ASCII Flow Diagram

```text
User: "!s <complex query>"
  |
  v
Message Handler (app/commands.py)
  |-- Check FeatureFlagService.is_enabled("agentic_search")
  |   +-- FALSE -> Reply "Feature Disabled"
  |   +-- TRUE  -> Send "Thinking..."
  v
AgenticSearchOrchestrator
  |
  +---> [Iteration 0]
  |       |---> HybridSearch (Query A)
  |       |---> Gap Analysis LLM (Prompt: GAP_ANALYZER_SYSTEM)
  |       |---> Decision: Need more info?
  |               |
  |               +-- YES --> [Iteration 1]
  |               |             |---> Refine Query (Query B)
  |               |             |---> HybridSearch (Query B)
  |               |             |---> Gap Analysis LLM
  |               |             |---> Decision: Stop (Max Reached or Sufficient)
  |               |
  |               +-- NO ---> Break Loop
  |
  +---> Final Synthesis LLM (Prompt: SYNTHESIZER_SYSTEM)
          | (Combines Context A + Context B)
  v
Formatted WhatsApp Response
```

## Defense in Depth (Timeouts & Fallbacks)

To prevent the WhatsApp Webhook from hanging indefinitely and getting terminated by the gateway or user frustration:
- **Global Timeout**: The entire execution loop is wrapped in a hard 14-second `asyncio.wait_for` constraint.
- **Local Timeouts**: Search step (3s), Gap Analysis (5s), and Final Synthesis (6s).
- **Graceful Degradation**: If the LLM throws an exception (e.g., token limit or connection drop) during Gap Analysis, the system catches the error, breaks the loop immediately, and instructs the Synthesizer LLM to generate the best possible answer with whatever partial context it has accumulated so far.

## Dynamic Help Menu

The `!help` command now intelligently parses the `FeatureFlagService` and the user's role.
- **Regular Users**: If `agentic_search` is OFF, the command is completely hidden. If ON, it appears under "AI Tools".
- **Owners/Admins**: If OFF, it appears as `!s (Currently Disabled)` so administrators know the command exists and can toggle it via `!config`.
