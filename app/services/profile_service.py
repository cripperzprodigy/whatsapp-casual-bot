import json
from pathlib import Path
from typing import Dict, Any
from filelock import FileLock
from app.config import settings

def get_profile_path(chat_id: str) -> Path:
    safe_id = chat_id.replace('@', '_').replace('.', '_')
    contact_dir = Path(f"./data/contacts/{safe_id}")
    contact_dir.mkdir(parents=True, exist_ok=True)
    return contact_dir / "profile.json"

def read_profile(chat_id: str) -> Dict[str, Any]:
    profile_path = get_profile_path(chat_id)
    lock_path = str(profile_path) + ".lock"

    profile = {
        "chatty_status": settings.CHATTY_GROUP_DEFAULT if "@g.us" in chat_id else settings.CHATTY_DEFAULT,
        "chatty_frequency": settings.CHATTY_DEFAULT_FREQUENCY,
        "chatty_burst": settings.CHATTY_DEFAULT_BURST,
        "message_counter": 0,
        "preferred_language": None
    }

    with FileLock(lock_path):
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    saved_profile = json.load(f)
                    profile.update(saved_profile)
            except Exception:
                pass
    return profile

def write_profile(chat_id: str, profile_data: Dict[str, Any]) -> None:
    profile_path = get_profile_path(chat_id)
    lock_path = str(profile_path) + ".lock"
    with FileLock(lock_path):
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, indent=2)
