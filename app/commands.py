import csv
import logging
import os
from sqlalchemy.orm import Session
from app.state import (
    BotAdmin,
    ChatSettings,
    GroupContactLedger,
    MessageBuffer,
    Note,
    Task,
    get_chat_settings,
    get_global_setting,
    set_global_setting,
)
from app.services.profile_service import read_profile, write_profile
from app.translation import translate_text, detect_language
from app.pm_service import start_batched_pm_task
from app.whatsapp_gateway import send_text_message
from app.utils.message_splitter import send_long_message
from app.ai_client import ask_llm
from app.config import settings as app_settings, persist_global_config
from app.permissions import (
    ADMIN_ROLE,
    OWNER_ROLE,
    PUBLIC_ROLE,
    get_user_role,
    grant_role,
    is_admin,
    is_owner,
    list_active_roles,
    revoke_role,
    try_claim_ownership,
    is_claim_ownership_available,
)
from app.services.search_service import HybridSearchService
from app.services.agentic_search_service import AgenticSearchOrchestrator
from app.services.deep_crawl_service import DeepCrawlService
from app.services.feature_flag_service import FeatureFlagService
import asyncio

logger = logging.getLogger(__name__)


async def _build_help_text(db: Session, role: str, is_group_chat: bool) -> str:
    # Role is one of "owner", "admin", "public"
    display_role = "User" if role == PUBLIC_ROLE else role.capitalize()
    
    response = "🤖 *WhatsApp Casual Bot Commands*\n\n"
    
    # ---------------------------------------------------------
    # 1. COMMON COMMANDS (Available to everyone)
    # ---------------------------------------------------------
    response += "*📢 Available to You:*\n"
    response += "• `!a <text>`: Ask the AI a question\n"
    response += "• `!search <query>`: Quick search the web\n"
    response += "• `!s <query>`: Search the web with AI refinement\n"
    response += "• `!sc <query>`: 🕷️ Deep Crawl Search: Fetches full content from top websites (if enabled)\n"
    response += "• `!summary`: Summarize replied text or chat history\n"
    response += "• `!ping`: Check bot status\n"
    response += "• `!help`: Show this menu\n"
    
    # Translation & Productivity
    response += "• `!t <lang> <text>`: Translate text\n"
    response += "• `!t auto <text>`: Translate to default\n"
    if not is_group_chat:
        response += "• `!lang set <code>`: (DM Only) Set preferred language\n"
        response += "• `!lang reset`: (DM Only) Revert preferred language\n"
    response += "• `!task add <desc>`: Add a task\n"
    response += "• `!task list`: List tasks\n"
    response += "• `!task done <id>`: Complete a task\n"
    response += "• `!note add <text>`: Add a note\n"
    response += "• `!note list`: List notes\n"
    
    # Setup for new bots (only shown if claim is available)
    if role == PUBLIC_ROLE and not is_group_chat:
        if is_claim_ownership_available(db):
            response += "• `!claim_ownership`: Claim initial bot ownership\n"
            
    # ---------------------------------------------------------
    # 2. ADMIN COMMANDS (Available to admin and owner)
    # ---------------------------------------------------------
    if role in [ADMIN_ROLE, OWNER_ROLE]:
        response += "\n*🛡️ Admin Commands:*\n"
        response += "• `!chatty <on|off>`: Toggle continuous AI conversation\n"
        response += "• `!chatty_freq <val>`: Set AI response frequency\n"
        response += "• `!chatty_burst <val>`: Set AI burst count\n"
        response += "• `!chatty_delay <min> <max>`: Set human-like delay\n"
        response += "• `!chatty_mode <debounce|throttle>`: Set delay strategy\n"
        response += "• `!chatty_status`: View current AI chatter settings\n"
        response += "• `!auto on|off`: Toggle auto-translate for this chat\n"
        response += "• `!auto global`: Reset auto-translate for this chat\n"
        response += "• `!target <lang>`: Set target language\n"
        response += "• `!ignore add|remove <lang>`: Manage translation ignore list\n"
        response += "• `!ignore global`: Reset translation ignore list\n"
        response += "• `!contacts list`: View group contacts\n"
        response += "• `!pm group <text>`: DM current group\n"
        response += "• `!pm @user <text>`: DM specific user\n"
        response += "• `!broadcast <msg>`: Message all chats\n"
        response += "• `!stats`: System statistics\n"
        response += "• `!botid`: Show bot identity status\n"

    # ---------------------------------------------------------
    # 3. OWNER COMMANDS (Available to owner only)
    # ---------------------------------------------------------
    if role == OWNER_ROLE:
        response += "\n*👑 Owner Commands:*\n"
        response += "• `!sc_toggle <on|off>`: 🔒 Toggle Deep Crawl feature globally\n"
        response += "• `!config toggle <feature> <state>`: ⚙️ Advanced configuration toggles\n"
        response += "• `!contacts global`: View all contacts globally\n"
        response += "• `!contacts export`: Export global contact ledger\n"
        response += "• `!resolve @mention`: Force resolve a user's phone number\n"
        response += "• `!resolve group`: Actively resolve all numbers in the current group\n"
        response += "• `!resolve global`: Actively resolve all numbers across all groups\n"
        response += "• `!pm global <text>`: DM all groups\n"
        response += "• `!pm flood limit|interval <val>`: PM flood settings\n"
        response += "• `!owner grant|revoke <jid>`: Manage Owners\n"
        response += "• `!admin grant|revoke <jid>`: Manage Admins\n"
        response += "• `!owner|admin list`: List privileged users\n"
        response += "• `!owner transfer <jid>`: Transfer ownership\n"
        response += "• `!whoami`: 🆔 Registers the bot's current WhatsApp LID\n"
        response += "• `!forget-me`: Clears the bot's known LIDs\n"
        response += "• `!globaltrans on|off`: Toggle global auto-translate\n"
        response += "• `!shutdown | !restart`: Lifecycle controls\n"

    # ---------------------------------------------------------
    # Footer
    # ---------------------------------------------------------
    response += f"\n_You are viewing help as [{display_role}]. Contact @owner for access._"
    
    return response


