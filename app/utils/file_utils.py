"""
Temporary File Lifecycle Management (Task 4 — Temp File Hygiene).

Every request that needs disk scratch space should use TempFileContext so that
temp artifacts are guaranteed to be wiped when the request completes, whether it
succeeded or raised an exception.

Usage:
    async with TempFileContext("audio") as tmp_dir:
        audio_file = tmp_dir / "clip.ogg"
        ...  # process audio
    # tmp_dir and all contents are deleted here, unconditionally

Startup hygiene:
    Invoke `cleanup_orphaned_temp_dirs()` once at application startup (e.g. in
    app/main.py) to reclaim any /tmp/bot_* directories left by a previous crash.
"""

import asyncio
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Default: orphaned directories older than this many seconds are wiped at startup.
_ORPHAN_MAX_AGE_SECONDS = 3600  # 1 hour


class TempFileContext:
    """Async context manager that creates an isolated per-request temp directory.

    The directory is created under the OS temp folder as::

        <tmpdir>/bot_<uuid>/<prefix>/

    On ``__aexit__`` the *entire* ``bot_<uuid>`` parent is removed with
    ``shutil.rmtree``, regardless of whether the block raised an exception.
    This guarantees zero artifact leakage even on crashes.
    """

    def __init__(self, prefix: str = "") -> None:
        self.request_id: uuid.UUID = uuid.uuid4()
        self._root: Path = Path(tempfile.gettempdir()) / f"bot_{self.request_id}"
        self.path: Path = self._root / prefix if prefix else self._root

    async def __aenter__(self) -> Path:
        await asyncio.to_thread(lambda: self.path.mkdir(parents=True, exist_ok=True))
        logger.debug(f"[TempFileContext] Created temp dir: {self.path}")
        return self.path

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Aggressively wipe the entire bot_<uuid> root, including all sub-paths."""
        try:
            if self._root.exists():
                await asyncio.to_thread(
                    lambda: shutil.rmtree(self._root, ignore_errors=True)
                )
                logger.debug(
                    f"[TempFileContext] Cleaned up temp dir: {self._root}"
                    + (f" (exception: {exc_type.__name__})" if exc_type else "")
                )
        except Exception as cleanup_err:
            # Never let cleanup failure propagate — log and swallow.
            logger.warning(
                f"[TempFileContext] Failed to clean up {self._root}: {cleanup_err}"
            )
        # Return False so any original exception still propagates.
        return False


async def cleanup_orphaned_temp_dirs(max_age_seconds: int = _ORPHAN_MAX_AGE_SECONDS) -> int:
    """Delete any ``/tmp/bot_*`` directories older than *max_age_seconds*.

    Call once at application startup.  Returns the number of directories removed.
    """
    tmp_root = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_seconds
    removed = 0

    def _scan_and_remove() -> int:
        count = 0
        for entry in tmp_root.iterdir():
            if not entry.is_dir():
                continue
            if not entry.name.startswith("bot_"):
                continue
            try:
                mtime = entry.stat().st_mtime
                if mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    logger.info(f"[TempFileCleanup] Removed orphaned dir: {entry}")
                    count += 1
            except OSError:
                pass
        return count

    try:
        removed = await asyncio.to_thread(_scan_and_remove)
    except Exception as e:
        logger.warning(f"[TempFileCleanup] Error during orphan scan: {e}")

    if removed:
        logger.info(f"[TempFileCleanup] Removed {removed} orphaned temp director(ies).")
    return removed
