# Message Chunking & Sequential Sending

> **ADR-030** | Introduced: 2026-06-30 | Status: Active

## Problem Statement

The bot sends all text responses as a single HTTP POST payload to the WhatsApp gateway (`/message/sendText`). When LLM-generated responses, agentic search reports, or AI replies exceed ~3000 characters, the `httpx` client hits a `ReadTimeout` (default 5s). The retry mechanism re-sends the same oversized payload, which either fails again or — worse — succeeds on retry after the first attempt was silently delivered, producing **duplicate messages**.

### Evidence from Production Logs

```
httpx.ReadTimeout: TimeoutError()
Failed to send message to 120363XXXX@g.us (Attempt 1/3): ReadTimeout...
Failed to send message to 120363XXXX@g.us (Attempt 2/3): ReadTimeout...
```

## Solution: Smart Sender Utility

### Key Files

| File | Purpose |
|---|---|
| `app/utils/__init__.py` | Package init |
| `app/utils/message_splitter.py` | Core splitting algorithm + `send_long_message()` |
| `app/commands.py` | Integration at `!s`, `!search`, `!a` |
| `app/router_webhook.py` | Integration at DM + group chatty replies |
| `app/whatsapp_gateway.py` | Timeout increase (5s → 15s) |

### Configuration Constants

```python
MAX_CHUNK_SIZE = 2500          # Max characters per chunk
INTER_CHUNK_DELAY = 1.0        # Seconds between sequential sends
PART_HEADER_TEMPLATE = "📄 *Part {current}/{total}*\n\n"
```

## Splitting Algorithm

The algorithm uses **hierarchical boundary detection** — it tries the most readable split first and only falls back to finer granularity when necessary:

```text
Input: 5172-char search report
  │
  ├── Step 1: Split by paragraphs (\n\n)
  │     Accumulate paragraphs into a chunk until > 2500 chars.
  │     If a paragraph itself is > 2500 chars:
  │       │
  │       ├── Step 2: Split by sentences (regex: (?<=[.!?])\s+)
  │       │     Accumulate sentences until > 2500 chars.
  │       │     If a sentence itself is > 2500 chars:
  │       │       │
  │       │       ├── Step 3: Split by words (whitespace)
  │       │       │     Accumulate words until > 2500 chars.
  │       │       │     If a single word is > 2500 chars (e.g. URL):
  │       │       │       │
  │       │       │       └── Step 4: Hard cut at max_length
  │       │       │
  │       │       └── Accumulate words
  │       └── Accumulate sentences
  └── Accumulate paragraphs

Output: ["chunk1 (≤2500)", "chunk2 (≤2500)", "chunk3 (≤2500)"]
```

### Why This Order?

- **Paragraphs first**: Preserves topic boundaries in search results (each result = paragraph).
- **Sentences second**: Preserves semantic coherence. Readers don't see cut-off thoughts.
- **Words third**: Last resort for very long sentences (e.g., code blocks, JSON).
- **Hard cut**: Only for tokens that are themselves > 2500 chars (extremely rare — massive URLs or base64 strings).

## ASCII Flow: send_long_message()

```text
send_long_message(chat_id, text)
  │
  ├── len(text) ≤ 2500?
  │     └── YES → send_text_message(chat_id, text) directly
  │                (zero overhead, same as before)
  │
  └── NO → split_text_into_chunks(text, 2500)
            │
            ├── For each chunk[i]:
            │     ├── Prepend: "📄 Part {i+1}/{total}\n\n"
            │     ├── First chunk only: include quoted_msg_id (reply thread)
            │     ├── send_text_message(chat_id, header + chunk)
            │     │
            │     ├── SUCCESS?
            │     │     └── YES → await asyncio.sleep(1.0), continue
            │     │
            │     └── FAILURE?
            │           ├── Log error
            │           ├── Send: "⚠️ Message delivery interrupted at part X/Y"
            │           └── ABORT remaining chunks, return result
            │
            └── All chunks sent → return last GatewaySendResult
```

## Integration Points

Only code paths that produce **potentially long text** use `send_long_message()`. Short, fixed-length messages (error strings, help text, confirmations, command acknowledgements) remain on `send_text_message()` directly.

| Code Path | File:Line | Description |
|---|---|---|
| `!s` (agentic search) | `commands.py:889` | LLM-synthesized multi-hop search reports |
| `!search` results | `commands.py:854` | Formatted search result listings |
| `!a` (AI ask) | `commands.py:1301` | Free-form LLM responses |
| DM chatty reply | `router_webhook.py:265` | AI conversational replies in DMs |
| Group chatty reply | `router_webhook.py:159` | AI replies triggered by @mention or frequency |
| Group burst reply | `router_webhook.py:169` | Follow-up burst messages in groups |

## Gateway Timeout Fix

The `httpx.AsyncClient` in `send_text_message()` previously used the library default timeout (5 seconds). This was insufficient for the gateway to process even moderate payloads under load.

```python
# Before:
async with httpx.AsyncClient() as client:        # default 5s timeout

# After:
async with httpx.AsyncClient(timeout=15.0) as client:  # explicit 15s
```

With chunking keeping payloads ≤ 2500 chars, 15s is generous headroom.

## SOP Compliance

**Rule added to SOP.md → Agentic Workflows and Loop Guards:**

> **Outbound Message Chunking (MANDATORY)**: Any code path that sends potentially long text (LLM responses, search results, AI replies) MUST use `send_long_message()` from `app/utils/message_splitter.py` instead of raw `send_text_message()`. Short, fixed-length messages may use `send_text_message()` directly. Chunks must not exceed 2500 characters and must be split at natural boundaries. Sequential chunks must have a 1-second inter-chunk delay.

## Test Results

```
✅ Short message (11 chars):         1 chunk
✅ Empty text:                        0 chunks
✅ Paragraph split (3×1000 chars):   2 chunks, max 2002 chars
✅ Sentence split (80 sentences):    8 chunks, max 472 chars
✅ Word split (600 words):           15 chunks, max 199 chars
✅ Long URL/word (3000-char token):  4 chunks
✅ Realistic search (5172 chars):    3 chunks, max 2077 chars
```

## Troubleshooting

### Messages still timing out
- Check that the code path uses `send_long_message()`, not `send_text_message()`.
- Verify `MAX_CHUNK_SIZE` hasn't been accidentally increased above 3000.
- Check gateway logs for HTTP 500/503 — these indicate session issues, not payload size.

### Part headers showing on short messages
- `send_long_message()` only adds headers when `total > 1`. Single-chunk messages have no header.

### Chunks splitting mid-word
- This should not happen. The algorithm splits at sentence/word boundaries first. If you see cut words, check if the text contains very long strings without whitespace (URLs, JSON). The hard-cut fallback handles these.

### Duplicate messages reappearing
- Chunking alone doesn't fix all duplicate scenarios. Also check:
  - **Single-Response Contract** (SOP): Service functions must return strings, not raise.
  - **Gateway retry logic**: If chunk attempt 1 times out but was actually delivered, retry delivers again. The 15s timeout mitigates this by reducing false timeouts.

### Want to change chunk size or delay
- Edit `MAX_CHUNK_SIZE` and `INTER_CHUNK_DELAY` in `app/utils/message_splitter.py`.
- `send_long_message()` also accepts `max_chunk_size` as a parameter for per-call override.
