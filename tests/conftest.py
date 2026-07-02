"""
conftest.py — Test environment bootstrap.

Stubs out heavy ML / native packages that are not installed in a lightweight
test environment (chromadb, sentence_transformers, langdetect, pdfplumber, httpx,
etc.) so that unit tests can run without the full dependency stack.

Any test that DOES need the real packages should install them in a full venv
and run without this stub in effect.  The stubs are intentionally minimal —
just enough to allow imports to succeed.
"""

import sys
import types
from unittest.mock import MagicMock


def _make_stub(name: str, **attrs) -> types.ModuleType:
    """Create a minimal module stub and register it in sys.modules."""
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    sys.modules[name] = mod
    return mod


# ── Heavy packages not available in lightweight CI ────────────────────────────

# chromadb
if "chromadb" not in sys.modules:
    _chroma_mod = _make_stub("chromadb")
    _chroma_mod.PersistentClient = MagicMock
    _settings_stub = _make_stub("chromadb.config", Settings=MagicMock)
    _chroma_mod.config = _settings_stub

# sentence_transformers
if "sentence_transformers" not in sys.modules:
    _st_mod = _make_stub("sentence_transformers")
    _st_mod.SentenceTransformer = MagicMock

# langdetect — use the real package if installed (required by test_language_mirroring.py)
# Only stub if the real package is genuinely unavailable.
try:
    import langdetect as _real_langdetect  # noqa: F401  — keeps real pkg in sys.modules
    from langdetect.lang_detect_exception import LangDetectException as _RealLDE  # noqa: F401
except ImportError:
    # Real langdetect not available — create minimal stubs
    _ld_mod = _make_stub(
        "langdetect",
        detect=MagicMock(return_value="en"),
        detect_langs=MagicMock(return_value=[MagicMock(lang="en", prob=0.99)]),
        DetectorFactory=MagicMock(),
    )
    _ld_exc = _make_stub("langdetect.lang_detect_exception")

    class _FakeLangDetectException(Exception):
        pass

    _ld_exc.LangDetectException = _FakeLangDetectException
    _ld_mod.lang_detect_exception = _ld_exc
    sys.modules["langdetect.lang_detect_exception"] = _ld_exc

# pdfplumber
if "pdfplumber" not in sys.modules:
    _make_stub("pdfplumber")

# httpx
if "httpx" not in sys.modules:
    _httpx = _make_stub("httpx")
    _httpx.HTTPError = type("HTTPError", (Exception,), {})
    _httpx.Timeout = MagicMock
    _httpx.Client = MagicMock
    _httpx.AsyncClient = MagicMock

# openai
if "openai" not in sys.modules:
    _openai = _make_stub("openai")
    _openai.AsyncOpenAI = MagicMock
    _openai.OpenAIError = type("OpenAIError", (Exception,), {})
    _make_stub("openai.types")
    _make_stub("openai.types.chat")
    _make_stub("openai.types.chat.chat_completion", ChatCompletion=MagicMock)

# filelock — install if not present (lightweight, usually available)
try:
    import filelock  # noqa: F401
except ImportError:
    _make_stub("filelock", FileLock=MagicMock)
