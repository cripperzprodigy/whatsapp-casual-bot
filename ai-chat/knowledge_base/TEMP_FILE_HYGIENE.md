# Temp File Hygiene — Per-Request Isolation

> **Status:** Active
> **Files:** `app/utils/file_utils.py`

---

## Overview

All temporary files (audio clips, images, PDFs) must be handled via `TempFileContext`. This async context manager creates an isolated per-request directory and **unconditionally wipes it on exit** — whether the request succeeded or raised an exception. No artifact leakage.

---

## Usage

```python
from app.utils.file_utils import TempFileContext

async def process_audio(data: bytes) -> str:
    async with TempFileContext("audio") as tmp_dir:
        audio_file = tmp_dir / "clip.ogg"
        audio_file.write_bytes(data)
        result = await transcribe(audio_file)
    # /tmp/bot_{uuid}/audio/ and ALL contents are deleted here, unconditionally
    return result
```

---

## Directory Structure

```
/tmp/
└── bot_{uuid4}/           ← unique per request
    └── {prefix}/          ← e.g. "audio", "image", "pdf"
        └── ...            ← temp files created inside
```

The **entire** `bot_{uuid4}/` root is removed on `__aexit__`, not just the prefix subdirectory.

---

## Cleanup on Exception

```python
async with TempFileContext("image") as tmp_dir:
    img_path = tmp_dir / "photo.jpg"
    img_path.write_bytes(image_bytes)
    raise ValueError("processing failed")
# ↑ ValueError re-raises
# ↓ /tmp/bot_{uuid}/ is still deleted — guaranteed
```

The `__aexit__` method returns `False` so the original exception propagates normally.

---

## Startup Orphan Cleanup

A startup job removes any `bot_*` directories in the OS temp folder that are older than 1 hour (left by a previous crash):

```python
# In app/main.py startup:
from app.utils.file_utils import cleanup_orphaned_temp_dirs
removed = await cleanup_orphaned_temp_dirs(max_age_seconds=3600)
```

Override the threshold via the `max_age_seconds` parameter. `cleanup_orphaned_temp_dirs` is non-destructive for recent directories and safe to call on every startup.

---

## SOP Compliance

Per **SOP.md** constraints:
- All temporary media (audio, image, PDF) **must** use `TempFileContext`.
- Raw `tempfile.mkdtemp()` or `/tmp/` paths without context management are **prohibited** for request-scoped data.
- `cleanup_orphaned_temp_dirs()` must be registered in `main.py` startup.
