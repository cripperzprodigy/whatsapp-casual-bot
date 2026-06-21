# Chatty Feature & Persistent RAG Memory

The **Chatty** feature elevates the passive, translation-focused WhatsApp bot into a highly contextual, multimodal, long-term conversational assistant. It leverages a Retrieval-Augmented Generation (RAG) architecture powered by ChromaDB and sentence-transformers.

## 🗂️ Directory & Path Isolation
Privacy and context separation are fundamental. All user data is stringently isolated inside `./data/contacts/{id}/`.

```text
./data/
├── config.json                 <-- Global dynamic config
├── system_prompts/
│   └── default.txt             <-- Base persona prompt
└── contacts/
    └── {user_id_or_group_id}/  <-- Strict Isolation Layer
        ├── profile.json        <-- Tracks lang_pref, summary, status
        ├── chat_history.jsonl  <-- Append-only log
        ├── media/              <-- Local media downloads
        │   └── 17000000_image.jpeg
        └── vector_db/          <-- Local ChromaDB persistence
            └── chroma.sqlite3
```

## ⚙️ Variables & Configurations

### Global Settings (`.env`)
- `CHATTY_DEFAULT` (bool): Default state for DMs (true).
- `CHATTY_GROUP_DEFAULT` (bool): Default state for Groups (false).
- `DYNAMIC_SYSTEM_PROMPT` (bool): Enable LLM rolling summaries (true).
- `RAG_EMBEDDING_MODEL` (str): Local model for vector DB (default: `all-MiniLM-L6-v2`).
- `VISION_ENABLED` (bool): Process media via vision LLMs.
- `CHATTY_DEFAULT_FREQUENCY` (int): Standard unprompted response trigger threshold (default: 10 messages).
- `CHATTY_DEFAULT_BURST` (int): Responses yielded per threshold activation (default: 1).
- `CHATTY_DELAY_MIN` (int): Minimum seconds to simulate typing/reading before a reply.
- `CHATTY_DELAY_MAX` (int): Maximum seconds to simulate typing/reading before a reply.
- `CHATTY_DELAY_MODE` (str): 'debounce' (resets timer if user keeps typing) or 'throttle' (strict wait).
- `DEFAULT_GROUP_LANGUAGE` (str): Backup resolution if detection fails (default: 'en').
- `DEFAULT_DM_LANGUAGE` (str): Backup resolution for DMs.

### Local Contact Profile (`profile.json`)
- `chatty_status`: Overrides the `.env` default on a per-chat basis.
- `lang_pref`: The `langdetect` ISO string to force the LLM to output that language.
- `preferred_language`: Hardcoded ISO string explicit to a DM user (skips autodetection).
- `conversation_summary`: A condensed JSON state of the chat updated every 5 messages.
- `message_counter`, `chatty_frequency`, `chatty_burst`: Real-time analytics determining unprompted activation.

---

## 🛠️ Commands
Users and Admins interact with the Chatty memory engine using the `!chatty` command.

| Command | Permission | Description |
|---|---|---|
| `!chatty on\|off` | Public (DM), Admin/Owner (Group) | Enables Chatty mode for the current chat window. |
| `!chatty_freq <val>` | Admin/Owner (Group) | Sets the frequency trigger interval (10-1000). |
| `!chatty_burst <val>` | Admin/Owner (Group) | Modifies the burst response count per trigger (1-5). |
| `!chatty_delay <min> <max>` | Admin/Owner (Group) | Configures the simulated human delay. |
| `!chatty_mode <debounce\|throttle>` | Admin/Owner (Group) | Sets the timer strategy for rapid messages. |
| `!chatty_status` | Public (DM), Admin/Owner (Group) | Lists current frequency, delay, and counter stats. |
| `!lang set <code>` | Public (DM) | Sets a strict language preference. |
| `!lang reset` | Public (DM) | Reverts DM into automatic `langdetect` logic. |

---

## ⏱️ Human Simulation & Trigger Logic

The bot mimics human interaction by utilizing a combination of frequency counters, implicit DM tagging, and delayed background tasks.

### Mention & Trigger Flow

