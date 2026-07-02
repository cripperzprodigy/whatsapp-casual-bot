"""
Migration Script: Scoped Preference Migration (Task 2 — Preference Scoping).

ADR-036: Migrates existing global user preferences (stored in per-chat
profile.json files) into the new (user_id, global) scoped preference file.

This script is idempotent — safe to run multiple times. For DM chats
(chat_id == user_id), the profile.json data is copied into the user's
``data/prefs/<user>/global.json`` so that existing language and persona
settings are preserved under the new fallback chain.

Usage:
    python -m scripts.migrate_preferences_scope [--dry-run] [--chat-id ID]

Options:
    --dry-run       Print what would be migrated without writing any files.
    --chat-id ID    Migrate only the specified chat ID.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow running as `python -m scripts.migrate_preferences_scope` from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.profile_service import (
    GLOBAL_PREFERENCE_KEYS,
    PERSONA_PREFERENCE_KEYS,
    _get_global_pref_path,
    _get_scoped_pref_path,
)
from filelock import FileLock

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("migrate_preferences_scope")

# Keys that are meaningful to preserve from old profile.json files
_MIGRATE_KEYS = GLOBAL_PREFERENCE_KEYS | PERSONA_PREFERENCE_KEYS | {
    "chatty_status",
    "chatty_frequency",
    "chatty_burst",
}


def _is_dm_chat(chat_id: str) -> bool:
    """Heuristic: DM chat IDs don't contain @g.us."""
    return "@g.us" not in chat_id


def migrate_chat(contacts_dir: Path, chat_dir: Path, dry_run: bool) -> bool:
    """Migrate a single contact directory.  Returns True if any data was written."""
    profile_path = chat_dir / "profile.json"
    if not profile_path.exists():
        return False

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception as e:
        logger.warning(f"  Could not read {profile_path}: {e}")
        return False

    # Reconstruct chat_id from the directory name (reverse the safe_id transform)
    # safe_id = chat_id.replace('@', '_').replace('.', '_')
    # We can't perfectly reverse this, so we search existing profile for stored chat_id
    # or fall back to inferring from directory name.
    safe_id = chat_dir.name
    # Try to read an explicit chat_id stored in the profile
    chat_id = profile.get("chat_id") or profile.get("jid") or None

    if not chat_id:
        # Best-effort: reconstruct from safe_id.  The directory name has @ → _ and . → _
        # which is not fully reversible, so we log a warning.
        logger.debug(f"  No explicit chat_id in profile for dir={safe_id}; using safe_id as chat_id")
        chat_id = safe_id  # This won't be a valid JID but is used only as scope key

    # Only migrate DM profiles into the global pref file
    # Group profiles are preserved in their existing location (group-scoped by default)
    if not _is_dm_chat(chat_id):
        logger.info(f"  Skipping group chat: {chat_id}")
        return False

    # For DM chats, copy relevant keys to (user_id=chat_id, global) pref file
    global_path = _get_global_pref_path(user_id=chat_id)
    lock_path = str(global_path) + ".lock"

    existing: dict = {}
    if global_path.exists():
        try:
            with open(global_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    to_migrate = {k: v for k, v in profile.items() if k in _MIGRATE_KEYS and v is not None}
    if not to_migrate:
        logger.debug(f"  Nothing to migrate for {chat_id}")
        return False

    # Merge: don't overwrite keys that already exist in the new scoped file
    merged = {**to_migrate, **existing}  # existing takes precedence

    if dry_run:
        logger.info(f"  [DRY RUN] Would write to {global_path}: {merged}")
        return True

    with FileLock(lock_path):
        global_path.parent.mkdir(parents=True, exist_ok=True)
        with open(global_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)

    logger.info(f"  Migrated {list(to_migrate.keys())} → {global_path}")
    return True


def run_migration(dry_run: bool = False, filter_chat_id: str | None = None) -> int:
    contacts_root = Path("./data/contacts")
    if not contacts_root.exists():
        logger.warning(f"Contacts directory not found: {contacts_root}. Nothing to migrate.")
        return 0

    migrated = 0
    for chat_dir in sorted(contacts_root.iterdir()):
        if not chat_dir.is_dir():
            continue

        if filter_chat_id:
            safe_filter = filter_chat_id.replace('@', '_').replace('.', '_')
            if chat_dir.name != safe_filter:
                continue

        logger.info(f"Processing: {chat_dir.name}")
        if migrate_chat(contacts_root, chat_dir, dry_run=dry_run):
            migrated += 1

    logger.info(
        f"\nMigration {'(DRY RUN) ' if dry_run else ''}complete. "
        f"{migrated} profile(s) processed."
    )
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate existing global user preferences to scoped preference files."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be migrated without writing files.",
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help="Migrate only the specified chat ID.",
    )
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run, filter_chat_id=args.chat_id)


if __name__ == "__main__":
    main()