async def handle_command(  # Issue 13: added return type
    text: str, chat_id: str, sender_id: str, db: Session
) -> None:
    parts = text.strip().split()
    if not parts:
        return

    command = parts[0].lower()
    args = parts[1:]
    chat_settings = get_chat_settings(db, chat_id)
    user_role = await get_user_role(db, sender_id)
    is_group_chat = chat_id.endswith("@g.us")

    try:
        if command == "!help":
            help_text = await _build_help_text(db, user_role, is_group_chat)
            await send_text_message(chat_id, help_text)

        elif command == "!auto":
            if len(args) == 1:
                if args[0] in ["on", "off"]:
                    if not await is_admin(db, sender_id):
                        await send_text_message(
                            chat_id,
                            "🚫 Access Denied: This command requires Admin or Owner privileges.",
                        )
                    else:
                        chat_settings.auto_translate_enabled = (args[0] == "on")
                        db.commit()
                        state = (
                            "ON"
                            if chat_settings.auto_translate_enabled
                            else "OFF"
                        )
                        await send_text_message(
                            chat_id,
                            f"Auto-translate for this chat is now "
                            f"explicitly {state}.",
                        )
                elif args[0] == "global":
                    if not await is_admin(db, sender_id):
                        await send_text_message(
                            chat_id,
                            "🚫 Access Denied: This command requires Admin or Owner privileges.",
                        )
                    else:
                        chat_settings.auto_translate_enabled = None
                        db.commit()
                        await send_text_message(
                            chat_id,
                            "Auto-translate for this chat reset to "
                            "GLOBAL configuration.",
                        )

        elif command == "!globaltrans":
            if not await is_owner(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: `!globaltrans` requires Owner privileges.",
                )
            elif len(args) == 1 and args[0] in ["on", "off"]:
                new_state = args[0] == "on"
                app_settings.GLOBAL_AUTO_TRANSLATE = new_state
                persist_global_config("GLOBAL_AUTO_TRANSLATE", new_state)
                state_label = "ON ✅" if new_state else "OFF ❌"
                await send_text_message(
                    chat_id,
                    f"🌐 Global auto-translation is now *{state_label}*.\n\n"
                    f"{'Groups with auto-translate enabled will now process translations.' if new_state else 'All auto-translation is disabled globally. Group settings are overridden.'}",
                )
            else:
                current = "ON ✅" if app_settings.GLOBAL_AUTO_TRANSLATE else "OFF ❌"
                await send_text_message(
                    chat_id,
                    f"🌐 Global auto-translation is currently: *{current}*\n"
                    f"Usage: `!globaltrans on` or `!globaltrans off`",
                )

        elif command == "!sc_toggle":
            if not await is_owner(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: `!sc_toggle` requires Owner privileges. Type !help to see available commands.",
                )
            elif len(args) == 1 and args[0] in ["on", "off"]:
                new_state = args[0] == "on"
                app_settings.deep_crawl_enabled = new_state
                persist_global_config("deep_crawl_enabled", new_state)
                if new_state:
                    await send_text_message(
                        chat_id,
                        "✅ Deep Crawl Search is now *enabled* globally.\n"
                        "Users can use `!sc <query>` to crawl full web pages for research.",
                    )
                else:
                    await send_text_message(
                        chat_id,
                        "⛔ Deep Crawl Search is now *disabled* globally.\n"
                        "The `!sc` command will return a disabled notice.",
                    )
            else:
                current = "ON ✅" if app_settings.deep_crawl_enabled else "OFF ❌"
                await send_text_message(
                    chat_id,
                    f"🕷️ Deep Crawl Search is currently: *{current}*\n"
                    f"Usage: `!sc_toggle on` or `!sc_toggle off`",
                )

        elif command == "!target":
            if not await is_admin(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Admin or Owner privileges.",
                )
            elif len(args) == 1:
                if args[0] == "global":
                    chat_settings.default_target_language = None
                    db.commit()
                    await send_text_message(
                        chat_id,
                        "Target language for this chat reset to "
                        "GLOBAL configuration.",
                    )
                else:
                    chat_settings.default_target_language = args[0]
                    db.commit()
                    await send_text_message(
                        chat_id,
                        f"Default target language set to: {args[0]}",
                    )

        elif command == "!ignore":
            if len(args) >= 1:
                subcmd = args[0]

                if subcmd == "global":
                    if not await is_admin(db, sender_id):
                        await send_text_message(
                            chat_id,
                            "🚫 Access Denied: This command requires Admin or Owner privileges.",
                        )
                    else:
                        chat_settings.ignored_languages = None
                        db.commit()
                        await send_text_message(
                            chat_id,
                            "Ignored languages for this chat reset to "
                            "GLOBAL configuration.",
                        )
                    return

                # Fetch explicit ignored list; treat None as empty list
                ignored = (
                    list(chat_settings.ignored_languages)
                    if chat_settings.ignored_languages is not None
                    else []
                )

                if subcmd == "add" and len(args) == 2:
                    if not await is_admin(db, sender_id):
                        await send_text_message(
                            chat_id,
                            "🚫 Access Denied: This command requires Admin or Owner privileges.",
                        )
                    else:
                        if args[1] not in ignored:
                            ignored.append(args[1])
                            chat_settings.ignored_languages = ignored
                            db.commit()
                        await send_text_message(
                            chat_id,
                            f"Added '{args[1]}' to explicit ignore list.",
                        )
                elif subcmd == "remove" and len(args) == 2:
                    if not await is_admin(db, sender_id):
                        await send_text_message(
                            chat_id,
                            "🚫 Access Denied: This command requires Admin or Owner privileges.",
                        )
                    else:
                        if args[1] in ignored:
                            ignored.remove(args[1])
                            chat_settings.ignored_languages = ignored
                            db.commit()
                        await send_text_message(
                            chat_id,
                            f"Removed '{args[1]}' from explicit ignore list.",
                        )
                elif subcmd == "list":
                    if chat_settings.ignored_languages is None:
                        await send_text_message(
                            chat_id,
                            "Ignored languages currently following "
                            "GLOBAL config.",
                        )
                    else:
                        await send_text_message(
                            chat_id,
                            "Explicitly ignored languages: "
                            f"{', '.join(ignored)}",
                        )

        elif command == "!t":
            if not args:
                await send_text_message(chat_id, "Please provide text to translate. Usage: !t [lang] <text>")
                return

            from app.translation import FULL_NAME_TO_CODE, is_valid_language_code
            first_word = args[0].lower()

            if first_word == "auto" and len(args) > 1:
                target_lang = "auto"
                text_to_translate = " ".join(args[1:])
            elif first_word in FULL_NAME_TO_CODE and len(args) > 1:
                target_lang = FULL_NAME_TO_CODE[first_word]
                text_to_translate = " ".join(args[1:])
            elif is_valid_language_code(first_word) and len(args) > 1:
                target_lang = first_word
                text_to_translate = " ".join(args[1:])
            else:
                target_lang = "auto"
                text_to_translate = " ".join(args)

            if not text_to_translate.strip():
                await send_text_message(chat_id, "Please provide text to translate. Usage: !t [lang] <text>")
                return

            if target_lang == "auto":
                # Cascade: Chat Setting -> Global -> Default 'en'
                target_lang = (
                    chat_settings.default_target_language
                    if chat_settings.default_target_language is not None
                    else (app_settings.GLOBAL_TARGET_LANGUAGE or "en")
                )
            if text_to_translate.strip():
                translated = await translate_text(
                    text_to_translate, target_lang
                )
                await send_text_message(chat_id, translated)

        elif command == "!summary":
            mode = args[0] if len(args) > 0 else "full"
            # Issue 14: use SUMMARY_MESSAGE_LIMIT instead of magic 30
            recent_msgs = (
                db.query(MessageBuffer)
                .filter(MessageBuffer.chat_id == chat_id)
                .order_by(MessageBuffer.timestamp.desc())
                .limit(app_settings.SUMMARY_MESSAGE_LIMIT)
                .all()
            )
            recent_msgs.reverse()

            if not recent_msgs:
                await send_text_message(
                    chat_id, "No recent messages to summarize."
                )
                return

            convo = "\n".join(
                [f"{m.sender_name}: {m.content}" for m in recent_msgs]
            )
            actual_count = len(recent_msgs)
            prompt = (
                f"Summarize the following conversation spanning the last {actual_count} messages. Mode: {mode}. "
                "For 'short', use bullet points. For 'full', include "
                "key points, decisions, and open questions.\n\n"
                f"{convo}"
            )
            summary = await ask_llm(prompt, task_type="summary")
            await send_text_message(
                chat_id, f"*Summary:*\n{summary}"
            )

        elif command == "!task":
            if len(args) >= 1:
                subcmd = args[0]
                if subcmd == "add" and len(args) > 1:
                    desc = " ".join(args[1:])
                    task = Task(chat_id=chat_id, description=desc)
                    db.add(task)
                    db.commit()
                    db.refresh(task)
                    await send_text_message(
                        chat_id, f"Task #{task.id} added."
                    )
                elif subcmd == "list":
                    tasks = (
                        db.query(Task)
                        .filter(
                            Task.chat_id == chat_id,
                            Task.is_done == False,  # noqa: E712
                        )
                        .all()
                    )
                    if tasks:
                        msg = "*Open Tasks:*\n" + "\n".join(
                            [f"#{t.id}: {t.description}" for t in tasks]
                        )
                    else:
                        msg = "No open tasks."
                    await send_text_message(chat_id, msg)
                elif subcmd == "done" and len(args) == 2:
                    # Issue 15: guard against non-integer input
                    try:
                        task_id = int(args[1])
                    except ValueError:
                        await send_text_message(
                            chat_id,
                            f"Invalid task ID '{args[1]}'. "
                            "Please provide a numeric ID "
                            "(e.g. !task done 3).",
                        )
                        return
                    task = (
                        db.query(Task)
                        .filter(
                            Task.id == task_id,
                            Task.chat_id == chat_id,
                        )
                        .first()
                    )
                    if task:
                        task.is_done = True
                        db.commit()
                        await send_text_message(
                            chat_id,
                            f"Task #{task_id} marked as done.",
                        )

        elif command == "!note":
            if len(args) >= 1:
                subcmd = args[0]
                if subcmd == "add" and len(args) > 1:
                    content = " ".join(args[1:])
                    note = Note(chat_id=chat_id, content=content)
                    db.add(note)
                    db.commit()
                    await send_text_message(chat_id, "Note added.")
                elif subcmd == "list":
                    notes = (
                        db.query(Note)
                        .filter(Note.chat_id == chat_id)
                        .all()
                    )
                    if notes:
                        msg = "*Notes:*\n" + "\n".join(
                            [f"- {n.content}" for n in notes]
                        )
                    else:
                        msg = "No notes."
                    await send_text_message(chat_id, msg)

        elif command == "!broadcast":
            if not await is_admin(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Admin or Owner privileges.",
                )
            elif len(args) == 0:
                await send_text_message(
                    chat_id,
                    "Usage: !broadcast <message> - send a message to all active chats.",
                )
            else:
                message = " ".join(args)
                chat_ids = [
                    row[0]
                    for row in db.query(ChatSettings.chat_id).all()
                    if row[0]
                ]
                for target_chat in set(chat_ids):
                    await send_text_message(target_chat, message)
                await send_text_message(
                    chat_id,
                    f"Broadcast sent to {len(set(chat_ids))} chats.",
                )

        elif command == "!stats":
            if not await is_admin(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Admin or Owner privileges.",
                )
            else:
                chat_count = db.query(ChatSettings).count()
                task_count = db.query(Task).count()
                note_count = db.query(Note).count()
                contact_count = (
                    db.query(GroupContactLedger)
                    .filter(GroupContactLedger.is_active.is_(True))
                    .count()
                )
                owner_count = (
                    db.query(BotAdmin)
                    .filter(
                        BotAdmin.role == OWNER_ROLE,
                        BotAdmin.is_active.is_(True),
                    )
                    .count()
                )
                admin_count = (
                    db.query(BotAdmin)
                    .filter(
                        BotAdmin.role == ADMIN_ROLE,
                        BotAdmin.is_active.is_(True),
                    )
                    .count()
                )
                await send_text_message(
                    chat_id,
                    "*System Stats:*\n"
                    f"Chats: {chat_count}\n"
                    f"Open tasks: {task_count}\n"
                    f"Notes: {note_count}\n"
                    f"Active contacts: {contact_count}\n"
                    f"Active owners: {owner_count}\n"
                    f"Active admins: {admin_count}",
                )

        elif command == "!ping":
            await send_text_message(chat_id, "pong")

        elif command == "!botid":
            if not await is_admin(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Admin or Owner privileges.",
                )
            else:
                from app.config import BotIdentityManager
                import time
                
                env_val = getattr(app_settings, 'BOT_NUMBER', 'Not set')
                
                now = time.time()
                ttl = getattr(app_settings, 'BOT_IDENTITY_CACHE_TTL', 300)
                cache_status = "stale"
                if (BotIdentityManager._cache is not None 
                    and BotIdentityManager._cache_timestamp is not None
                    and (now - BotIdentityManager._cache_timestamp) < ttl):
                    cache_status = "fresh"
                
                detected = BotIdentityManager.get_bot_number()
                
                match_status = "MATCH" if str(env_val) == str(detected) else "MISMATCH"
                recommendation = "All good."
                if match_status == "MISMATCH":
                    if getattr(app_settings, 'AUTO_SYNC_BOT_NUMBER', False):
                        recommendation = "Restart the bot; AUTO_SYNC_BOT_NUMBER=True will sync it at startup."
                    else:
                        recommendation = "Update BOT_NUMBER in .env to match the detected value, or set AUTO_SYNC_BOT_NUMBER=True and restart."
                        
                msg = (
                    "*Bot Identity Status*\n"
                    f"ENV value: {env_val}\n"
                    f"Detected value: {detected}\n"
                    f"Cache status: {cache_status}\n"
                    f"Match status: {match_status}\n"
                    f"Recommendation: {recommendation}"
                )
                await send_text_message(chat_id, msg)

        elif command == "!config":
            if len(args) >= 3 and args[0] == "toggle":
                feature_name = args[1]
                state_str = args[2].lower()

                if state_str not in ["on", "off"]:
                    await send_text_message(chat_id, "Usage: !config toggle <feature_name> <on|off>")
                    return

                state_bool = state_str == "on"

                try:
                    if feature_name == "agentic_search":
                        if not await is_owner(db, sender_id):
                            await send_text_message(chat_id, "🚫 Unauthorized: Only Owner can toggle features. Type !help to see available commands.")
                            return
                        app_settings.enable_agentic_search = state_bool
                        from app.utils.config_persister import persist_global_config
                        persist_global_config("enable_agentic_search", state_bool)
                        await send_text_message(chat_id, f"✅ Feature '{feature_name}' is now {state_str.upper()}.")
                    else:
                        await FeatureFlagService.toggle_feature(db, feature_name, state_bool, sender_id)
                        await send_text_message(chat_id, f"✅ Feature '{feature_name}' is now {state_str.upper()}.")
                except PermissionError:
                    await send_text_message(chat_id, "🚫 Unauthorized: Only Owner can toggle features. Type !help to see available commands.")
                except Exception as e:
                    logger.error(f"Error toggling feature: {e}")
                    await send_text_message(chat_id, "⚠️ Error toggling feature.")
            else:
                await send_text_message(chat_id, "Usage: !config toggle <feature_name> <on|off>")

        elif command == "!owner":
            if not await is_owner(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Owner privileges.",
                )
            elif len(args) == 0:
                await send_text_message(
                    chat_id,
                    "Usage: !owner grant|revoke|list|transfer <jid>",
                )
            else:
                subcmd = args[0]
                if subcmd == "grant" and len(args) == 2:
                    await grant_role(
                        db,
                        args[1],
                        OWNER_ROLE,
                        sender_id,
                    )
                    await send_text_message(
                        chat_id,
                        f"Granted owner role to {args[1]}",
                    )
                elif subcmd == "revoke" and len(args) == 2:
                    if args[1] == sender_id:
                        await send_text_message(
                            chat_id,
                            "🚫 You cannot revoke your own owner role. Transfer ownership first.",
                        )
                    else:
                        revoked = await revoke_role(
                            db, args[1], OWNER_ROLE
                        )
                        if revoked:
                            await send_text_message(
                                chat_id,
                                f"Revoked owner role from {args[1]}",
                            )
                        else:
                            await send_text_message(
                                chat_id,
                                "Could not revoke owner role. Ensure the target is an active owner and at least one owner remains.",
                            )
                elif subcmd == "transfer" and len(args) == 2:
                    if args[1] == sender_id:
                        await send_text_message(
                            chat_id,
                            "🚫 You are already the owner.",
                        )
                    else:
                        await grant_role(
                            db,
                            args[1],
                            OWNER_ROLE,
                            sender_id,
                        )
                        revoked = await revoke_role(
                            db, sender_id, OWNER_ROLE
                        )
                        if revoked:
                            await send_text_message(
                                chat_id,
                                f"Ownership transferred to {args[1]}",
                            )
                        else:
                            await send_text_message(
                                chat_id,
                                "Ownership transfer failed. Please try again.",
                            )
                elif subcmd == "list":
                    owners = await list_active_roles(db, OWNER_ROLE)
                    if owners:
                        msg = "*Active Owners:*\n" + "\n".join(
                            [f"- {o.user_id}" for o in owners]
                        )
                    else:
                        msg = "No active owners found."
                    await send_text_message(chat_id, msg)
                else:
                    await send_text_message(
                        chat_id,
                        "Usage: !owner grant|revoke|list|transfer <jid>",
                    )

        elif command == "!admin":
            if not await is_owner(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Owner privileges.",
                )
            elif len(args) == 0:
                await send_text_message(
                    chat_id,
                    "Usage: !admin grant|revoke|list <jid>",
                )
            else:
                subcmd = args[0]
                if subcmd == "grant" and len(args) == 2:
                    await grant_role(
                        db,
                        args[1],
                        ADMIN_ROLE,
                        sender_id,
                    )
                    await send_text_message(
                        chat_id,
                        f"Granted admin role to {args[1]}",
                    )
                elif subcmd == "revoke" and len(args) == 2:
                    revoked = await revoke_role(
                        db, args[1], ADMIN_ROLE
                    )
                    if revoked:
                        await send_text_message(
                            chat_id,
                            f"Revoked admin role from {args[1]}",
                        )
                    else:
                        await send_text_message(
                            chat_id,
                            "Could not revoke admin role. Ensure the target is an active admin.",
                        )
                elif subcmd == "list":
                    admins = await list_active_roles(db, ADMIN_ROLE)
                    if admins:
                        msg = "*Active Admins:*\n" + "\n".join(
                            [f"- {a.user_id}" for a in admins]
                        )
                    else:
                        msg = "No active admins found."
                    await send_text_message(chat_id, msg)
                else:
                    await send_text_message(
                        chat_id,
                        "Usage: !admin grant|revoke|list <jid>",
                    )

        elif command == "!shutdown" or command == "!restart":
            if not await is_owner(db, sender_id):
                await send_text_message(
                    chat_id,
                    "🚫 Access Denied: This command requires Owner privileges.",
                )
            else:
                if command == "!shutdown":
                    await send_text_message(chat_id, "Shutting down bot...")
                else:
                    await send_text_message(
                        chat_id,
                        "Restart requested. The bot process will stop now.",
                    )
                os._exit(0)

        elif command == "!claim_ownership":
            claimed = await try_claim_ownership(db, sender_id, is_group_chat)
            if claimed:
                await send_text_message(
                    chat_id,
                    "👑 Ownership claimed successfully! You are now the bot Owner.\n"
                    "Use `!help` to see all available commands.\n\n"
                    "⚠️ *IMPORTANT*: If this bot will be used in group chats, please go to a group, tag the bot, and send `@Bot !whoami` to initialize its identity."
                )
            else:
                if is_group_chat:
                    await send_text_message(chat_id, "⚠️ Ownership can only be claimed in a private message.")
                else:
                    await send_text_message(chat_id, "⚠️ Ownership claim unavailable. An owner already exists or is configured via environment.")

        elif command == "!search":
            if len(args) > 0:
                query = " ".join(args)
                mode = getattr(app_settings, "SEARCH_PROVIDER_MODE", "hybrid")
                searxng_url = getattr(app_settings, "SEARXNG_BASE_URL", None)
                max_results = getattr(app_settings, "search_max_results", 5)

                search_service = HybridSearchService(mode, searxng_url)

                try:
                    results = await search_service.search(query, max_results)
                    if not results:
                        await send_text_message(chat_id, f"🔍 No results found for '{query}'. Try rephrasing or using different keywords.")
                    else:
                        response_lines = [f"🔍 *Search Results for '{query}':*"]
                        for i, res in enumerate(results, 1):
                            response_lines.append(f"\n{i}. *{res.title}*\n{res.url}\n_{res.snippet}_")

                        await send_long_message(chat_id, "\n".join(response_lines))
                except Exception as e:
                    logger.error(f"Search failed for query '{query}': {e}", exc_info=True)
                    err_msg = "⚠️ Search service encountered an error. Please try again later."
                    if getattr(app_settings, "enable_agentic_search", False):
                        err_msg += " (Consider trying !s for more complex queries if enabled)"
                    await send_text_message(chat_id, err_msg)
            else:
                await send_text_message(chat_id, "Usage: !search <query>")

        elif command == "!s":
            if not getattr(app_settings, "enable_agentic_search", False):
                await send_text_message(chat_id, "🚫 Agentic search is disabled. Owner can enable via: !config toggle agentic_search on")
                return

            if len(args) > 0:
                query = " ".join(args)

                # Immediately send "Thinking..." if we anticipate it taking long, though
                # AgenticSearchOrchestrator can take ~14s, so sending this right away is good UX.
                await send_text_message(chat_id, f"🔍 *Agentic Search:* Thinking about '{query}'...")

                mode = getattr(app_settings, "SEARCH_PROVIDER_MODE", "hybrid")
                searxng_url = getattr(app_settings, "SEARXNG_BASE_URL", None)
                search_service = HybridSearchService(mode, searxng_url)
                orchestrator = AgenticSearchOrchestrator(search_service)

                try:
                    # execute_iterative_search ALWAYS returns a str — never raises.
                    # This is by design to prevent duplicate messages: if it raised,
                    # this except block would send a SECOND message.
                    final_answer = await orchestrator.execute_iterative_search(query, sender_id)
                    logger.info(f"Agentic search completed for '{query}'. Sending single response.")
                    await send_long_message(chat_id, final_answer)
                except Exception as e:
                    # Defensive safety net — should never fire since
                    # execute_iterative_search catches all exceptions internally.
                    logger.error(f"Agentic search unexpected exception for '{query}': {e} (this should not happen)")
                    await send_text_message(chat_id, "⚠️ Agentic search service encountered an error. Please try again later.")
            else:
                await send_text_message(chat_id, "Usage: !s <query>")

        elif command == "!sc":
            if not app_settings.deep_crawl_enabled:
                await send_text_message(chat_id, "🚫 Deep Crawl Search is currently disabled by admin. Owner can enable via: `!sc_toggle on`")
                return

            if len(args) > 0:
                query = " ".join(args)

                max_urls = getattr(app_settings, "deep_crawl_max_urls", 5)
                crawl_timeout = float(getattr(app_settings, "crawl_timeout_seconds", 15.0))
                est_seconds = max_urls * crawl_timeout
                await send_text_message(
                    chat_id,
                    f"🔍🕷️ *Deep Crawl Search:* Crawling up to {max_urls} sites for '{query}'... "
                    f"Estimated time: ~{int(est_seconds)}s."
                )

                mode = getattr(app_settings, "SEARCH_PROVIDER_MODE", "hybrid")
                searxng_url = getattr(app_settings, "SEARXNG_BASE_URL", None)
                search_service = HybridSearchService(mode, searxng_url)
                deep_crawl = DeepCrawlService(
                    search_service=search_service,
                )

                try:
                    # search_and_crawl ALWAYS returns a str — never raises.
                    result = await deep_crawl.search_and_crawl(query)
                    logger.info(f"Deep crawl completed for '{query}'. Sending single response.")
                    await send_long_message(chat_id, result)
                except Exception as e:
                    # Defensive safety net — should never fire since
                    # search_and_crawl catches all exceptions internally.
                    logger.error(f"Deep crawl unexpected exception for '{query}': {e} (this should not happen)")
                    await send_text_message(chat_id, "⚠️ Deep crawl service encountered an error. Please try again later.")
            else:
                await send_text_message(chat_id, "Usage: !sc <query>")

        elif command == "!pm":
            if len(args) < 2:
                await send_text_message(
                    chat_id,
                    "Usage:\n!pm @user <text>\n!pm group <text>\n!pm global <text>\n!pm flood limit <n>\n!pm flood interval <s>"
                )
                return

            subcmd = args[0]
            
            # Owner config checks
            if subcmd == "flood":
                if not await is_owner(db, sender_id):
                    await send_text_message(chat_id, "🚫 Access Denied: This command requires Owner privileges.")
                    return
                if len(args) == 3 and args[1] in ["limit", "interval"]:
                    try:
                        val = int(args[2])
                        if val <= 0:
                            await send_text_message(chat_id, "❌ Value must be greater than 0.")
                            return
                            
                        if args[1] == "limit":
                            set_global_setting(db, "pm_flood_limit", str(val))
                            await send_text_message(chat_id, f"✅ PM flood limit updated to {val} messages per batch.")
                        else:
                            set_global_setting(db, "pm_flood_interval_seconds", str(val))
                            await send_text_message(chat_id, f"✅ PM flood interval updated to {val} seconds.")
                    except ValueError:
                        await send_text_message(chat_id, "❌ Please provide a valid integer.")
                else:
                    await send_text_message(chat_id, "Usage: !pm flood limit <n> | !pm flood interval <s>")
                return

            text_to_send = " ".join(args[1:])

            if subcmd == "group":
                # Must be group admin or bot owner
                if not is_group_chat:
                    await send_text_message(chat_id, "This command can only be used in a group.")
                    return
                
                user_ledger = db.query(GroupContactLedger).filter(
                    GroupContactLedger.chat_id == chat_id,
                    GroupContactLedger.jid == sender_id
                ).first()
                is_group_admin = user_ledger and user_ledger.is_admin
                is_bot_owner = await is_owner(db, sender_id)
                
                if not is_group_admin and not is_bot_owner:
                    await send_text_message(chat_id, "🚫 Access Denied: You must be a group admin or bot owner to use this command.")
                    return
                    
                contacts = db.query(GroupContactLedger).filter(
                    GroupContactLedger.chat_id == chat_id,
                    GroupContactLedger.is_active == True,
                    GroupContactLedger.jid != sender_id # Don't PM self
                ).all()
                
                jids = [c.jid for c in contacts]
                if not jids:
                    await send_text_message(chat_id, "No active contacts found to PM.")
                    return
                    
                await send_text_message(chat_id, f"Initiating PM to {len(jids)} group members...")
                start_batched_pm_task(chat_id, jids, text_to_send)
                return

            elif subcmd == "global":
                if not await is_owner(db, sender_id):
                    await send_text_message(chat_id, "🚫 Access Denied: This command requires Owner privileges.")
                    return
                
                # Fetch distinct JIDs across all groups
                contacts = db.query(GroupContactLedger.jid).filter(
                    GroupContactLedger.is_active == True,
                    GroupContactLedger.jid != sender_id
                ).distinct().all()
                
                jids = [c[0] for c in contacts]
                if not jids:
                    await send_text_message(chat_id, "No active contacts found globally.")
                    return
                    
                await send_text_message(chat_id, f"Initiating Global PM to {len(jids)} unique members...")
                start_batched_pm_task(chat_id, jids, text_to_send)
                return
                
            else:
                # Direct user mention e.g. !pm @628123456789 Hello OR !pm 628123456789 Hello
                # Or standard mentions in WhatsApp format
                # Check permissions
                if not is_group_chat:
                     # In private chat, just checking if owner/admin
                     if not await is_admin(db, sender_id):
                         await send_text_message(chat_id, "🚫 Access Denied: Requires Admin/Owner.")
                         return
                else:
                    user_ledger = db.query(GroupContactLedger).filter(
                        GroupContactLedger.chat_id == chat_id,
                        GroupContactLedger.jid == sender_id
                    ).first()
                    is_group_admin = user_ledger and user_ledger.is_admin
                    is_bot_owner = await is_owner(db, sender_id)
                    if not is_group_admin and not is_bot_owner:
                        await send_text_message(chat_id, "🚫 Access Denied: You must be a group admin or bot owner to use this command.")
                        return

                target = subcmd.strip("@")
                # Format to JID if it doesn't have the suffix
                if "@" not in target:
                    # Strip any non-digit chars if they sent formatted number
                    import re
                    target = re.sub(r'\D', '', target)
                    if not target:
                        await send_text_message(chat_id, "Invalid number format.")
                        return
                    target_jid = f"{target}@s.whatsapp.net"
                else:
                    target_jid = target
                
                result = await send_text_message(target_jid, text_to_send)
                if result.success:
                    await send_text_message(chat_id, f"✅ PM sent to {target_jid}.")
                elif result.queued:
                    pass # Silent queueing per constraint
                else:
                    await send_text_message(chat_id, f"❌ Failed to send PM to {target_jid}.")
                return

        elif command == "!contacts":
            if len(args) == 0:
                await send_text_message(
                    chat_id,
                    "Usage: !contacts list | !contacts global | !contacts export"
                )
            else:
                subcmd = args[0]
                if subcmd == "list":
                    # Check if user is an admin of the current group
                    if not is_group_chat:
                        await send_text_message(chat_id, "This command can only be used in a group.")
                    else:
                        # Check sender permissions
                        user_ledger = db.query(GroupContactLedger).filter(
                            GroupContactLedger.chat_id == chat_id,
                            GroupContactLedger.jid == sender_id
                        ).first()
                        
                        is_group_admin = user_ledger and user_ledger.is_admin
                        is_bot_owner = await is_owner(db, sender_id)
                        
                        if not is_group_admin and not is_bot_owner:
                            await send_text_message(chat_id, "🚫 Access Denied: You must be a group admin or bot owner to use this command.")
                        else:
                            contacts = db.query(GroupContactLedger).filter(
                                GroupContactLedger.chat_id == chat_id,
                                GroupContactLedger.is_active == True
                            ).order_by(GroupContactLedger.push_name).all()
                            
                            chat_settings = get_chat_settings(db, chat_id)
                            group_name = chat_settings.group_name or "Unknown Group"
                            
                            msg = f"📋 *Active Contacts for {group_name}*\n\n"
                            for c in contacts:
                                name = c.push_name or "Unknown"
                                phone = c.phone_number or "Unknown"
                                role = "(Admin)" if c.is_admin else ""
                                msg += f"• {name} {role}\n  📞 {phone}\n"
                            
                            await send_text_message(chat_id, msg)
                
                elif subcmd == "global":
                    if not await is_owner(db, sender_id):
                        await send_text_message(chat_id, "🚫 Access Denied: This command requires Owner privileges.")
                    else:
                        all_unique_jids = set()
                        contacts_dir = "data/contacts"
                        
                        import os, json
                        from filelock import FileLock
                        if os.path.exists(contacts_dir):
                            for group_folder in os.listdir(contacts_dir):
                                if "_g_us" in group_folder:
                                    profile_path = os.path.join(contacts_dir, group_folder, "profile.json")
                                    if os.path.exists(profile_path):
                                        try:
                                            with FileLock(f"{profile_path}.lock", timeout=5):
                                                with open(profile_path, "r", encoding="utf-8") as f:
                                                    data = json.load(f)
                                                    for jid in data.get("participants", {}).keys():
                                                        all_unique_jids.add(jid)
                                        except Exception as e:
                                            logger.error(f"Failed to read {group_folder}: {e}")
                                            
                        if not all_unique_jids:
                            await send_text_message(chat_id, "📭 No contacts found in any group profiles.")
                        else:
                            await send_text_message(chat_id, "⏳ Resolving contact info from gateway... this may take a moment.")
                            
                            from app.contact_sync import resolve_participant_info_batch
                            
                            async def send_progress(current, total):
                                if current > 0 and current % 50 == 0:
                                    await send_text_message(chat_id, f"🔄 Resolving {current}/{total}...")
                                    
                            resolved_contacts = await resolve_participant_info_batch(list(all_unique_jids), send_progress)
                            hidden_count = sum(1 for info in resolved_contacts if not info.get("phone"))
                                    
                            def format_contact_entry(info: dict) -> str:
                                if info.get("phone"):
                                    return f"• +{info['phone']} ({info.get('name', 'Unknown')})"
                                else:
                                    name_val = info.get("name", "Unknown User")
                                    return f"• 🔒 Hidden (User has strict privacy settings) - {name_val}. Tip: Ask them to add your bot number as a contact to reveal their number."
                                    
                            lines = [format_contact_entry(c) for c in resolved_contacts]
                            output = "🌍 *Global Contacts Summary (Deduplicated)*\n\n" + "\n".join(lines)
                            output += f"\n\nℹ️ {hidden_count} numbers hidden. These users likely have 'Who can see my phone number' set to 'Nobody' or 'My Contacts'."
                            
                            await send_long_message(chat_id, output)
                            
                elif subcmd == "export":
                    if not await is_owner(db, sender_id):
                        await send_text_message(chat_id, "🚫 Access Denied: This command requires Owner privileges.")
                    else:
                        ledger_rows = (
                            db.query(GroupContactLedger)
                            .filter(GroupContactLedger.is_active.is_(True))
                            .all()
                        )
                        if not ledger_rows:
                            await send_text_message(
                                chat_id,
                                "No active contact ledger entries to export.",
                            )
                        else:
                            import os, csv
                            os.makedirs(
                                app_settings.CONTACTS_EXPORT_DIR,
                                exist_ok=True,
                            )
                            export_path = os.path.join(
                                app_settings.CONTACTS_EXPORT_DIR,
                                "ledger.csv",
                            )
                            with open(
                                export_path,
                                "w",
                                newline="",
                                encoding="utf-8",
                            ) as csvfile:
                                writer = csv.writer(csvfile)
                                writer.writerow(
                                    [
                                        "chat_id",
                                        "phone_number",
                                        "push_name",
                                        "is_admin",
                                        "is_active",
                                        "first_seen_at",
                                        "last_seen_at",
                                    ]
                                )
                                for row in ledger_rows:
                                    writer.writerow(
                                        [
                                            row.chat_id,
                                            row.phone_number,
                                            row.push_name or "",
                                            row.is_admin,
                                            row.is_active,
                                            row.first_seen_at.isoformat()
                                            if row.first_seen_at
                                            else "",
                                            row.last_seen_at.isoformat()
                                            if row.last_seen_at
                                            else "",
                                        ]
                                    )
                            await send_text_message(
                                chat_id,
                                f"✅ Contacts exported to: {export_path}",
                            )

        elif command == "!resolve":
            if not await is_owner(db, sender_id):
                await send_text_message(chat_id, "🚫 Access Denied: This command requires Owner privileges.")
                return
                
            if len(args) == 0 and not mentioned_jids:
                await send_text_message(chat_id, "Usage: !resolve @mention OR !resolve group OR !resolve global")
                return
                
            from app.contact_sync import resolve_participant_info
            
            if args and args[0] == "global":
                import os, json, asyncio
                from filelock import FileLock
                all_unique_jids = set()
                contacts_dir = "data/contacts"
                if os.path.exists(contacts_dir):
                    for group_folder in os.listdir(contacts_dir):
                        if "_g_us" in group_folder:
                            profile_path = os.path.join(contacts_dir, group_folder, "profile.json")
                            if os.path.exists(profile_path):
                                try:
                                    with FileLock(f"{profile_path}.lock", timeout=5):
                                        with open(profile_path, "r", encoding="utf-8") as f:
                                            data = json.load(f)
                                            for j in data.get("participants", {}).keys():
                                                all_unique_jids.add(j)
                                except Exception as e:
                                    logger.error(f"Failed to read {group_folder}: {e}")
                
                if not all_unique_jids:
                    await send_text_message(chat_id, "📭 No contacts found to resolve.")
                    return
                    
                total = len(all_unique_jids)
                await send_text_message(chat_id, f"🔄 Starting global resolution for {total} users... This will run in the background. Results will be sent to you via DM when complete.")
                
                async def run_global_resolution_bg(jids, recipient_id):
                    from app.contact_sync import resolve_participant_info_batch
                    
                    async def send_progress(current, total_bg):
                        if current > 0 and current % 100 == 0:
                            await send_text_message(recipient_id, f"⏳ Progress: Resolving {current}/{total_bg} users...")
                            
                    resolved = await resolve_participant_info_batch(jids, send_progress)
                    resolved_count = sum(1 for info in resolved if info.get("phone"))
                    hidden_count = len(resolved) - resolved_count
                    
                    def format_contact_entry(info: dict) -> str:
                        if info.get("phone"):
                            return f"• +{info['phone']} ({info.get('name', 'Unknown')})"
                        else:
                            name_val = info.get("name", "Unknown User")
                            return f"• 🔒 Hidden (User has strict privacy settings) - {name_val}. Tip: Ask them to add your bot number as a contact to reveal their number."
                            
                    lines = [format_contact_entry(c) for c in resolved]
                    output = f"✅ *Global Resolution Complete*\n\nResolved {resolved_count}/{total} numbers.\n\n" + "\n".join(lines)
                    output += f"\n\nℹ️ {hidden_count} numbers hidden. These users likely have 'Who can see my phone number' set to 'Nobody' or 'My Contacts'."
                    
                    await send_long_message(recipient_id, output)
                    
                asyncio.create_task(run_global_resolution_bg(list(all_unique_jids), sender_id))
            
            elif args and args[0] == "group":
                if not is_group_chat:
                    await send_text_message(chat_id, "❌ This command must be used within a group chat.")
                    return
                    
                import os, json, asyncio
                from filelock import FileLock
                all_unique_jids = set()
                contacts_dir = "data/contacts"
                # Remove suffix '@g.us' -> '_g_us' to match folder names
                folder_name = f"{chat_id.replace('@g.us', '_g_us')}"
                profile_path = os.path.join(contacts_dir, folder_name, "profile.json")
                
                if os.path.exists(profile_path):
                    try:
                        with FileLock(f"{profile_path}.lock", timeout=5):
                            with open(profile_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                for j in data.get("participants", {}).keys():
                                    all_unique_jids.add(j)
                    except Exception as e:
                        logger.error(f"Failed to read {folder_name}: {e}")
                        
                if not all_unique_jids:
                    await send_text_message(chat_id, "📭 No contacts found in this group to resolve.")
                    return
                    
                total = len(all_unique_jids)
                await send_text_message(chat_id, f"🔍 Starting group resolution for {total} users in batches...")
                
                from app.contact_sync import resolve_participant_info_batch
                
                async def send_progress(current, total_bg):
                    if current > 0 and current % 50 == 0:
                        await send_text_message(chat_id, f"⏳ Progress: {current}/{total_bg} users processed...")
                        
                resolved = await resolve_participant_info_batch(list(all_unique_jids), send_progress)
                resolved_count = sum(1 for info in resolved if info.get("phone"))
                hidden_count = len(resolved) - resolved_count
                
                await send_text_message(chat_id, f"✅ *Group Resolution Complete*\n\nResolved {resolved_count}/{total} numbers.\n{hidden_count} hidden by privacy settings.")
                
            else:
                jid = mentioned_jids[0]
                info = await resolve_participant_info(jid)
                if info.get("phone"):
                    reply = f"✅ Resolved: +{info['phone']} ({info.get('name', 'Unknown')})"
                else:
                    reply = f"🔒 Hidden (User has strict privacy settings) - {info.get('name', 'Unknown')}. Tip: Ask them to add your bot number as a contact to reveal their number."
                await send_text_message(chat_id, reply)

        elif command == "!chatty":
            if len(args) == 1 and args[0] in ["on", "off"]:
                status = args[0] == "on"
                if is_group_chat:
                    user_ledger = db.query(GroupContactLedger).filter(
                        GroupContactLedger.chat_id == chat_id,
                        GroupContactLedger.jid == sender_id
                    ).first()
                    is_group_admin = user_ledger and user_ledger.is_admin
                    is_bot_owner = await is_owner(db, sender_id)
                    if not is_group_admin and not is_bot_owner:
                        await send_text_message(chat_id, "🚫 Access Denied: You must be a group admin or bot owner to toggle Chatty in a group.")
                        return

                profile = read_profile(chat_id)
                profile["chatty_status"] = status
                write_profile(chat_id, profile)

                await send_text_message(chat_id, f"✅ Chatty mode turned {'ON' if status else 'OFF'}.")
            else:
                await send_text_message(chat_id, "Usage: !chatty on | !chatty off")

        elif command == "!chatty_freq":
            if not is_group_chat:
                await send_text_message(chat_id, "This command is only available in groups.")
                return
            user_ledger = db.query(GroupContactLedger).filter(
                    GroupContactLedger.chat_id == chat_id,
                GroupContactLedger.jid == sender_id
            ).first()
            is_group_admin = user_ledger and user_ledger.is_admin
            is_bot_owner = await is_owner(db, sender_id)
            if not is_group_admin and not is_bot_owner:
                await send_text_message(chat_id, "🚫 Access Denied: You must be a group admin or bot owner.")
                return
            if len(args) != 1:
                await send_text_message(chat_id, "Usage: !chatty_freq <number>")
                return
            try:
                freq = int(args[0])
                if not 10 <= freq <= 1000:
                    raise ValueError
            except ValueError:
                await send_text_message(chat_id, "Frequency must be an integer between 10 and 1000.")
                return

            profile = read_profile(chat_id)
            profile["chatty_frequency"] = freq
            write_profile(chat_id, profile)

            await send_text_message(chat_id, f"✅ Chatty frequency set to {freq} messages.")

        elif command == "!chatty_burst":
            if not is_group_chat:
                await send_text_message(chat_id, "This command is only available in groups.")
                return
            user_ledger = db.query(GroupContactLedger).filter(
                    GroupContactLedger.chat_id == chat_id,
                GroupContactLedger.jid == sender_id
            ).first()
            is_group_admin = user_ledger and user_ledger.is_admin
            is_bot_owner = await is_owner(db, sender_id)
            if not is_group_admin and not is_bot_owner:
                await send_text_message(chat_id, "🚫 Access Denied: You must be a group admin or bot owner.")
                return
            if len(args) != 1:
                await send_text_message(chat_id, "Usage: !chatty_burst <number>")
                return
            try:
                burst = int(args[0])
                if not 1 <= burst <= 5:
                    raise ValueError
            except ValueError:
                await send_text_message(chat_id, "Burst count must be an integer between 1 and 5.")
                return

            profile = read_profile(chat_id)
            profile["chatty_burst"] = burst
            write_profile(chat_id, profile)

            await send_text_message(chat_id, f"✅ Chatty burst set to {burst} messages.")

        elif command == "!chatty_delay":
            if is_group_chat:
                user_ledger = db.query(GroupContactLedger).filter(
                    GroupContactLedger.chat_id == chat_id,
                    GroupContactLedger.jid == sender_id
                ).first()
                is_group_admin_check = user_ledger and user_ledger.is_admin
                is_bot_owner_check = await is_owner(db, sender_id)
                if not is_group_admin_check and not is_bot_owner_check:
                    await send_text_message(chat_id, "❌ Access Denied: You must be a group admin or bot owner to change Chatty delay.")
                    return

            if len(args) != 2:
                await send_text_message(chat_id, "Usage: !chatty_delay <min> <max>")
                return

            try:
                delay_min = int(args[0])
                delay_max = int(args[1])
                if delay_min < 0 or delay_max < delay_min:
                    raise ValueError
            except ValueError:
                await send_text_message(chat_id, "❌ Minimum and maximum must be valid positive numbers, and max must be >= min.")
                return

            profile = read_profile(chat_id)
            profile["chatty_delay_min"] = delay_min
            profile["chatty_delay_max"] = delay_max
            write_profile(chat_id, profile)

            await send_text_message(chat_id, f"✅ Chatty delay set to {delay_min}-{delay_max} seconds.")

        elif command == "!chatty_mode":
            if is_group_chat:
                user_ledger = db.query(GroupContactLedger).filter(
                    GroupContactLedger.chat_id == chat_id,
                    GroupContactLedger.jid == sender_id
                ).first()
                is_group_admin_check = user_ledger and user_ledger.is_admin
                is_bot_owner_check = await is_owner(db, sender_id)
                if not is_group_admin_check and not is_bot_owner_check:
                    await send_text_message(chat_id, "❌ Access Denied: You must be a group admin or bot owner to change Chatty mode.")
                    return

            if len(args) != 1 or args[0].lower() not in ["debounce", "throttle"]:
                await send_text_message(chat_id, "Usage: !chatty_mode <debounce|throttle>\n\n*debounce*: resets the timer on every new message (waits until you stop typing).\n*throttle*: responds exactly N seconds after your first message.")
                return

            mode = args[0].lower()
            profile = read_profile(chat_id)
            profile["chatty_delay_mode"] = mode
            write_profile(chat_id, profile)

            await send_text_message(chat_id, f"✅ Chatty delay mode set to '{mode}'.")

        elif command == "!chatty_status":
            profile = read_profile(chat_id)

            default_status = app_settings.CHATTY_GROUP_DEFAULT if chat_id.endswith("@g.us") else app_settings.CHATTY_DEFAULT
            status = profile.get("chatty_status", default_status)
            freq = profile.get("chatty_frequency", app_settings.CHATTY_DEFAULT_FREQUENCY)
            burst = profile.get("chatty_burst", app_settings.CHATTY_DEFAULT_BURST)
            d_min = profile.get("chatty_delay_min", app_settings.CHATTY_DELAY_MIN)
            d_max = profile.get("chatty_delay_max", app_settings.CHATTY_DELAY_MAX)
            d_mode = profile.get("chatty_delay_mode", app_settings.CHATTY_DELAY_MODE)
            counter = profile.get("message_counter", 0)
            lang = profile.get("preferred_language", "Auto")

            msg = f"🧠 *Chatty Status*\n\nStatus: {'ON' if status else 'OFF'}\nFrequency: {freq}\nBurst: {burst}\nDelay: {d_min}-{d_max}s ({d_mode})\nCounter: {counter}/{freq}\nPreferred Lang: {lang}"
            await send_text_message(chat_id, msg)

        elif command == "!lang":
            if is_group_chat:
                await send_text_message(chat_id, "This command is only available in DMs. Use !target for groups.")
                return
            if len(args) == 0:
                await send_text_message(chat_id, "Usage: !lang set <code> | !lang reset")
                return

            subcmd = args[0]
            profile = read_profile(chat_id)

            if subcmd == "reset":
                profile["preferred_language"] = None
                write_profile(chat_id, profile)
                await send_text_message(chat_id, "✅ Preferred language reset to auto-detect.")
            elif subcmd == "set" and len(args) == 2:
                # Issue: Language Code Sanitization
                SUPPORTED_CODES = ['en', 'id', 'ms', 'zh', 'ja', 'ko', 'fr', 'de', 'es', 'pt', 'ru', 'ar']
                LANG_MAP = {
                    'english': 'en', 'indonesian': 'id', 'malay': 'ms',
                    'chinese': 'zh', 'japanese': 'ja', 'korean': 'ko',
                    'french': 'fr', 'german': 'de', 'spanish': 'es',
                    'portuguese': 'pt', 'russian': 'ru', 'arabic': 'ar'
                }

                raw_input = args[1].lower().strip()
                code = LANG_MAP.get(raw_input, raw_input.split('-')[0])

                if code not in SUPPORTED_CODES:
                    await send_text_message(chat_id, f"Invalid language. Please use codes like 'en', 'id', 'ms'. Supported: {', '.join(SUPPORTED_CODES)}")
                    return

                profile["preferred_language"] = code
                write_profile(chat_id, profile)
                await send_text_message(chat_id, f"✅ Preferred language set to {code}.")
            else:
                await send_text_message(chat_id, "Usage: !lang set <code> | !lang reset")

        elif command == "!a":
            if len(args) > 0:
                ai_prompt = " ".join(args)
                response = await ask_llm(
                    ai_prompt, task_type="generic"
                )
                await send_long_message(chat_id, response)
            else:
                await send_text_message(
                    chat_id,
                    "Usage: !a <text> - Ask the AI any general question or request.",
                )

        else:
            await send_text_message(
                chat_id,
                "Unknown command. Type !help for available commands."
            )

    except Exception as exc:
        logger.error(
            "Error handling command %s: %s", command, exc
        )
        await send_text_message(
            chat_id,
            "Something went wrong, please try again later.",
        )
