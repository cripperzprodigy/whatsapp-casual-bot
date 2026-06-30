# Configuration Guide: Agentic Search & Deep Crawl

This document explains the environment variables available in `.env` to configure the behaviour, performance, and safety limits of the Agentic Search (`!s`) and Deep Crawl (`!sc`) features.

## Deep Crawl (`!sc`) Configuration

Deep Crawl is a resource-intensive feature that fetches full HTML pages. The following variables help you balance depth of research against API timeouts and LLM token costs.

| Variable | Default | Description | Bounds |
|---|---|---|---|
| `DEEP_CRAWL_ENABLED` | `true` | Enable or disable the `!sc` deep crawl search feature. | `true` or `false` |
| `LLM_TIMEOUT_SECONDS` | `300` | The maximum time (in seconds) the bot will wait for the LLM to synthesize the final deep crawl report. Complex queries with large contexts require higher timeouts. | `10` to `1200` |
| `CRAWL_TIMEOUT_SECONDS` | `15.0` | The maximum time (in seconds) the bot will wait for a single website to respond during the crawl phase. | `1.0` to `60.0` |
| `DEEP_CRAWL_MAX_URLS` | `5` | The maximum number of top search results to fetch and read. Higher numbers yield deeper research but consume more LLM tokens. | `1` to `20` |
| `MAX_TOTAL_CONTEXT_CHARS` | `15000` | The hard ceiling on the total characters sent to the LLM. The bot dynamically divides this budget across the crawled URLs (`MAX_TOTAL_CONTEXT_CHARS // DEEP_CRAWL_MAX_URLS`) to prevent context overflow. | `1000` to `100000` |
| `FALLBACK_TO_SNIPPETS` | `true` | If `true`, the bot will fall back to using search engine snippets (like `!s`) if all full-page fetches fail or are blocked by SSRF protection. If `false`, the bot will return an error message instead. | `true` or `false` |

## Agentic Search (`!s`) Configuration

Agentic Search is an iterative process where the LLM evaluates search results and refines its queries until it finds a sufficient answer.

| Variable | Default | Description | Bounds |
|---|---|---|---|
| `ENABLE_AGENTIC_SEARCH` | `true` | Enable or disable the `!s` agentic search feature globally. | `true` or `false` |
| `SEARCH_MAX_RESULTS` | `5` | The default number of search results to fetch for queries. | `1` to `20` |
| `AGENTIC_MAX_ITERATIONS` | `3` | The maximum number of search-and-refine loops the LLM is allowed to execute. Lower this if you want faster, cheaper answers. | `1` to `10` |
| `SEARCH_RESULTS_PER_QUERY` | `10` | The number of search results (snippets) to fetch from SearXNG/DuckDuckGo per query iteration. | `1` to `50` |
| `OPENROUTER_RATE_LIMIT_DELAY` | `2.0` | The delay (in seconds) the bot will sleep between iteration loops. This prevents the bot from hitting "Too Many Requests" rate limits on providers like OpenRouter. | `0.0` to `10.0` |

## Invalid Value Handling

The bot uses Pydantic `model_validator` clamping to handle invalid configuration gracefully. If you provide a value outside the allowed bounds (e.g., `DEEP_CRAWL_MAX_URLS=50`), the bot will silently clamp it to the maximum allowed value (`20`) rather than crashing on startup. If you provide a non-numeric value, the bot will fall back to the default.
