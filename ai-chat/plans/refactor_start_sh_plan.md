# Refactor start.sh for Idempotency and Control Flow Continuity

This plan outlines the steps to refactor `start.sh` into a robust, state-aware service launcher that avoids redundant installations, properly persists environment variables, and ensures seamless startup.

## User Review Required

> [!WARNING]
> This refactoring will restructure the entire `start.sh` execution flow. The interactive `(y/n)` prompts for dependency installation will be automated away in favor of the idempotent "Set and Forget" approach, meaning the script will automatically install missing dependencies without blocking for user input.

## Open Questions

1. **`install_deps.sh` Execution:** Currently, `start.sh` calls `./install_deps.sh` at the very beginning. Should we also skip this pre-flight check if the `.bot_ready_state` marker exists, to ensure lightning-fast startups?
2. **Interactive Prompts:** Should we entirely remove the `(y/n)` interactive prompts for installing OS packages (like `nodejs`, `npm`, and Puppeteer dependencies) if the script detects they are missing during a fresh run, or auto-approve them? (The plan assumes auto-approving or removing the blocking prompts to fulfill the "Set and Forget" constraint).

## Proposed Changes

### [MODIFY] [start.sh](file:///d:/11-github/whatsapp-casual-bot/start.sh)

- **State Marker Logic (`.bot_ready_state`)**:
  - Implement a `check_ready_state()` function at the top of the script.
  - If the marker exists, extract the binary path and verify it using functional tests (`command -v`, `import sys`, `import sqlite3`, `import venv`).
  - If valid, bypass `install_deps.sh` and the Python fallback ladder.

- **Idempotent Pre-Flight & System Checks**:
  - Auto-detect missing Node.js/ffmpeg/Puppeteer dependencies and install them via APT only if they are missing (using `dpkg -l` checks). Remove blocking `read -p` prompts.

- **Control Flow & Compilation Fixes**:
  - Refactor the execution into a clean, linear `main()` function pipeline.
  - Remove all inner `exit` calls from successful compilation paths.
  - Call `hash -r` to refresh the shell cache and export `PYTHON_BIN` globally after a successful source installation.

- **Idempotent Virtual Environment & Pip**:
  - Only create the `venv` if `venv/bin/activate` is missing or the python version doesn't match 3.12.
  - Wrap pip installation in an idempotent check (e.g., `if ! "$PYTHON_BIN" -c "import fastapi" 2>/dev/null; then`).
  - Execute `pip install -q --upgrade-strategy only-if-needed -r requirements.txt` to minimize overhead if new packages are added.

- **Service Startup**:
  - Transition unconditionally to `start_services()` at the end of the script.
  - Implement a graceful `trap` for cleanup of Node and Uvicorn processes.

## Verification Plan

### Automated Tests
- Since this is a bash script dealing with OS-level binaries, automated testing via `pytest` is not applicable.

### Manual Verification
- **Fresh Install**: Delete `venv`, `node_modules`, and `.bot_ready_state`. Verify the script installs everything sequentially without dead-ends.
- **Restart**: Run the script a second time. Verify it hits the marker, skips APT/compilation, skips pip, and boots in under 5 seconds.
- **New Dependency**: Add a dummy package to `requirements.txt`. Verify the script detects it and runs pip, then starts the bot.
- **Invalidated State**: Manually change the path inside `.bot_ready_state` or delete the Python binary. Verify the script falls back to installation.
