# Web Search Protocol (WEB-SEARCH-FIX-001 / ADR-042)

> **ADR Reference:** ADR-042 (2026-07-02)
> **Files:** `app/utils/search_intent.py`, `app/services/deep_crawl_service.py`, `app/router_webhook.py`

---

## Overview

The web search system supports both explicit commands and natural language triggers:

| Input Type | Example | Flow |
|-----------|---------|------|
| Explicit command | `!sc FIFA results` | → `commands.py` → `DeepCrawlService` |
| Explicit command | `!s FIFA results` | → `commands.py` → `AgenticSearchOrchestrator` |
| Natural language | `search for FIFA results` | → `search_intent.py` → `DeepCrawlService` |
| Natural language | `look up the weather` | → `search_intent.py` → `DeepCrawlService` |

---

## Natural Language Intent Patterns

`detect_search_intent(text)` in `app/utils/search_intent.py` matches these patterns:

| Pattern | Example trigger |
|---------|----------------|
| `^search (for)? X` | "search for FIFA results" |
| `^look (up\|for) X` | "look up the news" |
| `^google X` | "google weather Singapore" |
| `^find X` | "find the latest scores" |
| `^what's the latest X` | "what are the latest updates?" |
| `^what are the recent X` | "what are the recent developments?" |
| `^check X` | "check the news" |
| `^can you search (for)? X` | "can you search for Python docs?" |
| `^can you look up X` | "can you look up the time?" |
| `^can you find X` | "can you find recent articles?" |
| `^search the web for X` | "search the web for AI trends" |
| `^look up online X` | "look up online the score" |

*Note: All regex patterns use a specific Capture Group 1 to extract ONLY the targeted query (X) while discarding the trigger prefix words. E.g., "search the web for batam news" extracts strictly "batam news".*

### False Positive Exclusions

These inputs do NOT trigger search:
- `"find my keys"` — possessive "my/your/his/her"
- `"I looked for my phone"` — past tense
- `"I searched for hours"` — past tense
- `"find it"` / `"find out"` — pronoun object

---

## Time-Aware Synthesis (ADR-042)

Every `DeepCrawlService._synthesize()` call now injects:

```
[SYSTEM TIME: 2026-07-02 12:00 UTC]
Interpret 'latest', 'recent', 'yesterday', 'today' relative to this time.
```

This enables the LLM to:
- Understand `"latest news"` = published within the last 24 hours
- Understand `"yesterday's results"` = 2026-07-01
- Avoid hallucinating dates when context mentions "this week"

---

## Enforced Search-Then-Reply Flow

```
DM Message: "look up latest FIFA results"
        │
        ├─► detect_search_intent() → (True, "latest FIFA results")
        │
        ├─► deep_crawl_enabled AND CHATTY_SEARCH_DEFAULT?
        │         YES ↓
        │
        ├─► await asyncio.wait_for(
        │       DeepCrawlService.search_and_crawl("latest FIFA results"),
        │       timeout=settings.LLM_SEARCH_TIMEOUT (90s)
        │   )
        │
        ├─► Search result returned → send_long_message(result)
        │
        └─► return  ← Chatty LLM call is SKIPPED

DM Message: "what's the weather like?" (no intent)
        │
        └─► Falls through to Chatty engine (standard AI reply)
```

---

## Tuning

| Setting | Default | Effect |
|---------|---------|--------|
| `CHATTY_SEARCH_DEFAULT` | `True` | Enable/disable natural language search in Chatty |
| `DEEP_CRAWL_ENABLED` | `True` | Enable/disable deep crawl globally |
| `DEEP_CRAWL_MAX_URLS` | `5` | URLs crawled per query |
| `LLM_SEARCH_TIMEOUT` | `90` | LLM Timeout for Search Synthesis (seconds) |
| `CRAWL_TIMEOUT_SECONDS` | `15` | Per-URL fetch timeout |
| `MAX_TOTAL_CONTEXT_CHARS` | `15000` | Max context sent to LLM |
