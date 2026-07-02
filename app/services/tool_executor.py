"""
Tool Execution Context — Isolated Scratchpad (Task 5).

Prevents tool execution logs from polluting the main conversation history by
routing all tool output to a per-session `tool_scratchpad` list.  The scratchpad
is injected into the LLM system prompt only while a tool is active or retrying,
and is cleared immediately after successful resolution.

Usage in a handler:
    executor = ToolExecutor(session_state=session.state)

    async with executor.execute("web_search") as ctx:
        result = await do_search(query)
        ctx.log(f"Search returned {len(result)} hits")

    # After the block, scratchpad is cleared.
    # Build prompt that includes scratchpad only when a tool is running:
    prompt = system_prompt + executor.get_scratchpad_prompt()

The session_state dict is mutated in-place so changes are visible to any code
that holds a reference to the same dict (e.g. a SQLite-backed session row).
"""

import contextlib
import logging
import time
from typing import Any, Dict, Generator

logger = logging.getLogger(__name__)

# Keys written into session_state
_KEY_CURRENT_TOOL = "current_tool"
_KEY_SCRATCHPAD = "tool_scratchpad"


class ToolExecutionContext:
    """Lightweight context object yielded inside `ToolExecutor.execute()`."""

    def __init__(self, executor: "ToolExecutor", tool_name: str) -> None:
        self._executor = executor
        self.tool_name = tool_name

    def log(self, message: str) -> None:
        """Append a message to the scratchpad for this execution."""
        self._executor.log_to_scratchpad(f"[{self.tool_name}] {message}")


class ToolExecutor:
    """Manages tool execution with scratchpad isolation.

    Accepts a mutable ``session_state`` dict (e.g. from the in-memory session
    store or a SQLite-backed SessionState row's JSON field).  All tool logs are
    routed to ``session_state["tool_scratchpad"]`` instead of the main
    conversation history.
    """

    def __init__(self, session_state: Dict[str, Any]) -> None:
        self._state = session_state
        # Ensure required keys exist
        if _KEY_SCRATCHPAD not in self._state:
            self._state[_KEY_SCRATCHPAD] = []
        if _KEY_CURRENT_TOOL not in self._state:
            self._state[_KEY_CURRENT_TOOL] = None

    # ------------------------------------------------------------------ #
    #  Scratchpad operations
    # ------------------------------------------------------------------ #

    def log_to_scratchpad(self, entry: str) -> None:
        """Append an entry to the scratchpad (never to conversation history)."""
        ts = time.strftime("%H:%M:%S", time.localtime())
        self._state[_KEY_SCRATCHPAD].append(f"[{ts}] {entry}")
        logger.debug(f"[Scratchpad] {entry}")

    def get_scratchpad_prompt(self) -> str:
        """Return the scratchpad content formatted for LLM system prompt injection.

        Returns an empty string when the scratchpad is empty so callers can safely
        concatenate without adding blank sections.
        """
        pad = self._state.get(_KEY_SCRATCHPAD, [])
        if not pad:
            return ""
        content = "\n".join(pad)
        return f"\n<tool_scratchpad>\n{content}\n</tool_scratchpad>"

    def is_tool_active(self) -> bool:
        """True when a tool is currently executing (scratchpad non-empty or current_tool set)."""
        return bool(
            self._state.get(_KEY_CURRENT_TOOL)
            or self._state.get(_KEY_SCRATCHPAD)
        )

    def clear_scratchpad(self) -> None:
        """Clear the scratchpad after successful tool resolution."""
        self._state[_KEY_SCRATCHPAD] = []
        self._state[_KEY_CURRENT_TOOL] = None
        logger.debug("[Scratchpad] Cleared after successful resolution.")

    # ------------------------------------------------------------------ #
    #  Execution context manager
    # ------------------------------------------------------------------ #

    @contextlib.asynccontextmanager
    async def execute(self, tool_name: str):
        """Async context manager for tracked tool execution.

        On entry: marks the tool as active and logs a START entry to the scratchpad.
        On success: logs DONE and clears the scratchpad.
        On exception: logs ERROR (with message), re-raises without clearing so the
          scratchpad remains available for retry / debugging; caller is responsible
          for clearing when retries are exhausted.

        Example::

            async with executor.execute("rag_search") as ctx:
                results = await do_rag(query)
                ctx.log(f"Returned {len(results)} results")
        """
        self._state[_KEY_CURRENT_TOOL] = tool_name
        self.log_to_scratchpad(f"[TOOL START] {tool_name}")
        ctx = ToolExecutionContext(self, tool_name)
        try:
            yield ctx
            self.log_to_scratchpad(f"[TOOL DONE] {tool_name}")
            self.clear_scratchpad()
        except Exception as exc:
            self.log_to_scratchpad(f"[TOOL ERROR] {tool_name}: {exc}")
            self._state[_KEY_CURRENT_TOOL] = None
            raise
