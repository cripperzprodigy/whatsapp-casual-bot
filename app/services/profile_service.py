import json
from pathlib import Path
from typing import Dict, Any
from filelock import FileLock
from app.config import settings

# ── Preference scoping policy (Task 2 — Persona Leak fix) ────────────────────
#
# PERSONA preferences are scoped to (user_id, chat_id).
#   A tone setting configured in a DM is NOT visible in a Group and vice versa.
#
# GLOBAL preferences (e.g. preferred_language) remain per-user and apply
#   everywhere unless overridden by a scoped entry.
#
# Fallback chain for any preference key:
#   1. (user_id, chat_id) scoped file  →  most specific
#   2. (user_id, global) file          →  DM-level / user-level global
#   3. Hard-coded defaults             →  last resort
#
PERSONA_PREFERENCE_KEYS = frozenset({"tone", "emoji_style", "persona", "system_prompt"})
GLOBAL_PREFERENCE_KEYS = frozenset({"preferred_language", "lang_pref"})


def get_profile_path(chat_id: str) -> Path:
    safe_id = chat_id.replace('@', '_').replace('.', '_')
    contact_dir = Path(f"./data/contacts/{safe_id}")
    contact_dir.mkdir(parents=True, exist_ok=True)
    return contact_dir / "profile.json"


# ── Scoped preference helpers ─────────────────────────────────────────────────

def _get_scoped_pref_path(user_id: str, chat_id: str) -> Path:
    """Return path for (user_id, chat_id) scoped preferences file."""
    safe_user = user_id.replace('@', '_').replace('.', '_')
    safe_chat = chat_id.replace('@', '_').replace('.', '_')
    pref_dir = Path(f"./data/prefs/{safe_user}")
    pref_dir.mkdir(parents=True, exist_ok=True)
    return pref_dir / f"{safe_chat}.json"


def _get_global_pref_path(user_id: str) -> Path:
    """Return path for (user_id, global) preferences file."""
    safe_user = user_id.replace('@', '_').replace('.', '_')
    pref_dir = Path(f"./data/prefs/{safe_user}")
    pref_dir.mkdir(parents=True, exist_ok=True)
    return pref_dir / "global.json"


def read_scoped_preferences(user_id: str, chat_id: str) -> Dict[str, Any]:
    """Read preferences scoped to (user_id, chat_id) with global fallback.

    For PERSONA keys the lookup chain is:
        (user_id, chat_id) → empty dict (no DM persona bleeds into group)

    For GLOBAL keys the lookup chain is:
        (user_id, chat_id) → (user_id, global)

    Callers that need the effective value for a single key should use
    ``get_effective_preference()``.
    """
    scoped_path = _get_scoped_pref_path(user_id, chat_id)
    lock_path = str(scoped_path) + ".lock"
    scoped: Dict[str, Any] = {}
    with FileLock(lock_path):
        if scoped_path.exists():
            try:
                with open(scoped_path, "r", encoding="utf-8") as f:
                    scoped = json.load(f)
            except Exception:
                pass
    return scoped


def write_scoped_preference(user_id: str, chat_id: str, key: str, value: Any) -> None:
    """Persist a preference scoped to (user_id, chat_id).

    PERSONA keys are written to the (user_id, chat_id) file.
    GLOBAL keys are written to the (user_id, global) file so they apply everywhere.
    """
    if key in GLOBAL_PREFERENCE_KEYS:
        target_path = _get_global_pref_path(user_id)
    else:
        target_path = _get_scoped_pref_path(user_id, chat_id)

    lock_path = str(target_path) + ".lock"
    with FileLock(lock_path):
        data: Dict[str, Any] = {}
        if target_path.exists():
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data[key] = value
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def get_effective_preference(user_id: str, chat_id: str, key: str, default: Any = None) -> Any:
    """Return the effective value for *key* by walking the fallback chain.

    PERSONA keys: only scoped (user_id, chat_id) is consulted — no cross-chat bleed.
    GLOBAL keys:  (user_id, chat_id) → (user_id, global) → *default*.
    """
    # Check scoped file first
    scoped = read_scoped_preferences(user_id, chat_id)
    if key in scoped:
        return scoped[key]

    # For persona keys: stop here — do NOT fall back to global to prevent persona leak
    if key in PERSONA_PREFERENCE_KEYS:
        return default

    # For global keys: try user-level global file
    global_path = _get_global_pref_path(user_id)
    if global_path.exists():
        lock_path = str(global_path) + ".lock"
        with FileLock(lock_path):
            try:
                with open(global_path, "r", encoding="utf-8") as f:
                    global_data = json.load(f)
                if key in global_data:
                    return global_data[key]
            except Exception:
                pass

    return default

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


from typing import Callable

def update_profile_atomic(chat_id: str, update_func: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
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

        # Perform atomic mutation
        update_func(profile)

        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

    return profile
