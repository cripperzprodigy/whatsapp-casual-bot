# Portable Backup & Restore System

The bot includes a robust, cross-platform utility (`backup_restore.py`) designed to make migrating the WhatsApp Bot to a new server or backing up its critical state seamless and secure.

## 🗂️ Critical State Paths

The backup script dynamically identifies and packs only the essential files required to resume operations on a new machine without data loss or the need to re-authenticate WhatsApp:

1. **Authentication Session:**
   - `.wwebjs_auth/` / `.wwebjs_cache/` (Holds WhatsApp Web session keys to avoid QR re-scanning).
2. **Configuration:**
   - `.env` (API keys, models, global settings).
3. **Bot State & RAG Storage:**
   - `bot.db` (Primary SQLite database tracking groups, tasks, and permissions).
   - `data/` (Strictly isolated folder containing `config.json`, user RAG vector DBs, user `profile.json` states, and media).

To maintain security and minimize the backup size, the script explicitly excludes `venv/`, `node_modules/`, `exports/`, `logs`, and OS metadata (e.g. `.DS_Store`).

---

## 🔁 Backup / Restore Logic (Flow Diagram)

```text
               [ Administrator ]
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
[ --mode backup ]              [ --mode restore ]
       │                               │
       │                        1. Target ZIP via --file
1. Scan Root Directory          2. Check for active sessions
   for Critical Paths              (e.g., .wwebjs_auth/)
       │                               │
2. Prune bloat/cache            3. Prompt for overwrite safety
   (venv, node_modules)            (Optional auto pre-restore backup)
       │                               │
3. Archive to timestamped       4. Extract ZIP to current dir
   ZIP file                        (Preserving script chmod)
       │                               │
       ▼                               ▼
[ bot_backup_*.zip ]           [ Fully Restored Bot State ]
```

---

## 🛠️ Usage Examples

The script runs on standard Python 3.9+ and requires no external `pip` dependencies.

### Backing Up the Bot
```bash
python3 backup_restore.py --mode backup
```
This produces a zip file (e.g. `bot_backup_20240620_142010.zip`). You can also specify an exact filename:
```bash
python3 backup_restore.py --mode backup --file my_bot_migration.zip
```

### Restoring the Bot
Move your archived zip file to the freshly cloned repository directory on the new machine and execute:
```bash
python3 backup_restore.py --mode restore --file my_bot_migration.zip
```
*Note: If the script detects existing WhatsApp sessions, it will prompt you for confirmation to avoid accidental data destruction. To bypass this prompt (e.g. in automated CI/CD environments), append the `-y` or `--yes` flag.*
