import logging
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


async def process_message(
    payload: WhatsAppWebhookPayload, db: Session
) -> None:
    try:
        data = payload.data
        msg_key = data.key

        chat_id = msg_key.remoteJid
        sender_id = msg_key.participant or msg_key.remoteJid
        sender_name = data.pushName or "Unknown"

        # Security: Check Whitelist
        if settings.WHITELISTED_CHATS:
            allowed = [
                c.strip()
                for c in settings.WHITELISTED_CHATS.split(",")
                if c.strip()
            ]
            if allowed and chat_id not in allowed:
                # Ignore messages from un-whitelisted chats
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
                db, chat_id, sender_id, sender_name, is_admin=False
            )
            export_group_contacts(db, chat_id)

        # Don't process our own messages to avoid loops
        if msg_key.fromMe or sender_id == settings.BOT_NUMBER:
            return

        content_obj = data.message
        text = None
        if content_obj.conversation:
            text = content_obj.conversation
        elif (
            content_obj.extendedTextMessage
            and "text" in content_obj.extendedTextMessage
        ):
            text = content_obj.extendedTextMessage["text"]

        if not text:
            return

        # Log to buffer
        add_message_to_buffer(
            db, chat_id, sender_id, sender_name, text
        )

        # Handle Commands
        if text.startswith("!"):
            await handle_command(text, chat_id, sender_id, db)
            return

        # Auto-translation
        chat_settings = get_chat_settings(db, chat_id)

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
            lang = await detect_language(text)
            if (
                lang != "unknown"
                and lang not in ignore_list
                and lang != target_lang
            ):
                translated = await translate_text(text, target_lang)
                original_snippet = (
                    text
                    if len(text) <= 120
                    else text[:117] + "..."
                )
                reply_text = (
                    f"[{lang.upper()}] {translated}\n\n"
                    f"Translated from: {original_snippet}"
                )
                await send_text_message(
                    chat_id,
                    reply_text,
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
