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
    check_gateway_health,
)
from app.state import get_db, add_message_to_buffer, get_chat_settings, SessionLocal
from app.commands import handle_command
from app.translation import detect_language, translate_text
from app.config import settings, BotIdentityManager
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

# ── JID normalisation helpers ────────────────────────────────────

_JID_SUFFIXES = (
    '@s.whatsapp.net',
    '@c.us',
    '@lid',
    '@g.us',
    '@broadcast',
    '@newsletter',
)

def normalize_jid_for_comparison(jid: str) -> str:
    """
    Strips any WhatsApp JID suffix and leading '+' to return a bare
    numeric string suitable for equality comparison.

    Examples:
      '68728804868116@lid'          → '68728804868116'
      '68728804868116@s.whatsapp.net' → '68728804868116'
      '+6587802805'                 → '6587802805'
      '6587802805'                  → '6587802805'
    """
    if not jid:
        return ""
    jid = jid.strip()
    for suffix in _JID_SUFFIXES:
        if jid.endswith(suffix):
            jid = jid[: -len(suffix)]
            break
    return jid.lstrip('+')


def is_explicitly_tagged(
    text: str,
    bot_number: str | None,
    mentioned_jids: list[str] | None = None,
) -> bool:
    """
    Returns True if the bot was explicitly addressed in the message.

    Detection order (any match returns True immediately):
      1. Bot's bare number found in the mentionedJids array
         (normalized comparison — handles @lid, @c.us, @s.whatsapp.net).
      2. Bot's bare number appears literally in the message text.
      3. Message text contains the pattern '@bot' (case-insensitive).

    Args:
      text          : Raw message body string.
      bot_number    : Bot's number in any format (or None to disable check).
      mentioned_jids: List of JID strings from the WhatsApp message payload.

    Returns:
      bool
    """
    if not bot_number:
        return False

    bare_bot = normalize_jid_for_comparison(bot_number)
    if not bare_bot:
        return False

    # 1. Check native @mention via mentionedJids array
    if mentioned_jids:
        from app.config import BotIdentityManager
        known_ids = BotIdentityManager.load_known_bot_ids()
        for jid in mentioned_jids:
            if normalize_jid_for_comparison(jid) == bare_bot:
                import logging
                logging.getLogger(__name__).debug(f"Mention detected via JID match for bot {bot_number}")
                return True
            if jid in known_ids:
                import logging
                logging.getLogger(__name__).debug(f"Mention detected via known LID match: {jid}")
                return True

    # 2. Check if bot's bare number is literally present in text
    if bare_bot and re.search(re.escape(bare_bot), text or ""):
        import logging
        logging.getLogger(__name__).debug(f"Mention detected via literal number match for bot {bot_number}")
        return True

    # 3. Check for generic @bot pattern
    if re.search(r'(?i)@\s*bot\b', text or ""):
        import logging
        logging.getLogger(__name__).debug(f"Mention detected via generic @bot pattern")
        return True

    # Fallback: Check message text for @BotName or @BotNumber
    from app.config import BotIdentityManager
    bot_identity = BotIdentityManager.get_bot_identity()
    bot_name = bot_identity.get("name", "")
    
    patterns = []
    if bot_name:
        patterns.append(re.escape(bot_name))
    if bare_bot:
        patterns.append(re.escape(bare_bot))
        
    if patterns:
        # Match @ followed by BotName or BotNumber (case-insensitive)
        pattern = r'@(' + '|'.join(patterns) + r')\b'
        if re.search(pattern, text or "", re.IGNORECASE):
            import logging
            logging.getLogger(__name__).debug(f"Mention detected via name regex for bot {bot_name}/{bot_number}")
            return True

    return False

