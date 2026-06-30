"""
Backfill the ChromaDB RAG vector store from SQLite message history.

Reads the last N messages per chat from `message_buffer` and passes each
through `AIMemoryEngine.ingest_message()`.  Requires the full bot
environment with all Python dependencies installed.

Usage:
    python -m scripts.backfill_rag [--limit N] [--chat-id CHAT_ID] [--dry-run]

Options:
    --limit N       Maximum messages per chat to ingest  (default: 500)
    --chat-id ID    Restrict backfill to one specific chat ID  (optional)
    --dry-run       Show counts without writing to ChromaDB

Exit codes:
    0  Success
    1  ENABLE_RAG_INGESTION is False — set it True in .env and retry
"""

import argparse
import asyncio
import logging
import os
import sys

# Add project root to path so `app.*` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.state import MessageBuffer, SessionLocal
from app.services.ai_memory_engine import AIMemoryEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("backfill_rag")


async def _backfill_chat(
    chat_id: str,
    messages: list,
    dry_run: bool,
) -> int:
    """Ingest a list of MessageBuffer rows for a single chat. Returns count ingested."""
    if not messages:
        return 0
    if dry_run:
        logger.info(f"[DRY RUN] Would ingest {len(messages)} messages for {chat_id}")
        return len(messages)

    message_type = "group" if chat_id.endswith("@g.us") else "dm"
    engine = AIMemoryEngine(chat_id, sender_name="Backfill", profile={})

    ingested = 0
    for i, msg in enumerate(messages):
        try:
            await engine.ingest_message(
                text=msg.content or "",
                media_path=None,
                sender_id=msg.sender_id or "unknown",
                message_type=message_type,
            )
            ingested += 1
            if (i + 1) % 50 == 0:
                logger.info(f"  [{chat_id}] Progress: {i + 1}/{len(messages)}")
            # Yield control so the event loop can process background ChromaDB tasks
            await asyncio.sleep(0)
        except Exception as exc:
            logger.error(f"  [{chat_id}] Failed to ingest message id={msg.id}: {exc}")

    # Allow background _rag_ingest_async tasks to settle before moving on
    await asyncio.sleep(1)
    return ingested


async def main(limit: int, chat_id_filter: str | None, dry_run: bool) -> None:
    if not settings.ENABLE_RAG_INGESTION:
        logger.error(
            "ENABLE_RAG_INGESTION=False in .env — set it to True and retry."
        )
        sys.exit(1)

    logger.info(
        f"Starting RAG backfill  limit={limit}  "
        f"chat_filter={chat_id_filter or 'all'}  dry_run={dry_run}"
    )

    db = SessionLocal()
    try:
        query = db.query(MessageBuffer.chat_id).distinct()
        if chat_id_filter:
            query = query.filter(MessageBuffer.chat_id == chat_id_filter)
        chat_ids = [row[0] for row in query.all() if row[0]]

        if not chat_ids:
            logger.warning("No chats found in message_buffer. Nothing to backfill.")
            return

        logger.info(f"Found {len(chat_ids)} chat(s) to backfill.")
        total_ingested = 0

        for cid in chat_ids:
            # Fetch oldest-first so history is ingested in chronological order
            msgs = (
                db.query(MessageBuffer)
                .filter(MessageBuffer.chat_id == cid)
                .order_by(MessageBuffer.timestamp.asc())
                .limit(limit)
                .all()
            )
            logger.info(f"Backfilling {len(msgs)} messages for chat: {cid}")
            count = await _backfill_chat(cid, msgs, dry_run=dry_run)
            total_ingested += count
            logger.info(f"  Done: {count} message(s) ingested for {cid}")

        logger.info(
            f"Backfill complete. "
            f"Total ingested: {total_ingested} across {len(chat_ids)} chat(s)."
        )
    finally:
        db.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill ChromaDB RAG vector store from SQLite message history."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max messages per chat to ingest (default: 500)",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        dest="chat_id",
        help="Restrict backfill to a single chat ID (optional)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be ingested without writing to ChromaDB",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(limit=args.limit, chat_id_filter=args.chat_id, dry_run=args.dry_run))
