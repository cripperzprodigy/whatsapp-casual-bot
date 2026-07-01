# RAG Memory Engine — Active Ingestion Pipeline

> **ADR Reference:** ADR-030 (2026-07-01)  
> **Status:** Active  
> **Files:** `app/services/ai_memory_engine.py`, `app/router_webhook.py`, `app/config.py`, `scripts/backfill_rag.py`

---

## Overview

The RAG (Retrieval-Augmented Generation) memory engine gives the bot persistent, cross-session memory. Every relevant message is embedded and stored in a per-chat ChromaDB vector database. Before generating any reply, the engine retrieves the most semantically similar past messages and injects them into the system prompt, allowing the bot to remember facts (names, preferences, topics) stated minutes, hours, or days earlier.

The pipeline operates **fully asynchronously** — ingestion never blocks the FastAPI event loop or the webhook response cycle.

---

## 🗂️ Storage Layout (Context Isolation)

Each chat gets a completely isolated directory. DM data cannot appear in a group's retrieval results and vice versa.

```
./data/contacts/
└── {safe_chat_id}/           ← derived: chat_id.replace('@','_').replace('.','_')
    ├── profile.json          ← lang_pref, conversation_summary, chatty config
    ├── chat_history.jsonl    ← append-only conversation log (user + assistant turns)
    └── vector_db/
        └── chroma.sqlite3    ← ChromaDB PersistentClient (per-chat collection)
```

**Privacy guarantee:** `SentenceTransformer.encode()` runs locally. No text is ever sent to a cloud embedding endpoint.

---

## ⚙️ Configuration Flags

| Variable | Type | Default | Description |
|---|---|---|---|
| `ENABLE_RAG_INGESTION` | bool | `True` | Master kill-switch. `False` suppresses all ChromaDB writes/reads. `.jsonl` writes are always preserved for session continuity. |
| `RAG_TOP_K` | int | `5` | Number of semantically similar past messages retrieved per query (`n_results` in ChromaDB). |
| `RAG_EMBEDDING_MODEL` | str | `all-MiniLM-L6-v2` | SentenceTransformer model. Loaded eagerly at startup to avoid blocking the event loop on first message. |
| `DYNAMIC_SYSTEM_PROMPT` | bool | `True` | Enables the rolling JSON summary (`conversation_summary` in `profile.json`). Triggers every 5 messages. |

---

## 🔄 Active Ingestion Flow (ASCII)

```
Incoming WhatsApp Message
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              app/router_webhook.py                  │
│                                                     │
│  1. Parse payload, extract text + sender metadata   │
│  2. Instantiate AIMemoryEngine(chat_id, ...)        │
│  3. asyncio.create_task(                            │  ← fire-and-forget
│         engine.ingest_message(                      │    (never awaited,
│             text,                                   │     never blocks
│             media_path,                             │     webhook response)
│             sender_id=sender_id,                   │
│             message_type="dm"|"group"              │
│         )                                           │
│     )                                               │
│  4. await engine.process_message(                   │  ← LLM reply path
│         ..., skip_user_ingestion=True               │
│     )                                               │
└─────────────────────────────────────────────────────┘
         │
         │  asyncio task (concurrent)
         ▼
┌─────────────────────────────────────────────────────┐
│         AIMemoryEngine.ingest_message()             │
│                                                     │
│  A. _process_media() — vision/PDF extraction        │
│  B. _append_history("user", full_text, metadata)    │
│     ├─ Writes to .jsonl  ← SYNCHRONOUS              │
│     │  (required for generate_delayed_reply)        │
│     └─ asyncio.create_task(_rag_ingest_async(...))  │
│                                                     │
└─────────────────────────────────────────────────────┘
         │
         │  asyncio task (thread pool)
         ▼
┌─────────────────────────────────────────────────────┐
│         AIMemoryEngine._rag_ingest_async()          │
│                                                     │
│  C. asyncio.to_thread(                             │
│         embedding_model.encode(content)             │  ← CPU-bound, off
│     )                                               │    event loop
│  D. asyncio.to_thread(                             │
│         collection.add(                             │
│             documents, embeddings, metadatas, ids   │
│         )                                           │
│     )                                               │
└─────────────────────────────────────────────────────┘
```

---

## 🔍 Retrieval Flow (Before LLM Generation)