def is_bot_mentioned(
    text: str,
    bot_number: str | None,
    is_group: bool = True,
    mentioned_jids: list[str] | None = None
) -> bool:
    """In DMs every message is implicit. Groups require explicit tag."""
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
                quoted_msg_id=None,
                quoted_participant=None,
            )
            # Process bursts sequentially if > 1
            for _ in range(1, burst_count):
                burst_reply = await engine.generate_delayed_reply(is_burst=True)
                if burst_reply:
                    await send_text_message(
                        chat_id,
                        burst_reply,
                        quoted_msg_id=None,
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

def normalize_jid(jid: str) -> str:
    if not jid: return ""
    return jid.split('@')[0] if '@' in jid else jid

def extract_context(message_content, bot_number: str | None, bot_known_ids: list[str]) -> tuple[str | None, str | None]:
    """
    Extracts quoted message context if the user is replying to the bot.
    Returns (context_type, context_content) or (None, None).
    """
    context_info = None
    if getattr(message_content, "contextInfo", None):
        context_info = getattr(message_content, "contextInfo")
    elif getattr(message_content, "extendedTextMessage", None):
        ext_txt = getattr(message_content, "extendedTextMessage")
        if isinstance(ext_txt, dict):
            context_info = ext_txt.get("contextInfo")
        elif hasattr(ext_txt, "contextInfo"):
            context_info = getattr(ext_txt, "contextInfo")

    if not context_info or not isinstance(context_info, dict):
        return None, None
        
    quoted_sender = context_info.get("participant", "")
    quoted_msg = context_info.get("quotedMessage", {})
    
    if not quoted_msg or not isinstance(quoted_msg, dict):
        return None, None

    quoted_numeric = normalize_jid(quoted_sender)
    bot_numerics = [normalize_jid(j) for j in bot_known_ids]
    if bot_number:
        bot_numerics.append(normalize_jid(bot_number))

    logger.debug(f"Reply Check: {quoted_numeric} in {bot_numerics}")
    is_bot = quoted_numeric in bot_numerics

    if is_bot:
        quoted_text = quoted_msg.get("conversation", "")
        if not quoted_text and "extendedTextMessage" in quoted_msg:
            ext_text = quoted_msg["extendedTextMessage"]
            if isinstance(ext_text, dict):
                quoted_text = ext_text.get("text", "")
            else:
                quoted_text = getattr(ext_text, "text", "")
        
        if quoted_text:
            return "reply", quoted_text
            
    return None, None

async def _handle_dm_message(chat_id: str, sender_id: str, sender_name: str, text: str, media_path: str, msg_key, profile: dict, context_tuple: tuple = None):
    """
    Handles Direct Messages (DMs).
    Logic: Always invoke Chatty. Never invoke Auto-Translation.
    Bypass frequency throttles (every DM is a direct conversation).
    """
    logger.info(f"DM message received: sender={sender_id}, chat={chat_id}, text_len={len(text)}, has_media={media_path is not None}")
    try:
        # For DMs, always trigger Chatty
        logger.debug(f"DM: Initializing AIMemoryEngine for {chat_id}")
        engine = AIMemoryEngine(chat_id, sender_name, profile=profile)
        logger.debug(f"DM: AIMemoryEngine initialized successfully for {chat_id}")

        # Cancel any pending background tasks for this chat to avoid race conditions
        if chat_id in pending_chatty_tasks:
            pending_chatty_tasks[chat_id].cancel()
            del pending_chatty_tasks[chat_id]

        final_user_input = text
        if context_tuple and context_tuple[0] == "reply":
            final_user_input = f"User is replying to your previous message: '{context_tuple[1]}'. Their new message is: '{text}'"

        # Process message WITH reply generation in the same request cycle
        logger.debug(f"DM: Calling process_message with generate_reply=True for {chat_id}")
        ai_reply = await engine.process_message(final_user_input, media_path, generate_reply=True, context_type=None, context_text=None)
        logger.info(f"DM: LLM reply received={ai_reply is not None}, reply_len={len(ai_reply) if ai_reply else 0} for {chat_id}")
        if ai_reply:
            await send_text_message(
                chat_id,
                ai_reply,
                quoted_msg_id=getattr(msg_key, 'id', None),
                quoted_participant=None,
            )
        else:
            logger.warning(f"DM: LLM returned None for {chat_id}. Sending fallback.")
            await send_text_message(
                chat_id,
                "⚠️ I received your message but couldn't generate a response right now. Please try again.",
                quoted_msg_id=None,
                quoted_participant=None,
            )
    except Exception as e:
        logger.error(f"DM Handler Error for {chat_id}: {e}")
        await send_text_message(chat_id, "⚠️ Something went wrong. Please try again.")


async def _handle_group_message(chat_id: str, sender_id: str, sender_name: str, text: str, media_path: str, msg_key, profile: dict, chat_settings, mentioned_jids: list[str], context_tuple: tuple = None):
    """
    Handles Group Chat messages.
    Logic: Implement the 'Mutual Exclusion' pattern.
    - If @bot mentioned -> Trigger Chatty immediately.
    - Else -> Check Chatty frequency triggers.
    - If Chatty did NOT consume the message -> Run Auto-Translation.
    """
    bot_id = BotIdentityManager.get_bot_number()
    is_text_mention = is_explicitly_tagged(text, bot_id, mentioned_jids)
    has_reply_context = (context_tuple is not None) and (context_tuple[0] == "reply")
    is_explicit_mention = is_text_mention or has_reply_context
    logger.info(f"Group message received: chat={chat_id}, sender={sender_id}, TextMention={is_text_mention}, ReplyContext={has_reply_context}, bot_id={bot_id}")
    message_consumed_by_chatty = False

    chatty_status = profile.get("chatty_status", settings.CHATTY_GROUP_DEFAULT)

    try:
        trigger = False
        trigger_reason = None
        burst_count = 1

        def update_counter(p):
            nonlocal trigger
            nonlocal trigger_reason
            nonlocal burst_count

            if has_reply_context:
                trigger = True
                trigger_reason = "REPLY"
                p["message_counter"] = 0
            elif is_text_mention:
                trigger = True
                trigger_reason = "TAG"
                p["message_counter"] = 0
            elif chatty_status:
                p["message_counter"] = p.get("message_counter", 0) + 1
                if p["message_counter"] >= p.get("chatty_frequency", settings.CHATTY_DEFAULT_FREQUENCY):
                    trigger = True
                    trigger_reason = "RANDOM"
                    p["message_counter"] = 0
            burst_count = p.get("chatty_burst", settings.CHATTY_DEFAULT_BURST)

        from app.services.profile_service import update_profile_atomic
        updated_profile = update_profile_atomic(chat_id, update_counter)

        engine = AIMemoryEngine(chat_id, sender_name, profile=updated_profile)

        logger.info(f"Group: trigger={trigger}, reason={trigger_reason}, chatty_status={chatty_status} for {chat_id}")
        if trigger:
            message_consumed_by_chatty = True
            if trigger_reason in ["REPLY", "TAG"]:
                # ── Path A: Explicit Mention ── Immediate inline reply ──
                if chat_id in pending_chatty_tasks:
                    pending_chatty_tasks[chat_id].cancel()
                    del pending_chatty_tasks[chat_id]

                final_user_input = text
                
                if trigger_reason == "REPLY" and is_text_mention:
                    quoted_text = context_tuple[1]
                    final_user_input = f"User @{sender_name} explicitly tagged you and is replying to your previous message: '{quoted_text}'. Their new message is: '{text}'"
                elif trigger_reason == "REPLY":
                    quoted_text = context_tuple[1]
                    final_user_input = f"User is replying to your previous message: '{quoted_text}'. Their new message is: '{text}'"
                elif trigger_reason == "TAG":
                    final_user_input = f"User @{sender_name} tagged you in the group and said: '{text}'"

                logger.debug(f"Group: Context extracted - final_user_input={final_user_input}")

                ai_reply = await engine.process_message(final_user_input, media_path, generate_reply=True, context_type=None, context_text=None)
                if ai_reply:
                    await send_text_message(
                        chat_id,
                        ai_reply,
                        quoted_msg_id=getattr(msg_key, 'id', None),
                        quoted_participant=None,
                    )
                return
            else:
                # ── Path B: Frequency-Based ── Delayed background task ──
                await engine.process_message(text, media_path, generate_reply=False, context_type=None, context_text=None)

                d_min = updated_profile.get("chatty_delay_min", settings.CHATTY_DELAY_MIN)
                d_max = updated_profile.get("chatty_delay_max", settings.CHATTY_DELAY_MAX)
                delay = random.uniform(d_min, d_max)
                d_mode = updated_profile.get("chatty_delay_mode", settings.CHATTY_DELAY_MODE)

                if chat_id in pending_chatty_tasks:
                    if d_mode == "debounce":
                        pending_chatty_tasks[chat_id].cancel()
                    elif d_mode == "throttle":
                        return

                task = asyncio.create_task(_delayed_chatty_reply(
                    chat_id, msg_key.id, msg_key.participant, engine, delay, burst_count
                ))
                pending_chatty_tasks[chat_id] = task
                return
        else:
            # Still save to RAG context for future retrieval (Silent Observer)
            # Even if chatty is disabled entirely, we log it to memory context
            await engine.process_message(text, media_path, generate_reply=False, context_type=None, context_text=None)

            # If chatty was supposed to trigger but didn't, or was evaluated,
            # we should still mark it as consumed ONLY IF chatty_status is True.
            # But the requirement says: "If Chatty did NOT consume the message -> Run Auto-Translation"
            # Since trigger=False, Chatty didn't consume it for a reply.
            message_consumed_by_chatty = False
    except Exception as e:
        logger.error(f"Group Chatty Handler Error: {e}", exc_info=True)

    # ── Auto-Translation Logic ──
    if message_consumed_by_chatty:
        logger.info(f"Group: Skipping auto-translation: message was consumed by Chatty. chat={chat_id}")
        return

    if is_explicit_mention:
        logger.info(f"Group: Skipping auto-translation: explicit bot mention. chat={chat_id}")
        return

    logger.info(f"Group: Proceeding to auto-translation check. chat={chat_id}, SkipTranslation=False")

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
                quoted_msg_id=msg_key.id,
                quoted_participant=msg_key.participant,
            )


