import logging
from sqlalchemy.orm import Session
from app.state import get_chat_settings, Task, Note, MessageBuffer
from app.translation import translate_text, detect_language
from app.whatsapp_gateway import send_text_message
from app.ai_client import ask_llm
from app.config import settings as app_settings

logger = logging.getLogger(__name__)

async def handle_command(text: str, chat_id: str, sender_id: str, db: Session):
    parts = text.strip().split()
    if not parts:
        return
    
    command = parts[0].lower()
    args = parts[1:]
    settings = get_chat_settings(db, chat_id)
    
    try:
        if command == "!help":
            help_text = """*WhatsApp Casual Bot Commands*
!auto on|off|global - Toggle auto-translation (or reset to global)
!target <lang>|global - Set target lang (or reset to global)
!ignore add|remove <lang> - Manage ignore list
!ignore list - Show ignored languages
!ignore global - Reset ignore list to global config
!t <lang> <text> - Translate text to lang
!t auto <text> - Translate to default target
!summary [short|full] - Summarize recent messages
!task add <desc> - Add a task
!task list - List tasks
!task done <id> - Complete a task
!note add <text> - Add a note
!note list - List notes
!search <query> - Search the web (if enabled)
"""
            await send_text_message(chat_id, help_text)

        elif command == "!auto":
            if len(args) == 1:
                if args[0] in ["on", "off"]:
                    settings.auto_translate_enabled = (args[0] == "on")
                    db.commit()
                    await send_text_message(chat_id, f"Auto-translate for this chat is now explicitly {'ON' if settings.auto_translate_enabled else 'OFF'}.")
                elif args[0] == "global":
                    settings.auto_translate_enabled = None
                    db.commit()
                    await send_text_message(chat_id, f"Auto-translate for this chat reset to GLOBAL configuration.")
        
        elif command == "!target":
            if len(args) == 1:
                if args[0] == "global":
                    settings.default_target_language = None
                    db.commit()
                    await send_text_message(chat_id, "Target language for this chat reset to GLOBAL configuration.")
                else:
                    settings.default_target_language = args[0]
                    db.commit()
                    await send_text_message(chat_id, f"Default target language set to: {args[0]}")

        elif command == "!ignore":
            if len(args) >= 1:
                subcmd = args[0]
                
                if subcmd == "global":
                    settings.ignored_languages = None
                    db.commit()
                    await send_text_message(chat_id, "Ignored languages for this chat reset to GLOBAL configuration.")
                    return
                
                # Fetch explicit ignored list, if it's currently falling back to global (None), treat it as an empty list to start appending.
                ignored = list(settings.ignored_languages) if settings.ignored_languages is not None else []
                
                if subcmd == "add" and len(args) == 2:
                    if args[1] not in ignored:
                        ignored.append(args[1])
                        settings.ignored_languages = ignored
                        db.commit()
                    await send_text_message(chat_id, f"Added '{args[1]}' to explicit ignore list.")
                elif subcmd == "remove" and len(args) == 2:
                    if args[1] in ignored:
                        ignored.remove(args[1])
                        settings.ignored_languages = ignored
                        db.commit()
                    await send_text_message(chat_id, f"Removed '{args[1]}' from explicit ignore list.")
                elif subcmd == "list":
                    if settings.ignored_languages is None:
                        await send_text_message(chat_id, "Ignored languages currently following GLOBAL config.")
                    else:
                        await send_text_message(chat_id, f"Explicitly ignored languages: {', '.join(ignored)}")

        elif command == "!t":
            if len(args) >= 2:
                target_lang = args[0]
                text_to_translate = " ".join(args[1:])
                if target_lang == "auto":
                    # Fallback cascade: Chat Setting -> Global Setting -> Default ('en')
                    target_lang = settings.default_target_language if settings.default_target_language is not None else (app_settings.GLOBAL_TARGET_LANGUAGE or "en")
                translated = await translate_text(text_to_translate, target_lang)
                await send_text_message(chat_id, translated)
                
        elif command == "!summary":
            mode = args[0] if len(args) > 0 else "full"
            recent_msgs = db.query(MessageBuffer).filter(MessageBuffer.chat_id == chat_id).order_by(MessageBuffer.timestamp.desc()).limit(30).all()
            recent_msgs.reverse()
            
            if not recent_msgs:
                await send_text_message(chat_id, "No recent messages to summarize.")
                return
                
            convo = "\n".join([f"{m.sender_name}: {m.content}" for m in recent_msgs])
            
            prompt = f"Summarize the following conversation. Mode: {mode}. For 'short', use bullet points. For 'full', include key points, decisions, and open questions.\n\n{convo}"
            summary = await ask_llm(prompt, task_type="summary")
            await send_text_message(chat_id, f"*Summary:*\n{summary}")

        elif command == "!task":
            if len(args) >= 1:
                subcmd = args[0]
                if subcmd == "add" and len(args) > 1:
                    desc = " ".join(args[1:])
                    task = Task(chat_id=chat_id, description=desc)
                    db.add(task)
                    db.commit()
                    db.refresh(task)
                    await send_text_message(chat_id, f"Task #{task.id} added.")
                elif subcmd == "list":
                    tasks = db.query(Task).filter(Task.chat_id == chat_id, Task.is_done == False).all()
                    if tasks:
                        msg = "*Open Tasks:*\n" + "\n".join([f"#{t.id}: {t.description}" for t in tasks])
                    else:
                        msg = "No open tasks."
                    await send_text_message(chat_id, msg)
                elif subcmd == "done" and len(args) == 2:
                    task_id = int(args[1])
                    task = db.query(Task).filter(Task.id == task_id, Task.chat_id == chat_id).first()
                    if task:
                        task.is_done = True
                        db.commit()
                        await send_text_message(chat_id, f"Task #{task_id} marked as done.")

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
                    notes = db.query(Note).filter(Note.chat_id == chat_id).all()
                    if notes:
                        msg = "*Notes:*\n" + "\n".join([f"- {n.content}" for n in notes])
                    else:
                        msg = "No notes."
                    await send_text_message(chat_id, msg)
                    
        elif command == "!search":
             if len(args) > 0:
                 query = " ".join(args)
                 # Mock web search behavior since we don't have a specific API configured
                 prompt = f"Using your internal knowledge as a simulated web search, answer this query concisely: {query}"
                 answer = await ask_llm(prompt, task_type="search_answer")
                 await send_text_message(chat_id, f"*Search Results:*\n{answer}")

    except Exception as e:
        logger.error(f"Error handling command {command}: {e}")
        await send_text_message(chat_id, "Something went wrong, please try again later.")
