"""
Natural Language Search Intent Detector (WEB-SEARCH-FIX-001).

Detects when a user's conversational message implies a web search request,
even when they don't use the explicit `!sc` or `!s` commands.  When detected,
the extracted query is passed to the deep crawl service automatically.

Design principles:
  - Start-anchored patterns reduce false positives (e.g. "I looked for my keys"
    does NOT trigger because "looked" is past tense and not at string start).
  - Returns the extracted query so the caller can rewrite the internal command
    to `!sc <query>` without re-parsing.
  - Patterns are ordered by specificity — most specific first.
"""

import re
from typing import Optional, Tuple

# ── Natural language search patterns ─────────────────────────────────────────
# Each pattern has exactly TWO capture groups:
#   Group 1: optional filler word (for, up, for the, etc.)
#   Group 2: the actual search query
#
# Patterns are start-anchored (^) to avoid false positives in the middle of
# narrative sentences like "I looked for my keys this morning".

_SEARCH_PATTERNS: list[re.Pattern] = [
    # Direct commands — "search for X", "search X"
    re.compile(r"(?i)^search(?:\s+for)?\s+(.+)", re.IGNORECASE),
    # "look up X", "look for X"
    re.compile(r"(?i)^look\s+(?:up|for)\s+(.+)", re.IGNORECASE),
    # "google X"
    re.compile(r"(?i)^google\s+(.+)", re.IGNORECASE),
    # "find X" — but NOT "find my keys" (handled by context below)
    re.compile(r"(?i)^find\s+(?:the\s+|latest\s+|recent\s+|current\s+)?(.+)", re.IGNORECASE),
    # "what are the latest X", "what's the latest X"
    re.compile(r"(?i)^what(?:'s|s| are)\s+(?:the\s+)?latest\s+(.+)", re.IGNORECASE),
    # "what are the recent X"
    re.compile(r"(?i)^what(?:'s|s| are)\s+(?:the\s+)?recent\s+(.+)", re.IGNORECASE),
    # "check X news", "check the news about X"
    re.compile(r"(?i)^check\s+(?:the\s+)?(.+?)(?:\s+news)?$", re.IGNORECASE),
    # "can you search (for) X"
    re.compile(r"(?i)^can\s+you\s+search(?:\s+for)?\s+(.+)", re.IGNORECASE),
    # "can you look up X"
    re.compile(r"(?i)^can\s+you\s+look\s+(?:up|for)\s+(.+)", re.IGNORECASE),
    # "can you find X"
    re.compile(r"(?i)^can\s+you\s+find\s+(.+)", re.IGNORECASE),
    # "search the web for X"
    re.compile(r"(?i)^search\s+the\s+web\s+for\s+(.+)", re.IGNORECASE),
    # "look up online X"
    re.compile(r"(?i)^look\s+up\s+online\s+(.+)", re.IGNORECASE),
]

# Phrases that should NOT trigger search even if they match a pattern above.
# These are conversational/narrative uses, not search requests.
_FALSE_POSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)\b(my keys|my phone|my wallet|my bag)\b"),  # "find my keys"
    re.compile(r"(?i)^find\s+(?:my|your|his|her|their|our)\s"),  # "find my way"
    re.compile(r"(?i)^find\s+(?:it|them|out)\s*$"),  # "find it" / "find out"
    re.compile(r"(?i)\blooked\b"),  # past tense — "I looked for..."
    re.compile(r"(?i)\bsearched\b"),  # past tense — "I searched for..."
]


def detect_search_intent(text: str) -> Tuple[bool, Optional[str]]:
    """Determine if *text* implies a web search request.

    Parameters
    ----------
    text:
        Raw user message text.

    Returns
    -------
    Tuple[bool, Optional[str]]
        ``(True, query)`` if a search intent is detected — *query* is the
        extracted search term.  ``(False, None)`` otherwise.
    """
    if not text or not text.strip():
        return False, None

    stripped = text.strip()

    # Check false-positive exclusions first
    for fp_pattern in _FALSE_POSITIVE_PATTERNS:
        if fp_pattern.search(stripped):
            return False, None

    # Check positive patterns
    for pattern in _SEARCH_PATTERNS:
        match = pattern.match(stripped)
        if match:
            # Group 2 is the query; fallback to group 1 or full match
            query = match.group(1).strip() if match.lastindex and match.lastindex >= 1 else match.group(0)
            # Clean up trailing punctuation
            query = re.sub(r"[?!.,]+$", "", query).strip()
            if query and len(query) >= 2:
                return True, query

    return False, None