```
await engine.process_message(text, ..., skip_user_ingestion=True)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              process_message() internals            │
│                                                     │
│  1. _detect_language(text)                          │
│  2. _process_media(media_path)                      │
│  3. Skip user .jsonl write (skip_user_ingestion)    │
│                                                     │
│  4. _retrieve_rag_context(full_text)                │
│     ← Consolidated retrieval method (ADR-035)       │
│     a. asyncio.to_thread(collection.count())        │
│     b. asyncio.to_thread(                          │
│            embedding_model.encode(full_text)        │
│        )                                            │
│     c. asyncio.to_thread(                          │
│            collection.query(                        │
│                query_embeddings=[embedding],         │
│                n_results=min(RAG_TOP_K, count),     │
│                where={"chat_id": self.chat_id}      │
│                ↑ Defense-in-depth isolation filter   │
│            )                                        │
│        )                                            │
│     → retrieved_context = top-K documents joined   │
│                                                     │
│  5. Build system prompt with [CONTEXT MEMORY]       │
│  6. Call LLM (ask_llm)                              │
│  7. _append_history("assistant", ai_reply)          │
│  8. _update_summary() every 5 messages              │
└─────────────────────────────────────────────────────┘
```

---

## 📝 System Prompt Structure

```ini
[Global Instructions]
{base_prompt from data/system_prompts/default.txt}

[User Profile]
Name: {profile.name}
Preferred Language: {detected_lang}
Custom Instructions: {profile.system_prompt}

[CONTEXT MEMORY]
The following relevant past conversations have been retrieved:
{retrieved_context | "No relevant past memories found."}

INSTRUCTION: Use this context to maintain continuity. If the user refers to
previous topics, use the information above to answer accurately.
If the context is irrelevant, ignore it.

[Recent Context Summary]
{profile.conversation_summary}

[Constraint]
Reply ONLY in {lang}. Be natural, human-like, and concise.
```

---

## ✅ Entry Points in router_webhook.py

All four message paths call `ingest_message()` via `asyncio.create_task()`:

| Path | Domain | Trigger | Ingestion call |
|---|---|---|---|
| DM handler | DM | Every DM message | `create_task(engine.ingest_message(..., message_type="dm"))` |
| Path A (Group) | Group | Explicit @mention or reply-to-bot | `create_task(engine.ingest_message(..., message_type="group"))` |
| Path B (Group) | Group | Frequency counter threshold | `create_task(engine.ingest_message(..., message_type="group"))` |
| Silent Observer (Group) | Group | No trigger (chatty below threshold) | `create_task(engine.ingest_message(..., message_type="group"))` |

`process_message()` is called with `skip_user_ingestion=True` on all paths where `ingest_message()` was already called. This prevents double-writing the user message to `.jsonl`.

---

## 🕐 Timing & Latency Impact

| Operation | Blocking? | Estimated time |
|---|---|---|
| `.jsonl` write (ingest path) | Sync (fast I/O) | < 1 ms |
| ChromaDB embed + add (ingest) | `asyncio.to_thread` (background) | 30–150 ms off event loop |
| Webhook response | Returns immediately | Not affected by ingestion |
| ChromaDB count + encode + query (retrieval) | `asyncio.to_thread` (inline before LLM) | 20–80 ms off event loop |
| Total added to LLM response time | Non-blocking | ~20–80 ms (retrieval only) |

**Path B race condition analysis:** `ingest_message()` schedules two tasks (`.jsonl` write is sync, ChromaDB is async). The `generate_delayed_reply()` background task fires after 5–10 seconds. By that time, the `.jsonl` write (sync, < 1ms) has long completed, and ChromaDB write has completed as well. No race condition.

---

## ⚠️ Failsafe Behaviours

| Scenario | Behaviour |
|---|---|
| `ENABLE_RAG_INGESTION=False` | ChromaDB skipped entirely. `.jsonl` still written. `generate_delayed_reply()` unaffected. |
| ChromaDB `collection.count() == 0` | Retrieval step is skipped. Prompt includes "No relevant past memories found." |
| `_rag_ingest_async()` exception | Error logged, ingestion silently drops. No user-visible impact. |
| `asyncio.create_task()` called with no running loop | `RuntimeError` caught silently in `_append_history()`. Occurs only in sync test contexts. |
| Embedding model fails to load | Falls back to `all-MiniLM-L3-v2`. Logged as warning. |

---

## 🗃️ Historical Backfill

To populate the vector store with messages that arrived before RAG was activated:

```bash
# Backfill last 500 messages per chat (default)
python -m scripts.backfill_rag

# Restrict to one chat, dry-run first
python -m scripts.backfill_rag --chat-id "120363XXXX@g.us" --dry-run
python -m scripts.backfill_rag --chat-id "120363XXXX@g.us" --limit 200

# Options
#   --limit N       Max messages per chat  (default: 500)
#   --chat-id ID    Restrict to one chat   (optional)
#   --dry-run       Preview without writing
```

Reads from SQLite `message_buffer`. Processes oldest-first. Yields after each row to keep the event loop responsive. Waits 1 second after each chat to let background ChromaDB tasks settle.

**Prerequisite:** `ENABLE_RAG_INGESTION=True` in `.env`.

---

## 🔒 Context Isolation Architecture (ADR-035)

RAG context isolation uses a **dual-layer** defense strategy:

### Layer 1: Filesystem Isolation (Primary)

Each `chat_id` maps to a completely separate ChromaDB `PersistentClient` on disk:

```
User DM:    ./data/contacts/user1_s_whatsapp_net/vector_db/chroma.sqlite3
Group A:    ./data/contacts/groupA_g_us/vector_db/chroma.sqlite3
Group B:    ./data/contacts/groupB_g_us/vector_db/chroma.sqlite3
```

These are **physically separate databases**. A query in one PersistentClient can never return results from another.

### Layer 2: Where Clause Filter (Defense-in-Depth)

The `_retrieve_rag_context()` method additionally filters by `chat_id` in the ChromaDB `where` clause:

```python
results = self.collection.query(
    query_embeddings=[query_embedding],
    n_results=min(settings.RAG_TOP_K, count),
    where={"chat_id": self.chat_id},  # Defense-in-depth
)
```

This is a no-op in the current architecture (all vectors in a collection already share the same `chat_id`) but guards against future changes that might consolidate collections.

### Isolation Guarantees

```
User Query (DM)                      User Query (Group A)
     │                                      │
     ▼                                      ▼
_retrieve_rag_context()             _retrieve_rag_context()
     │                                      │
     ▼                                      ▼
ChromaDB: user1_s_whatsapp_net/     ChromaDB: groupA_g_us/
  where: chat_id = DM_ID              where: chat_id = GROUP_A_ID
     │                                      │
     ▼                                      ▼
DM Messages ONLY ✓                  Group A Messages ONLY ✓
(No Group data)                     (No DM or Group B data)
```

| Scenario | Ingested In | Query In | Result |
|---|---|---|---|
| Same DM | DM | DM | ✅ Found |
| Same Group | Group A | Group A | ✅ Found |
| Group → DM | Group A | DM | ❌ Not found |
| Group → Group | Group A | Group B | ❌ Not found |
| DM → Group | DM | Group A | ❌ Not found |

---

## 🧪 Test Coverage

See `tests/test_rag_ingestion.py`:

| Test | Verifies |
|---|---|
| `test_ingest_message_writes_jsonl` | `.jsonl` written with correct role, content, type, sender_id, chat_id |
| `test_ingest_message_jsonl_written_when_rag_disabled` | `.jsonl` always written; ChromaDB.add not called when `ENABLE_RAG_INGESTION=False` |
| `test_ingest_message_schedules_chromadb_when_rag_enabled` | Background task scheduled when flag is True |
| `test_process_message_does_not_double_write_with_skip_flag` | No user entry in `.jsonl` when `skip_user_ingestion=True` |
| `test_process_message_writes_user_without_skip_flag` | User entry present when `skip_user_ingestion=False` |
| `test_context_isolation_separate_vector_paths` | DM and Group use distinct `vector_db_path` |
| `test_rag_top_k_used_in_retrieval` | `n_results=min(RAG_TOP_K, count)` respected |

See `tests/test_rag_isolation.py` (ADR-035):

| Test | Verifies |
|---|---|
| `test_scenario_a_group1_to_group2_no_leakage` | Group 1 data NOT visible in Group 2 |
| `test_scenario_b_group_to_dm_no_leakage` | Group data NOT visible in DM |
| `test_scenario_c_dm_to_same_dm_returns_results` | DM data IS visible in same DM |
| `test_scenario_d_group_to_same_group_returns_results` | Group data IS visible in same Group |
| `test_where_clause_includes_chat_id` | `where={"chat_id": ...}` passed to ChromaDB query |
| `test_filesystem_isolation_different_chat_types` | All chat types produce distinct DB paths |
