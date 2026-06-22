# Python 3.12 LTS Migration & Coexistence Report

## Overview
The application's runtime environment has been successfully refactored to enforce **Python 3.12** as the primary interpreter, ensuring compatibility with the stable CPU ecosystem for PyTorch and LangChain dependencies, without breaking or uninstalling newer system-level Python versions (e.g., Python 3.14).

## 1. Version Pinning Strategy
To achieve absolute stability while removing GPU-bloat, the following core dependencies were pinned against the PyTorch CPU index using `+cpu` tags specifically validated for Python 3.12:
- `torch==2.4.0+cpu`
- `torchvision==0.19.0+cpu`
- `torchaudio==2.4.0+cpu`

*The `--extra-index-url https://download.pytorch.org/whl/cpu` flag ensures `pip` resolves these requests locally before searching global PyPI indices for massive CUDA variants.*

## 2. Boot Script Hardening (`start.sh`)
The `start.sh` boot script has been rewritten to explicitly look for `python3.12` binaries rather than generically resolving `python3`.

**Key Safeguards Added:**
1. **Dependency Check:** Halts execution gracefully with a helpful `apt install` prompt if `python3.12` is not detected alongside the current default version.
2. **Venv Integrity Check:** Dynamically detects if an existing `./venv/` directory was compiled against an outdated or newer Python version (e.g., 3.14). If a version mismatch is found, it automatically deletes and transparently rebuilds the virtual environment using `python3.12`.
3. **No Sudo Requirement:** All Python module installations strictly operate within the virtual environment boundaries.

## 3. Coexistence Verification
This configuration guarantees zero conflict with existing Python binaries. `python3.14` and `python3.12` will coexist peacefully on the host OS, and the bot will cleanly isolate its execution context inside `venv/bin/python`.
