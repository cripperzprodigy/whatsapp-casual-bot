import logging

import os
import base64
import time
import json
import asyncio
import random
from typing import Dict
from pathlib import Path
from filelock import FileLock
from app.services.profile_service import read_profile, write_profile
from app.services.ai_memory_engine import AIMemoryEngine

import httpx
import sqlalchemy.exc
from fastapi import APIRouter, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.whatsapp_gateway import (
    WhatsAppWebhookPayload,
    send_text_message,
    fetch_group_metadata,
)
from app.state import get_db, add_message_to_buffer, get_chat_settings
from app.commands import handle_command
from app.translation import detect_language, translate_text
from app.config import settings
from app.contact_sync import (
    update_contact,
    export_group_contacts,
    process_active_sweep,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Issue 8: limiter instance — shared state injected from main.py
limiter = Limiter(key_func=get_remote_address)

import re

pending_chatty_tasks: Dict[str, asyncio.Task] = {}

def is_explicitly_tagged(text: str, bot_number: str | None, mentioned_jids: list[str] = None) -> bool:
    """Checks if the bot is explicitly tagged via @bot, its phone number, or native WhatsApp mentions."""
    if re.search(r'(?i)(?<!\w)@bot(?!\w)', text):
        return True
    if bot_number:
        # Match bot_number with optional @ prefix, ensuring it's not part of a larger number
        pattern = r'(?<!\d)@?' + re.escape(bot_number) + r'(?!\d)'
        if re.search(pattern, text):
            return True
        # Check native WhatsApp mentions
        if mentioned_jids:
            bot_prefix = f"{bot_number}@"
            if any(jid.startswith(bot_prefix) for jid in mentioned_jids):
                return True
    return False

def is_bot_mentioned(text: str, bot_number: str | None, is_group: bool, mentioned_jids: list[str] = None) -> bool:
    """
    Robust helper to determine if Chatty should be triggered implicitly or explicitly.
    DMs are always considered 'mentioned' (implicitly). Groups require an explicit tag.
    """
    if not is_group:
        return True
    return is_explicitly_tagged(text, bot_number, mentioned_jids)

async def _delayed_chatty_reply(chat_id: str, msg_id: str, participant: str, engine: AIMemoryEngine, delay: float, burst_count: int):
    try:
        if delay > 0:
            await asyncio.sleep(delay)
            
        # Check if this task was replaced by a newer message during the sleep
        if pending_chatty_tasks.get(chat_id) != asyncio.current_task():
            return

        ai_reply = await engine.generate_delayed_reply()
        if ai_reply:
            await send_text_message(
                chat_id,
                ai_reply,
                reply_to_msg_id=None,
                quoted_participant=None,
            )
            # Process bursts sequentially if > 1
            for _ in range(1, burst_count):
                burst_reply = await engine.generate_delayed_reply(is_burst=True)
                if burst_reply:
                    await send_text_message(
                        chat_id,
                        burst_reply,
                        reply_to_msg_id=None,
                        quoted_participant=None,
                    )
    except asyncio.CancelledError:
        # Task was cancelled (debounced) by a newer message
        pass
    except Exception as e:
        logger.error(f"Error in delayed chatty reply task: {e}")
    finally:
        # Clean up the task from pending dict if it's still this one
        if pending_chatty_tasks.get(chat_id) == asyncio.current_task():
            del pending_chatty_tasks[chat_id]

async def process_message(
    payload: WhatsAppWebhookPayload, db: Session
) -> None:
    try:
        data = payload.data
        msg_key = data.key

        chat_id = msg_key.remoteJid
        sender_id = msg_key.participant or msg_key.remoteJid
        sender_name = data.pushName or "Unknown"

        # System Domain Guard Rail
        # Ignore non-conversational domains to prevent the bot from attempting 
        # to chat with Status updates, Channels, or Linked Devices.
        if chat_id == "status@broadcast" or chat_id.endswith("@broadcast") or chat_id.endswith("@newsletter") or chat_id.endswith("@lid"):
            logger.debug(f"Ignoring non-conversational system domain: {chat_id}")
            return

        # Security: Check Whitelist
        if settings.ENFORCE_WHITELIST and settings.WHITELISTED_CHATS:
            allowed = [
                c.strip()
                for c in settings.WHITELISTED_CHATS.split(",")
                if c.strip()
            ]
            if allowed and chat_id not in allowed:
                logger.debug(f"Message from {chat_id} dropped: not in WHITELISTED_CHATS")
                return

        # Self-awareness & Contact Syncing
        chat_settings = get_chat_settings(db, chat_id)

        # Periodically/Passively check group info if not yet known.
        if chat_id.endswith("@g.us") and not chat_settings.group_name:
            group_info = await fetch_group_metadata(chat_id)
            if group_info:
                chat_settings.group_name = group_info.get(
                    "subject", "Unknown Group"
                )
                # Determine if bot is admin
                bot_number = settings.BOT_NUMBER
                participants = group_info.get("participants", [])
                if bot_number:
                    for p in participants:
                        pid = p.get("id", "")
                        if (
                            pid == bot_number
                            or pid == f"{bot_number}@s.whatsapp.net"
                        ):
                            chat_settings.bot_is_admin = p.get(
                            "admin"
                        ) in ["admin", "superadmin"]
                db.commit()

                # Active Sweep: bulk-inject participants into ledger
                process_active_sweep(db, chat_id, participants)

        # Update contact list passively on every message received
        if settings.AUTO_SYNC_CONTACTS and sender_id:
            update_contact(
                db, chat_id=chat_id, jid=sender_id, push_name=sender_name, is_admin=False
            )
            export_group_contacts(db, chat_id)

        # Don't process our own messages to avoid loops
        if msg_key.fromMe or (settings.BOT_NUMBER and sender_id and sender_id.startswith(settings.BOT_NUMBER)):
            return

        content_obj = data.message
        text = None
        mentioned_jids = []
        if content_obj.conversation:
            text = content_obj.conversation
        elif content_obj.extendedTextMessage and "text" in content_obj.extendedTextMessage:
            text = content_obj.extendedTextMessage["text"]

        # Extract mentions even if text was pulled from conversation
        if content_obj.extendedTextMessage and "contextInfo" in content_obj.extendedTextMessage:
            mentioned_jids = content_obj.extendedTextMessage["contextInfo"].get("mentionedJid", [])

        # Fallback to root contextInfo if it exists
        if not mentioned_jids and getattr(content_obj, "contextInfo", None):
            mentioned_jids = content_obj.contextInfo.get("mentionedJid", [])

        if not text:
            return

        # Log to buffer
        add_message_to_buffer(
            db, chat_id, sender_id, sender_name, text
        )


        # Media Handling
        media_path = None
        if data.media_data:
            try:
                media = data.media_data
                if media and isinstance(media, dict) and 'data' in media and 'filename' in media:
                    media_bytes = base64.b64decode(media['data'])
                    safe_id = chat_id.replace('@', '_').replace('.', '_')
                    contact_dir = Path(f"./data/contacts/{safe_id}/media")
                    contact_dir.mkdir(parents=True, exist_ok=True)

                    timestamp = int(time.time())
                    filename = f"{timestamp}_{media['filename']}"
                    file_path = contact_dir / filename

                    with open(file_path, "wb") as f:
                        f.write(media_bytes)

                    media_path = str(file_path)
            except Exception as e:
                logger.error(f"Failed to save media: {e}")

        # Ensure user profile and Chatty Status is initialized
        profile = read_profile(chat_id)
        default_status = settings.CHATTY_GROUP_DEFAULT if chat_id.endswith("@g.us") else settings.CHATTY_DEFAULT
        chatty_status = profile.get("chatty_status", default_status)

        # Handle Commands
        if text.startswith("!"):
            await handle_command(text, chat_id, sender_id, db)
            return

        # Mutual exclusion guard: if Chatty evaluates the message at all,
        # auto-translation must be skipped for this message event.
        message_consumed_by_chatty = False

        bot_id = settings.BOT_NUMBER
        is_explicit_mention = is_explicitly_tagged(text, bot_id, mentioned_jids)

        # Trigger Chatty RAG response if explicitly mentioned OR chatty is enabled
        if is_explicit_mention or chatty_status:
            message_consumed_by_chatty = True
            try:
                trigger = False
                burst_count = 1

                def update_counter(p):
                    nonlocal trigger
                    nonlocal burst_count
                    bot_id = settings.BOT_NUMBER
                    is_group = chat_id.endswith("@g.us")
                    
                    if is_bot_mentioned(text, bot_id, is_group, mentioned_jids):
                        trigger = True
                        p["message_counter"] = 0
                    elif chatty_status:
                        p["message_counter"] = p.get("message_counter", 0) + 1
                        if p["message_counter"] >= p.get("chatty_frequency", settings.CHATTY_DEFAULT_FREQUENCY):
                            trigger = True
                            p["message_counter"] = 0
                    burst_count = p.get("chatty_burst", settings.CHATTY_DEFAULT_BURST)

                from app.services.profile_service import update_profile_atomic
                updated_profile = update_profile_atomic(chat_id, update_counter)

                engine = AIMemoryEngine(chat_id, sender_name, profile=updated_profile)

                if trigger:
                    explicit_tag = is_explicit_mention

                    if explicit_tag:
                        # ── Path A: Explicit Mention ── Immediate inline reply ──
                        # Cancel any pending background tasks for this chat
                        if chat_id in pending_chatty_tasks:
                            pending_chatty_tasks[chat_id].cancel()
                            del pending_chatty_tasks[chat_id]

                        # Process message WITH reply generation in the same request cycle
                        ai_reply = await engine.process_message(text, media_path, generate_reply=True)
                        if ai_reply:
                            await send_text_message(
                                chat_id,
                                ai_reply,
                                reply_to_msg_id=None,
                                quoted_participant=None,
                            )
                        return
                    else:
                        # ── Path B: Frequency-Based ── Delayed background task ──
                        # Save to RAG context first without generating a reply
                        await engine.process_message(text, media_path, generate_reply=False)

                        d_min = updated_profile.get("chatty_delay_min", settings.CHATTY_DELAY_MIN)
                        d_max = updated_profile.get("chatty_delay_max", settings.CHATTY_DELAY_MAX)
                        delay = random.uniform(d_min, d_max)
                        d_mode = updated_profile.get("chatty_delay_mode", settings.CHATTY_DELAY_MODE)

                        # Handle existing tasks based on mode
                        if chat_id in pending_chatty_tasks:
                            if d_mode == "debounce":
                                pending_chatty_tasks[chat_id].cancel()
                            elif d_mode == "throttle":
                                # Do not reset timer, let the existing one finish
                                return

                        # Start new delayed task
                        task = asyncio.create_task(_delayed_chatty_reply(
                            chat_id, msg_key.id, msg_key.participant, engine, delay, burst_count
                        ))
                        pending_chatty_tasks[chat_id] = task
                        return
                else:
                    # No trigger — still save to RAG context for future retrieval
                    await engine.process_message(text, media_path, generate_reply=False)
            except Exception as e:
                logger.error(f"AI Memory Engine Error: {e}")

        # Auto-translation
        # Guard: If Chatty touched this message, translation must be skipped.
        # Chatty and Auto-Translation are mutually exclusive for each message event.
        if message_consumed_by_chatty:
            logger.debug(
                "Skipping auto-translation: message was consumed by Chatty processing."
            )
            return

        # Guard: Skip translation for messages explicitly directed at the bot.
        # These are conversational commands, not content requiring translation.
        # This also acts as defense-in-depth if the chatty try/except leaks.
        bot_id = settings.BOT_NUMBER
        if is_explicitly_tagged(text, bot_id, mentioned_jids):
            logger.debug(f"Skipping auto-translation: message is an explicit bot mention.")
            return

        # Uses the chat_settings already fetched at the top of the function
        is_auto_enabled = (
            chat_settings.auto_translate_enabled
            if chat_settings.auto_translate_enabled is not None
            else settings.GLOBAL_AUTO_TRANSLATE
        )
        target_lang = (
            chat_settings.default_target_language
            if chat_settings.default_target_language is not None
            else settings.GLOBAL_TARGET_LANGUAGE
        )

        if chat_settings.ignored_languages is not None:
            ignore_list = chat_settings.ignored_languages
        else:
            ignore_list = [
                lang.strip()
                for lang in settings.GLOBAL_IGNORED_LANGUAGES.split(",")
                if lang.strip()
            ]

        if is_auto_enabled and target_lang:
            translated = await translate_text(text, target_lang, ignore_list=ignore_list, chat_id=chat_id, msg_id=msg_key.id)
            if translated != text:
                await send_text_message(
                    chat_id,
                    translated,
                    reply_to_msg_id=msg_key.id,
                    quoted_participant=msg_key.participant,
                )
    except sqlalchemy.exc.SQLAlchemyError as exc:
        logger.error(
            "Database error while processing message: %s", exc
        )
    except Exception as exc:
        logger.error(
            "Unexpected error processing message: %s", exc,
            exc_info=True,
        )


@router.post("/webhook/whatsapp")
# Issue 8: rate-limit this endpoint; system/health endpoints are exempt
@limiter.limit(f"{settings.WEBHOOK_RATE_LIMIT}/minute")
async def whatsapp_webhook(
    request: Request,  # required by slowapi
    payload: WhatsAppWebhookPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    if payload.event == "messages.upsert":
        background_tasks.add_task(process_message, payload, db)
    return {"status": "ok"}
