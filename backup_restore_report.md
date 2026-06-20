# Backup & Restore System Report

## Identified Critical State Paths
Based on a scan of the codebase, the following files and folders have been identified as containing critical authentication, configuration, and persistent state data required for migrating the bot to a fresh installation:

1. **Authentication Session:**
   - `.wwebjs_auth/` (Identified in `whatsapp-service/index.js` as the default `SESSION_PATH` for `whatsapp-web.js`). This folder holds the encrypted keys to prevent QR code re-scanning.
   - `.wwebjs_cache/` (Often created alongside `.wwebjs_auth/` by puppeteer/whatsapp-web.js).

2. **Configuration:**
   - `.env` (The primary environment variables file containing API keys and global configurations).

3. **Bot State & Persistent Storage:**
   - `bot.db` (The SQLite database configured in `app/config.py` containing groups, commands, ledgers, etc).
   - `data/` (The folder containing `config.json`, `system_prompts/`, and all strictly isolated user data in `contacts/` such as `profile.json`, ChromaDB vector stores, and downloaded media).

## Excluded Paths (To reduce backup size and improve security/portability)
- `__pycache__/`
- `venv/`, `.venv/`, `env/`
- `node_modules/`
- `.git/`
- `exports/` (CSV/Markdown exports can be regenerated or are not strictly required for bot operation)
- Log files (`*.log`)


## Usage Examples

The script is a completely self-contained Python file (`backup_restore.py`) and utilizes standard Python libraries without requiring any external dependencies.

### 1. Backing Up the Bot
To securely pack the application's environment, database, isolated RAG data, and active WhatsApp sessions:

```bash
python3 backup_restore.py --mode backup
```
This will scan the current directory and produce a timestamped zip file (e.g. `bot_backup_20240620_142010.zip`).

*Optionally, to specify the exact name of the output backup:*
```bash
python3 backup_restore.py --mode backup --file my_bot_migration.zip
```

### 2. Restoring the Bot on a Fresh Machine
Upload the backup ZIP to your new server instance, place it inside your cloned codebase directory, and run:

```bash
python3 backup_restore.py --mode restore --file bot_backup_20240620_142010.zip
```
During restore:
1. The script dynamically checks if the new installation directory already has active WhatsApp sessions to prevent accidental destruction.
2. If sessions are found, it will warn you and prompt for confirmation. (You can skip this prompt by adding `-y` or `--yes` to the command).
3. If confirmed, it will automatically execute a "pre-restore" snapshot backup of the current state before unpacking your archived states over the top of it, ensuring total safety against data loss.
4. Shell scripts (`.sh`) will automatically have their executable permissions restored via `chmod 0o755`.
