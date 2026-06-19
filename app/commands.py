import logging
from sqlalchemy.orm import Session
from app.state import get_chat_settings, Task, Note, MessageBuffer
from app.translation import translate_text, detect_language
from app.whatsapp_gateway import send_text_message
from app.ai_client import ask_llm
from app.config import settings as app_settings

logger = logging.getLogger(__name__)


async def handle_command(  # Issue 13: added return type
    text: str, chat_id: str, sender_id: str, db: Session
) -> None:
    parts = text.strip().split()
    if not parts:
        return

    command = parts[0].lower()
    args = parts[1:]
    settings = get_chat_settings(db, chat_id)

    try:
        if command == "!help":
            help_text = (
                "*WhatsApp Casual Bot Commands*\n"
                "!auto on|off|global - Toggle auto-translation\n"
                "!target <lang>|global - Set target language\n"
                "!ignore add|remove <lang> - Manage ignore list\n"
                "!ignore list - Show ignored languages\n"
                "!ignore global - Reset ignore list to global\n"
                "!t <lang> <text> - Translate text to lang\n"
                "!t auto <text> - Translate to default target\n"
                "!summary [short|full] - Summarize recent messages\n"
                "!task add <desc> - Add a task\n"
                "!task list - List tasks\n"
                "!task done <id> - Complete a task\n"
                "!note add <text> - Add a note\n"
                "!note list - List notes\n"
                "!search <query> - Search the web (if enabled)\n"
            )
            await send_text_message(chat_id, help_text)

        elif command == "!auto":
            if len(args) == 1:
                if args[0] in ["on", "off"]:
                    settings.auto_translate_enabled = (args[0] == "on")
                    db.commit()
                    state = (
                        "ON"
                        if settings.auto_translate_enabled
                        else "OFF"
                    )
                    await send_text_message(
                        chat_id,
                        f"Auto-translate for this chat is now "
                        f"explicitly {state}.",
                    )
                elif args[0] == "global":
                    settings.auto_translate_enabled = None
                    db.commit()
                    await send_text_message(
                        chat_id,
                        "Auto-translate for this chat reset to "
                        "GLOBAL configuration.",
                    )

        elif command == "!target":
            if len(args) == 1:
                if args[0] == "global":
                    settings.default_target_language = None
                    db.commit()
                    await send_text_message(
                        chat_id,
                        "Target language for this chat reset to "
                        "GLOBAL configuration.",
                    )
                else:
                    settings.default_target_language = args[0]
                    db.commit()
                    await send_text_message(
                        chat_id,
                        f"Default target language set to: {args[0]}",
                    )

        elif command == "!ignore":
            if len(args) >= 1:
                subcmd = args[0]

                if subcmd == "global":
                    settings.ignored_languages = None
                    db.commit()
                    await send_text_message(
                        chat_id,
                        "Ignored languages for this chat reset to "
                        "GLOBAL configuration.",
                    )
                    return

                # Fetch explicit ignored list; treat None as empty list
                ignored = (
                    list(settings.ignored_languages)
                    if settings.ignored_languages is not None
                    else []
                )

                if subcmd == "add" and len(args) == 2:
                    if args[1] not in ignored:
                        ignored.append(args[1])
                        settings.ignored_languages = ignored
                        db.commit()
                    await send_text_message(
                        chat_id,
                        f"Added '{args[1]}' to explicit ignore list.",
                    )
                elif subcmd == "remove" and len(args) == 2:
                    if args[1] in ignored:
                        ignored.remove(args[1])
                        settings.ignored_languages = ignored
                        db.commit()
                    await send_text_message(
                        chat_id,
                        f"Removed '{args[1]}' from explicit ignore list.",
                    )
                elif subcmd == "list":
                    if settings.ignored_languages is None:
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
            if len(args) >= 2:
                target_lang = args[0]
                text_to_translate = " ".join(args[1:])
                if target_lang == "auto":
                    # Cascade: Chat Setting -> Global -> Default 'en'
                    target_lang = (
                        settings.default_target_language
                        if settings.default_target_language is not None
                        else (app_settings.GLOBAL_TARGET_LANGUAGE or "en")
                    )
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
            prompt = (
                f"Summarize the following conversation. Mode: {mode}. "
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

        elif command == "!search":
            if len(args) > 0:
                query = " ".join(args)
                prompt = (
                    "Answer this query concisely using internal knowledge "
                    "and reasoning. Do not claim live web access is available. "
                    "If the query asks for current news, weather, or live data, "
                    "state that live access is unavailable and provide useful "
                    "guidance on how the user can obtain the latest information."
                    f"\n\nQuery: {query}"
                )
                answer = await ask_llm(
                    prompt, task_type="search_answer"
                )
                if answer.lower().startswith(
                    "i do not have access"
                ) or "cannot access" in answer.lower():
                    await send_text_message(
                        chat_id,
                        "This bot currently does not have live web search "
                        "access. Please ask a different question or verify "
                        "your search API configuration.",
                    )
                else:
                    await send_text_message(
                        chat_id, f"*Search Results:*\n{answer}"
                    )

    except Exception as exc:
        logger.error(
            "Error handling command %s: %s", command, exc
        )
        await send_text_message(
            chat_id,
            "Something went wrong, please try again later.",
        )
