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

### Troubleshooting

- **`!search` vs `!s`**: `!search` relies directly on the underlying `HybridSearchService` with standard latency and no refinement loop. If `!search` fails, a generic error is surfaced. `!s` utilizes the `AgenticSearchOrchestrator` to multi-hop. If `!s` returns "Feature Disabled", ensure you are the Bot Owner and run `!config toggle agentic_search on` to turn it on dynamically.

---

## Deep Crawl Search (`!sc`)

The `!sc` command extends the search pipeline by fetching and parsing **full HTML page content** from top search results, then synthesizing a comprehensive report. While `!s` works with snippets (title + description), `!sc` reads the actual pages for in-depth research.

### Key Files
1. **`app/services/deep_crawl_service.py`**: The `DeepCrawlService` class handling URL fetching, HTML parsing, and LLM synthesis.
2. **`app/prompts/search_prompts.py`**: Contains `DEEP_CRAWL_SYNTHESIZER_SYSTEM` for detailed report generation.
3. **`app/config.py`**: `DEEP_CRAWL_ENABLED`, `DEEP_CRAWL_MAX_URLS`, `DEEP_CRAWL_TIMEOUT_SECONDS`.

### Configuration & Toggle

Dual-layer control (matches `!globaltrans` pattern):
1. **Environment Config**: `DEEP_CRAWL_ENABLED=false` inside `.env` (default: disabled).
2. **Runtime Toggle**: Owner command `!sc_toggle on|off`. State persisted to `data/global_config.json` and survives restarts.

### ASCII Flow Diagram

```text
User: "!sc <query>"
  |
  v
Message Handler (app/commands.py)
  |-- Check app_settings.DEEP_CRAWL_ENABLED
  |   +-- FALSE -> Reply "Disabled by admin."
  |   +-- TRUE  -> Send "Crawling the web..."
  v
DeepCrawlService.search_and_crawl(query)
  |
  +---> 1. HybridSearchService.search(query) -> Top 5 URLs
  |
  +---> 2. Async Fetch Loop (httpx, Semaphore=3)
  |         - URL 1 -> Fetch HTML -> BeautifulSoup Parse -> Text (max 2000 chars)
  |         - URL 2 -> Fetch HTML -> BeautifulSoup Parse -> Text
  |         - URL 3 -> Fetch HTML -> (Timeout/Error) -> Skip
  |         - ...
  |
  +---> 3. Aggregate Context (max 12000 chars total)
  |         "--- Content from [Title] (URL) ---"
  |         [Extracted Text]
  |
  +---> 4. LLM Synthesis (ask_llm + DEEP_CRAWL_SYNTHESIZER_SYSTEM)
  |
  v
send_long_message() -> WhatsApp User
```

### Graceful Degradation

- **Per-URL Timeout**: Each URL fetch has a configurable timeout (default 10s). Failed URLs are silently skipped.
- **All Fetches Fail**: Falls back to snippet-based synthesis (same quality as `!s`).
- **LLM Synthesis Timeout**: Returns raw crawled content truncated to 3000 chars.
- **Global Timeout**: Entire operation capped at 180s with `asyncio.wait_for`.
- **Single-Response Contract**: `search_and_crawl()` ALWAYS returns `str`, NEVER raises.

### Command Comparison

| Feature | `!search` | `!s` | `!sc` |
|---|---|---|---|
| Search Source | SearXNG/DDG Snippets | SearXNG/DDG Snippets | Full Page Content |
| LLM Iterations | 0 (raw results) | Up to 2 (gap analysis) | 1 (synthesis only) |
| Toggle | Always on | `!config toggle agentic_search` | `!sc_toggle on\|off` |
| Speed | Fast (~2s) | Medium (~15s) | Slow (~30s) |
| Depth | Shallow | Medium | Deep |

