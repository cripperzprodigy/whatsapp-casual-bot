# Tool Executor — Scratchpad Isolation

> **Status:** Active
> **Files:** `app/services/tool_executor.py`

---

## Overview

`ToolExecutor` prevents tool execution logs from polluting the main conversation history. All tool output is routed to `session_state["tool_scratchpad"]`, injected into the LLM system prompt **only while a tool is active**, and cleared on successful resolution.

---

## Problem Solved

Without isolation, tool execution logs appended to `conversation_history` bloat the context window with internal orchestration noise, reducing LLM response quality and exposing debugging artefacts to users.

---

## Usage

```python
from app.services.tool_executor import ToolExecutor

# Attach to session state (in-memory or SQLite-backed SessionState dict)
executor = ToolExecutor(session_state=session.state)

# Execute with automatic scratchpad management
async with executor.execute("web_search") as ctx:
    results = await do_web_search(query)
    ctx.log(f"Fetched {len(results)} results from DuckDuckGo")
    ctx.log(f"Top result: {results[0]['title']}")

# Scratchpad is CLEARED after the block — history is clean

# Build prompt: inject scratchpad only when a tool is active
prompt = base_system_prompt + executor.get_scratchpad_prompt()
# → "" if no tool running
# → "<tool_scratchpad>\n[12:34:01] [web_search] Fetched 5 results\n</tool_scratchpad>" if active
```

---

## Scratchpad Lifecycle

```
executor.execute("tool_name")
        │
        ├─ __aenter__: sets current_tool="tool_name"
        │              logs "[TOOL START] tool_name" to scratchpad
        │              yields ToolExecutionContext
        │
        ├─ Inside block: ctx.log("...") → appends to scratchpad (NOT history)
        │
        ├─ SUCCESS exit: logs "[TOOL DONE] tool_name"
        │                clears scratchpad & current_tool  ← history remains clean
        │
        └─ EXCEPTION: logs "[TOOL ERROR] tool_name: <msg>"
                      clears current_tool
                      PRESERVES scratchpad  ← available for retry/debug
                      re-raises exception
```

---

## API Reference

| Method | Description |
|--------|-------------|
| `ToolExecutor(session_state)` | Attach to a mutable state dict. Initialises keys if absent. |
| `log_to_scratchpad(entry)` | Append a timestamped log entry to the scratchpad. |
| `get_scratchpad_prompt()` | Returns `<tool_scratchpad>…</tool_scratchpad>` or `""` if empty. |
| `is_tool_active()` | `True` when `current_tool` is set or scratchpad is non-empty. |
| `clear_scratchpad()` | Wipe scratchpad and `current_tool`. Called automatically on success. |
| `execute(tool_name)` | Async context manager wrapping a full tool execution lifecycle. |

---

## session_state Keys

| Key | Type | Description |
|-----|------|-------------|
| `current_tool` | `str \| None` | Name of the tool currently executing. |
| `tool_scratchpad` | `list[str]` | Timestamped log entries from the current execution. Never touches `conversation_history`. |

These keys are also present in the `SessionState` SQLAlchemy model (`app/state.py`) for durability across restarts. See **SESSION_PERSISTENCE_GUIDE.md** and ADR-037.

---

## Standard History Export

Tool logs are never in `conversation_history`. Standard message export (e.g., `!summary`) will never contain scratchpad content, even for multi-step tool chains.

```
session_state = {
    "conversation_history": [
        {"role": "user",      "content": "search for Python tutorials"},
        {"role": "assistant", "content": "Here are the top results: ..."},
    ],
    "tool_scratchpad": [],      ← cleared after successful tool run
    "current_tool": None,
}
# History is clean — no "[TOOL START]", "[TOOL DONE]", or internal logs
```