def normalize_chat_id(raw_id: str) -> str:
    """
    Normalizes a WhatsApp ID.
    If it's an @lid, we accept it as is (since we can't synchronously resolve it to @s.whatsapp.net here).
    """
    return raw_id

async def process_message(
    payload: WhatsAppWebhookPayload
) -> None:
    db: Session | None = None
    try:
        db = SessionLocal()
        data = payload.data
        msg_key = data.key

        # Check gateway health before processing heavy tasks
        health = await check_gateway_health()
        if not health.get("isConnected", False) or health.get("recoveryTier", 0) > 0:
            logger.warning(f"Gateway is in recovery/disconnected. Processing may be queued or fail. (Health: {health})")

        raw_chat_id = msg_key.remoteJid
        raw_sender_id = msg_key.participant or msg_key.remoteJid
        chat_id = normalize_chat_id(raw_chat_id)
        sender_id = normalize_chat_id(raw_sender_id)
        sender_name = data.pushName or "Unknown"

        # System Domain Guard Rail
        # Ignore non-conversational domains (broadcasts, newsletters)
        if chat_id == "status@broadcast" or chat_id.endswith("@broadcast") or chat_id.endswith("@newsletter"):
            logger.debug(f"Ignoring non-conversational system domain: {chat_id}")
            return

        # Handle DM LID logic
        is_group = chat_id.endswith("@g.us")
        if not is_group:
            if not (chat_id.endswith("@s.whatsapp.net") or chat_id.endswith("@lid")):
                logger.debug(f"Ignoring truly invalid sender: {chat_id}")
                return
            if chat_id.endswith("@lid"):
                logger.debug(f"Processing DM from (possibly LID): {chat_id}")

        # Security: Check Whitelist
        if settings.ENFORCE_WHITELIST and settings.WHITELISTED_CHATS:
            allowed = [
                c.strip()
                for c in settings.WHITELISTED_CHATS.split(",")
                if c.strip()
            ]
            if allowed and chat_id not in allowed:
                # Permissive in dev/debug mode
                if getattr(settings, "ENV", "production").lower() == "development" or settings.LOG_LEVEL == "DEBUG":
                    logger.warning(f"DEV MODE: Message from {chat_id} not in whitelist. Permitting anyway.")
                else:
                    logger.warning(f"Message from {chat_id} dropped: not in WHITELISTED_CHATS")
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
                bot_number = BotIdentityManager.get_bot_number()
                participants = group_info.get("participants", [])
                if bot_number:
                    bare_bot_number = normalize_jid_for_comparison(bot_number)
                    for p in participants:
                        pid = p.get("id", "")
                        if normalize_jid_for_comparison(pid) == bare_bot_number:
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
        bot_number = BotIdentityManager.get_bot_number()
        if msg_key.fromMe or (bot_number and sender_id and normalize_jid_for_comparison(sender_id) == normalize_jid_for_comparison(bot_number)):
            return

        content_obj = data.message
        text = None
        if content_obj.conversation:
            text = content_obj.conversation
        elif content_obj.extendedTextMessage and "text" in content_obj.extendedTextMessage:
            text = content_obj.extendedTextMessage["text"]

        mentioned_jids: list[str] = []
        ext_txt = getattr(data.message, 'extendedTextMessage', None)
        if isinstance(ext_txt, dict):
            ctx_info = ext_txt.get('contextInfo', {})
            mentioned_jids = ctx_info.get('mentionedJid', [])
        elif hasattr(ext_txt, 'contextInfo') and isinstance(ext_txt.contextInfo, dict):
            mentioned_jids = ext_txt.contextInfo.get('mentionedJid', [])

        bot_known_ids = BotIdentityManager.load_known_bot_ids()
        context_tuple = extract_context(content_obj, bot_number, bot_known_ids)

        if not text:
            return

        # Log to buffer
        add_message_to_buffer(
            db, chat_id, sender_id, sender_name, text
        )

        import tempfile
        import os
        media_path = None
        tmp_file = None
        if data.media_data:
            try:
                raw = base64.b64decode(data.media_data["data"])
                ext = data.media_data.get("mimetype","").split("/")[-1] or "bin"
                tmp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=f".{ext}", prefix="wa_media_"
                )
                tmp_file.write(raw)
                tmp_file.close()
                media_path = tmp_file.name
            except Exception as e:
                logger.error(f"Media decode failed: {e}")
                media_path = None

        try:
            # Ensure user profile is initialized
            profile = read_profile(chat_id)

            # Handle Commands (Pre-Split)
            if text.strip().startswith("!"):
                command_text = text.strip()
                if command_text.startswith("!whoami") or command_text.startswith("!forget-me"):
                    from app.permissions import is_owner
                    if not await is_owner(db, sender_id):
                        await send_text_message(chat_id, "🚫 Access Denied: This command requires Owner privileges.")
                        return

                    if command_text.startswith("!whoami"):
                        if mentioned_jids:
                            bot_lid = mentioned_jids[0]
                            BotIdentityManager.register_bot_id(bot_lid)
                            await send_text_message(chat_id, f"✅ Bot identity registered successfully as: {bot_lid}")
                        else:
                            await send_text_message(chat_id, "⚠️ Please tag the bot when using !whoami to register its LID.")
                        return
                    elif command_text.startswith("!forget-me"):
                        BotIdentityManager.clear_bot_ids()
                        await send_text_message(chat_id, "🗑️ Known Bot identities (LIDs) have been cleared.")
                        return
                
                await handle_command(text, chat_id, sender_id, db)
                return  # Exits immediately, preventing fall-through to Chatty engine

            # Domain Split
            is_dm = not chat_id.endswith("@g.us")
            logger.info(f"Domain Split: chat={chat_id}, is_dm={is_dm}, mentioned_jids={mentioned_jids}")
            if is_dm:
                return await _handle_dm_message(
                    chat_id=chat_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    text=text,
                    media_path=media_path,
                    msg_key=msg_key,
                    profile=profile,
                    context_tuple=context_tuple
                )
            else:
                return await _handle_group_message(
                    chat_id=chat_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    text=text,
                    media_path=media_path,
                    msg_key=msg_key,
                    profile=profile,
                    chat_settings=chat_settings,
                    mentioned_jids=mentioned_jids,
                    context_tuple=context_tuple
                )
        finally:
            if tmp_file and os.path.exists(tmp_file.name):
                os.unlink(tmp_file.name)
    except sqlalchemy.exc.SQLAlchemyError as exc:
        logger.error(
            "Database error while processing message: %s", exc
        )
    except Exception as exc:
        logger.error(
            "Unexpected error processing message: %s", exc,
            exc_info=True,
        )
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


@router.post("/webhook/whatsapp")
# Issue 8: rate-limit this endpoint; system/health endpoints are exempt
@limiter.limit(f"{settings.WEBHOOK_RATE_LIMIT}/minute")
async def whatsapp_webhook(
    request: Request,  # required by slowapi
    payload: WhatsAppWebhookPayload,
    background_tasks: BackgroundTasks,
) -> dict:
    if payload.event == "messages.upsert":
        # WARNING: BackgroundTasks.add_task() does NOT properly execute
        # async functions. It wraps them in a regular callable, so the
        # coroutine is never awaited and silently does nothing. We must
        # use asyncio.create_task() directly instead.
        asyncio.create_task(process_message(payload))
    return {"status": "ok"}