```text
          [ Incoming Message ]
                   │
         Is this a Direct Message?
          /                  \
      [YES]                  [NO (Group)]
        │                      │
  (Implicit Mention)    Is @bot or @1234 explicitly tagged?
        │                /                 \
        │             [YES]                [NO]
        │               │                   │
        ▼               ▼                   ▼
    [ TRIGGER ]    [ TRIGGER ]       Increment Message Counter
                                            │
                                      Counter >= Frequency?
                                      /              \
                                   [YES]            [NO]
                                     │               │
                                 [ TRIGGER ]      [ IGNORE ]
```

### Task Delay Strategy (Debounce vs Throttle)

When `TRIGGER` is reached, the bot checks `CHATTY_DELAY_MODE` before responding.

```text
Mode: DEBOUNCE (Default)
Objective: Wait until the user finishes typing multiple rapid messages.
[Msg 1] ---> (Start 5s Timer)
[Msg 2] ---> (Cancel previous, Start NEW 5s Timer)
             ... 5s elapses ...
             => [ SEND REPLY ]

Mode: THROTTLE
Objective: Strict wait from the first message, collecting subsequent context.
[Msg 1] ---> (Start 5s Timer)
[Msg 2] ---> (Append to context, let timer run)
             ... 5s elapses ...
             => [ SEND REPLY ]

Mode: EXPLICIT MENTION BYPASS
Objective: Instant response to direct queries.
[Msg w/ @bot] ---> (Cancel existing timers, SEND REPLY IMMEDIATELY)
```

### 🚫 Natural Quoting
To maintain conversational realism, the `send_text_message` function is invoked with `reply_to_msg_id=None` during Chatty mode. The bot will interject naturally into the chat stream without using the WhatsApp 'reply' quote feature, identically to a human participant.

---

## 🔁 RAG Context Pipeline (Flow Diagram)

```text
         [ WhatsApp User ]
                │
                ▼ (Incoming Message via Node.js Gateway)
┌─────────────────────────────────────────┐
│        app/router_webhook.py            │
│ 1. Receives Base64 media & text payload │
│ 2. Downloads Media to ./data/media/     │
│ 3. Instantiates AIMemoryEngine          │
└───────────────┬─────────────────────────┘
                │
                ▼ (Engine Processing)
┌─────────────────────────────────────────┐
│     app/services/ai_memory_engine.py    │
│                                         │
│  A. Language Detection (langdetect)     │
│     => Logs 'es', 'en', 'id', etc.      │
│                                         │
│  B. Media Analysis (pdfplumber/Vision)  │
│     => Converts files to text context   │
│                                         │
│  C. Vector Embedding (ChromaDB)         │
│     => sentence-transformers encodes    │
│     => text into local SQLite DB        │
│                                         │
│  D. RAG Retrieval                       │
│     => Queries top 5 similar messages   │
│                                         │
│  E. Prompt Construction                 │
│     => Joins Profile + Memory + RAG     │
└───────────────┬─────────────────────────┘
                │
                ▼ (Unified Generation)
┌─────────────────────────────────────────┐
│           app/ai_client.py              │
│  Sends constructed system prompt and    │
│  user input to LLM Endpoint             │
└───────────────┬─────────────────────────┘
                │
                ▼ (Rolling Context Task)
┌─────────────────────────────────────────┐
│      AIMemoryEngine (Background)        │
│ Every 5 messages, triggers a JSON       │
│ summary generation to update the        │
│ profile.json `conversation_summary`     │
└─────────────────────────────────────────┘
```

## 🏗️ Architecture Design Choices

1. **Local Embeddings (Privacy):** Vector embeddings are generated locally using `sentence-transformers` rather than the main Chat LLM endpoints. This ensures absolute privacy (no data leak during indexing) and eliminates embedding latency issues if a slow local LLM is used.
2. **Node.js Media Pass-through:** To prevent double-fetching media chunks, the `whatsapp-web.js` microservice captures the binary blob, converts it to Base64, and pushes it up to the Python FastAPI via webhook. FastAPI handles the local file saving synchronously.
3. **Rolling Summary vs Generic Context:** Instead of feeding raw Chat History back to the LLM (which exceeds max context and gets expensive), the system leverages a combination of **Top-K RAG Matching** and a **Rolling JSON State Summary**. This allows the bot to remember specific instructions from weeks ago without hallucinating current conversation flow.
