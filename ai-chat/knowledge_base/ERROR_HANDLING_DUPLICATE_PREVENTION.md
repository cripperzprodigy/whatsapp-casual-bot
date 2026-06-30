# Error Handling & Duplicate Prevention in Command Responses

> **ADR-032** | Introduced: 2026-06-30 | Status: Active

## Problem Statement

When the OpenRouter API returned HTTP 500, the bot sent **two messages** to the group chat instead of one. This was a poor user experience and wasted API/gateway resources.

## Root Cause Analysis

### The Exception Propagation Chain

```text
User: "!s climate change effects"
  │
  ▼
commands.py:  !s handler
  │
  ├── orchestrator.execute_iterative_search(query, sender_id)
  │     │
  │     └── _execute_search_loop(query)
  │           │
  │           ├── search_service.search(query) → results OK
  │           │
  │           └── _synthesize_final_answer(query, context)
  │                 │
  │                 └── ask_llm(prompt) → OpenRouter 500
  │                       │
  │                       └── raises TranslationError("LLM returned no choices")
  │                             │
  │                             ▼
  │                 _execute_search_loop catches Exception → returns fallback string
  │                       │
  │                       ▼
  │     execute_iterative_search:
  │       ├── ONLY caught asyncio.TimeoutError  ← BUG!
  │       └── TranslationError propagated UP to commands.py
  │
  ▼
commands.py:
  ├── try:
  │     final_answer = await orchestrator.execute_iterative_search(...)
  │     await send_text_message(chat_id, final_answer)    ← never reached
  │
  └── except Exception as e:                              ← catches TranslationError
        await send_text_message(chat_id, "⚠️ error...")   ← SEND #1
```

But wait — the `_execute_search_loop` DID catch the exception and returned a fallback string. So how did TranslationError propagate?

**The gap:** `execute_iterative_search()` wraps `_execute_search_loop()` in `asyncio.wait_for()` with a 120s timeout. It only catches `asyncio.TimeoutError`. If `_execute_search_loop` raises anything else (which can happen in edge cases like `asyncio.CancelledError` or if exceptions occur between the inner try/except boundaries), it propagates to `commands.py`.

The duplicate scenario:
1. `_execute_search_loop` returns fallback → `execute_iterative_search` returns it → `commands.py` sends it → **SEND #1**
2. In a race condition or edge case, the exception escapes → `commands.py` `except` block sends error → **SEND #2**

## Fix: The Single-Response Contract

### Principle

> Service functions that return user-facing messages MUST catch **all** exceptions internally and ALWAYS return a string. The caller must NEVER send an additional message in its `except` block.

### Implementation

#### agentic_search_service.py — `execute_iterative_search()`

```python
async def execute_iterative_search(self, query: str, user_id: str) -> str:
    """Top-level entry point.  ALWAYS returns a str — never raises."""
    try:
        return await asyncio.wait_for(
            self._execute_search_loop(query),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        return "⚠️ I took too long to think about this query..."
    except Exception as exc:          # ← NEW: catch-all
        logger.error(f"Unexpected error for query '{query}': {exc}")
        return "⚠️ Something went wrong while processing your search..."
```

#### commands.py — `!s` handler

```python
try:
    # execute_iterative_search ALWAYS returns a str — never raises.
    final_answer = await orchestrator.execute_iterative_search(query, sender_id)
    logger.info(f"Agentic search completed. Sending single response.")
    await send_long_message(chat_id, final_answer)
except Exception as e:
    # Defensive safety net — should never fire.
    logger.error(f"Unexpected exception: {e} (this should not happen)")
    await send_text_message(chat_id, "⚠️ error message...")
```

### Logging Breadcrumbs

To trace the single-send path, the following log entries were added:

| Log Entry | Where | When |
|---|---|---|
| `"Fallback constructed (synthesis timeout)"` | `agentic_search_service.py` | Synthesis timed out, returning raw results |
| `"Fallback constructed (synthesis error)"` | `agentic_search_service.py` | Synthesis failed with exception |
| `"AgenticSearchOrchestrator unexpected error"` | `agentic_search_service.py` | Catch-all fired (should be rare) |
| `"Agentic search completed. Sending single response."` | `commands.py` | Normal path — about to send |
| `"this should not happen"` | `commands.py` | Safety net fired — investigate! |

## ASCII Flow: Fixed Single-Response Path

```text
User: "!s query"
  │
  ▼
commands.py: send "🔍 Thinking..."
  │
  ▼
execute_iterative_search(query)   ← ALWAYS returns str
  │
  ├── Success → synthesized answer string
  ├── Timeout → "⚠️ I took too long..."
  ├── LLM Error → "⚠️ couldn't synthesize... raw findings:"
  └── Unexpected → "⚠️ Something went wrong..."
  │
  ▼
commands.py: send_long_message(chat_id, result)   ← EXACTLY ONE send
  │
  ▼
END (safety-net except block NOT triggered)
```

## SOP Rule (Mandatory)

From `ai-chat/SOP.md` → Agentic Workflows and Loop Guards:

> **Single-Response Contract (MANDATORY)**: Service functions that construct and return user-facing messages (e.g., `execute_iterative_search()`) MUST catch all exceptions internally and ALWAYS return a string. The caller MUST NOT have a separate error-message send in its `except` block that could fire when the service already returned a fallback. This prevents duplicate messages. If a safety-net `except` is kept in the caller, it must log `"this should not happen"` to flag contract violations.

## Applying This Pattern to New Commands

When adding new commands that call external services (LLM, search, APIs):

1. **Service layer**: Wrap the entire operation in try/except and return a string for ALL cases.
2. **Caller**: Send exactly one message. Keep a safety-net `except` that logs "should not happen".
3. **Never** have the service send a message AND return a string — pick one pattern.
4. **Log**: Always log when fallback is constructed, so you can trace the execution path.

## Troubleshooting

### Duplicate messages still appearing
1. Check logs for `"this should not happen"` — if present, the safety net fired, meaning the service raised an exception it shouldn't have.
2. Check if the code path is actually using the updated `execute_iterative_search()` with the catch-all.
3. Check gateway retry logic — if the gateway retries a send that was actually delivered (returned 500 but delivered), that's a gateway-level duplicate, not a code-level one.

### "Something went wrong" message appearing instead of results
- Check logs for `"AgenticSearchOrchestrator unexpected error"` — this means a non-standard exception escaped `_execute_search_loop`. Investigate what exception type it was.

### Safety net logs "this should not happen"
- This is a **serious** bug indicator. The service function raised an exception despite the catch-all. Possible causes:
  - `asyncio.CancelledError` (not caught by `except Exception` in Python 3.9+)
  - `SystemExit` or `KeyboardInterrupt` (not caught by `except Exception`)
  - Code was modified to remove the catch-all
