#!/usr/bin/env python3
import os
import sys
import zipfile
import argparse
import shutil
from datetime import datetime
from pathlib import Path

# Common names for critical files/folders
CRITICAL_PATHS = {
    "session_folders": [".wwebjs_auth", "baileys_auth", "session", ".wwebjs_cache"],
    "env_files": [".env"],
    "state_files": ["bot.db", "bot.sqlite", "bot.sqlite3"],
    "data_folders": ["data"]
}

# Paths to explicitly exclude
EXCLUDE_DIRS = {"__pycache__", "venv", ".venv", "env", "node_modules", ".git", "exports"}
EXCLUDE_EXTS = {".log", ".pyc"}

def is_excluded(path: Path) -> bool:
    """Checks if a path should be excluded based on its parts or extension."""
    if path.suffix in EXCLUDE_EXTS:
        return True
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
    return False

def detect_paths(root_dir: Path) -> list:
    """Scans the root directory to find existing critical paths."""
    found_paths = []

    # 1. Sessions
    for session_name in CRITICAL_PATHS["session_folders"]:
        p = root_dir / session_name
        if p.exists() and p.is_dir():
            found_paths.append(p)

    # 2. Env
    for env_name in CRITICAL_PATHS["env_files"]:
        p = root_dir / env_name
        if p.exists() and p.is_file():
            found_paths.append(p)

    # 3. DB State
    for state_name in CRITICAL_PATHS["state_files"]:
        p = root_dir / state_name
        if p.exists() and p.is_file():
            found_paths.append(p)

    # 4. Data folders
    for data_name in CRITICAL_PATHS["data_folders"]:
        p = root_dir / data_name
        if p.exists() and p.is_dir():
            found_paths.append(p)

    return found_paths

def backup_mode(root_dir: Path, output_file: str = None):
    """Creates a ZIP archive of critical bot state."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not output_file:
        output_file = f"bot_backup_{timestamp}.zip"

    out_path = Path(output_file)

    paths_to_backup = detect_paths(root_dir)
    if not paths_to_backup:
        print("Warning: No critical paths detected. Backup might be empty.")

    print(f"Starting backup to {out_path}...")

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for item in paths_to_backup:
            if is_excluded(item):
                continue

            if item.is_file():
                arcname = item.relative_to(root_dir)
                zipf.write(item, arcname)
                print(f"  Added file: {arcname}")
            elif item.is_dir():
                for root, dirs, files in os.walk(item):
                    # Modify dirs in-place to prune excluded directories
                    dirs[:] = [d for d in dirs if not is_excluded(Path(root) / d)]

                    for file in files:
                        file_path = Path(root) / file
                        if not is_excluded(file_path):
                            arcname = file_path.relative_to(root_dir)
                            zipf.write(file_path, arcname)
                            print(f"  Added file: {arcname}")

    print(f"\n✅ Backup completed successfully: {out_path.absolute()}")

    # Check if session was found
    session_found = any(p.name in CRITICAL_PATHS["session_folders"] for p in paths_to_backup)
    if not session_found:
        print("⚠️  Warning: WhatsApp session folder not detected. You may need to re-scan the QR code if restoring from this backup.")

def restore_mode(root_dir: Path, backup_file: str, auto_confirm: bool = False):
    """Restores bot state from a ZIP archive."""
    backup_path = Path(backup_file)
    if not backup_path.exists() or not backup_path.is_file():
        print(f"❌ Error: Backup file not found at {backup_path}")
        sys.exit(1)

    print(f"Preparing to restore from {backup_path}...")

    # Safety Check: Does session already exist?
    existing_sessions = []
    for session_name in CRITICAL_PATHS["session_folders"]:
        p = root_dir / session_name
        if p.exists():
            existing_sessions.append(p)

    if existing_sessions:
        print("\n⚠️  Safety Check: Existing WhatsApp session(s) detected in current directory:")
        for es in existing_sessions:
            print(f"   - {es}")

        if not auto_confirm:
            ans = input("Do you want to overwrite existing sessions/state? (y/n): ").strip().lower()
            if ans != 'y':
                print("Restore aborted by user.")
                sys.exit(0)

        # Optional auto-backup of current state
        print("Creating automatic pre-restore backup just in case...")
        backup_mode(root_dir, f"pre_restore_auto_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")

    # Extract
    with zipfile.ZipFile(backup_path, 'r') as zipf:
        zipf.extractall(root_dir)

    print(f"\n✅ Restore completed successfully to {root_dir.absolute()}")

    # Optional permission restoration check
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            file_path = Path(root) / file
            # If it's a shell script, make it executable
            if file_path.suffix == '.sh':
                try:
                    os.chmod(file_path, 0o755)
                except Exception:
                    pass

def main():
    parser = argparse.ArgumentParser(description="Portable Backup & Restore System for WhatsApp Bot")
    parser.add_argument("--mode", choices=["backup", "restore"], required=True, help="Mode of operation")
    parser.add_argument("--file", help="Path to the ZIP file (Required for restore, optional for backup override)")
    parser.add_argument("--dir", default=".", help="Root directory of the bot (default: current directory)")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm prompts during restore")

    args = parser.parse_args()

    root_dir = Path(args.dir).resolve()

    if args.mode == "backup":
        backup_mode(root_dir, args.file)
    elif args.mode == "restore":
        if not args.file:
            print("❌ Error: --file argument is required for restore mode.")
            sys.exit(1)
        restore_mode(root_dir, args.file, args.yes)

if __name__ == "__main__":
    main()
