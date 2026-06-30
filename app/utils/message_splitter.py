"""
Message Chunking & Sequential Sending Utility.

WhatsApp allows messages up to ~65,000 chars, but the gateway HTTP
request risks ReadTimeout when processing very large payloads.  This
module provides smart splitting at natural boundaries (paragraphs,
sentences, words) and sequential delivery with inter-chunk delay.

Usage:
    from app.utils.message_splitter import send_long_message
    await send_long_message(chat_id, very_long_text)
"""

import re
import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
MAX_CHUNK_SIZE = 2500          # Safe margin below gateway timeout risk
INTER_CHUNK_DELAY = 1.0        # Seconds between sequential sends
PART_HEADER_TEMPLATE = "📄 *Part {current}/{total}*\n\n"


# ── Splitting Algorithm ─────────────────────────────────────────────

def split_text_into_chunks(text: str, max_length: int = MAX_CHUNK_SIZE) -> List[str]:
    """Split text into chunks of at most *max_length* characters.

    Splitting priority (preserving readability):
      1. Paragraph boundaries  (``\\n\\n``)
      2. Sentence boundaries   (``(?<=[.!?])\\s+``)
      3. Word boundaries       (whitespace)
      4. Hard cut              (absolute last resort)

    Returns a list of strings, each ≤ *max_length*.
    """
    if not text or len(text) <= max_length:
        return [text] if text else []

    # Step 1: Split by paragraphs
    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    current_chunk = ""

    for para in paragraphs:
        # Would appending this paragraph exceed the limit?
        candidate = (current_chunk + "\n\n" + para) if current_chunk else para

        if len(candidate) <= max_length:
            current_chunk = candidate
            continue

        # Flush whatever we have so far
        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""

        # If the single paragraph itself fits, start a new chunk with it
        if len(para) <= max_length:
            current_chunk = para
            continue

        # Step 2: Paragraph too long — split by sentences
        sentence_chunks = _split_by_sentences(para, max_length)
        # All but the last become full chunks; last becomes current_chunk
        for sc in sentence_chunks[:-1]:
            chunks.append(sc)
        current_chunk = sentence_chunks[-1] if sentence_chunks else ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _split_by_sentences(text: str, max_length: int) -> List[str]:
    """Split text at sentence boundaries (. ! ?)."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    current = ""

    for sent in sentences:
        candidate = (current + " " + sent) if current else sent

        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)

        # If a single sentence exceeds max_length, split by words
        if len(sent) > max_length:
            word_chunks = _split_by_words(sent, max_length)
            for wc in word_chunks[:-1]:
                chunks.append(wc)
            current = word_chunks[-1] if word_chunks else ""
        else:
            current = sent

    if current:
        chunks.append(current)

    return chunks


def _split_by_words(text: str, max_length: int) -> List[str]:
    """Split text at word boundaries (whitespace).  Falls back to hard cut."""
    words = text.split()
    chunks: List[str] = []
    current = ""

    for word in words:
        candidate = (current + " " + word) if current else word

        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)

        # If a single word exceeds max_length (e.g. a URL), hard-cut it
        if len(word) > max_length:
            while word:
                chunks.append(word[:max_length])
                word = word[max_length:]
            current = ""
        else:
            current = word

    if current:
        chunks.append(current)

    return chunks


# ── Sequential Sender ────────────────────────────────────────────────

async def send_long_message(
    chat_id: str,
    text: str,
    quoted_msg_id: Optional[str] = None,
    quoted_participant: Optional[str] = None,
    max_chunk_size: int = MAX_CHUNK_SIZE,
):
    """Send a message, automatically chunking if it exceeds *max_chunk_size*.

    - Short messages (≤ max_chunk_size): sent as a single message.
    - Long messages: split at natural boundaries, sent sequentially with
      part headers and a 1-second inter-chunk delay.
    - Only the FIRST chunk carries the quote (``quoted_msg_id``) so the
      reply UI thread is preserved without cluttering every part.

    Returns the GatewaySendResult of the LAST chunk sent (for consistency).
    """
    # Import here to avoid circular import (gateway imports config, etc.)
    from app.whatsapp_gateway import send_text_message

    chunks = split_text_into_chunks(text, max_chunk_size)

    if not chunks:
        logger.warning(f"send_long_message called with empty text for {chat_id}")
        return await send_text_message(chat_id, "⚠️ (empty response)")

    total = len(chunks)

    if total == 1:
        # Short message — send directly, no header needed
        logger.debug(f"send_long_message: single chunk ({len(chunks[0])} chars) to {chat_id}")
        return await send_text_message(
            chat_id, chunks[0],
            quoted_msg_id=quoted_msg_id,
            quoted_participant=quoted_participant,
        )

    logger.info(f"send_long_message: splitting into {total} chunks for {chat_id} (original={len(text)} chars)")

    last_result = None
    for i, chunk in enumerate(chunks):
        header = PART_HEADER_TEMPLATE.format(current=i + 1, total=total)
        msg_text = header + chunk

        # Only quote the first chunk so the WhatsApp reply thread is clear
        result = await send_text_message(
            chat_id,
            msg_text,
            quoted_msg_id=quoted_msg_id if i == 0 else None,
            quoted_participant=quoted_participant if i == 0 else None,
        )
        last_result = result

        if not result.success:
            logger.error(
                f"send_long_message: chunk {i+1}/{total} failed for {chat_id} "
                f"(status={result.status_code}, error={result.error_code}). Aborting remaining."
            )
            # Send abort notice if we have more chunks
            if i < total - 1:
                try:
                    await send_text_message(
                        chat_id,
                        f"⚠️ Message delivery interrupted at part {i+1}/{total}. Please retry.",
                    )
                except Exception:
                    pass
            return result

        # Delay between chunks (not after the last one)
        if i < total - 1:
            await asyncio.sleep(INTER_CHUNK_DELAY)

    logger.info(f"send_long_message: all {total} chunks sent successfully to {chat_id}")
    return last_result
