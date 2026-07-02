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

# 🧩 Natural language search patterns 🧩
# Each pattern has exactly ONE capture group:
#   Group 1: the actual search query (e.g., (.+) at end of pattern)
#
# Patterns are start-anchored (^) to avoid false positives in the middle of
# narrative sentences like "I looked for my keys this morning".

_SEARCH_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)^search (?:the web )?for (.+)"),
    re.compile(r"(?i)^look (?:up|for) (.+)"),
    re.compile(r"(?i)^google (.+)"),
    re.compile(r"(?i)^find (?:me )?(.+)"),
    re.compile(r"(?i)^what(?:'s| are) the (?:latest|recent) (.+)"),
    re.compile(r"(?i)^check (.+)"),
    re.compile(r"(?i)^can you (?:search|look up|find) (.+)"),
    re.compile(r"(?i)^search (?:the )?web for (.+)"),
    re.compile(r"(?i)^look up online (.+)"),
]

# Phrases that should NOT trigger search even if they match a pattern above.
# These are conversational/narrative uses, not search requests.
_FALSE_POSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)\b(my keys|my phone|my wallet|my bag)\b"),  # "find my keys"
    re.compile(r"(?i)^find\s+(?:my|your|his|her|their|our)\s"),  # "find my way"
    re.compile(r"(?i)^find\s+(?:it|them|out)\s*$"),  # "find it" / "find out"
    re.compile(r"(?i)\blooked\b"),  # past tense — "I looked for..."
    re.compile(r"(?i)\bsearched\b"),  # past tense — "I searched for..."
    re.compile(r"(?i)^google told me\b"), # "Google told me..."
]

TRIGGER_PHRASES = [
    r'(can you|could you|please)\s+',
    r'(search for|look up|find|google)\s+'
]

def clean_query(text: str, bot_name: str) -> str:
    """Removes bot mention and common conversational trigger phrases to isolate the raw search query."""
    # Remove bot mention
    text = re.sub(rf'@{re.escape(bot_name)}\s*', '', text, flags=re.IGNORECASE)
    # Remove trigger phrases
    for phrase in TRIGGER_PHRASES:
        text = re.sub(phrase, '', text, flags=re.IGNORECASE)
    # Trim and normalize whitespace
    return ' '.join(text.split())

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
            # Extract Group 1 (the query), not Group 0 (full match)
            query = match.group(1).strip() if match.lastindex else match.group(0)
            
            # Clean up trailing punctuation
            query = re.sub(r"[?!.,]+$", "", query).strip()
            
            # Exclude false positives
            if query.lower() in ["it", "this", "that"]:
                continue
                
            if query and len(query) >= 2:
                return True, query

    return False, None