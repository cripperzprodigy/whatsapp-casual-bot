# `start.sh` Architecture Rewrite & Idempotency Refactor

The `start.sh` boot script has been completely refactored from a linear, prompt-heavy installer into a robust, idempotent service launcher.

## Key Changes Made

### 1. The State Marker (`.bot_ready_state`)
The script now writes a state marker containing the verified path to the Python 3.12 binary upon a successful startup. 
- On subsequent runs, it reads this marker and dynamically bypasses the costly APT update, source compilation, and system-level dependency checks, allowing the bot to boot in under 5 seconds.
- The marker is fail-safe: if the Python binary is moved or becomes invalid, the script automatically deletes the marker and gracefully falls back to a full installation.

### 2. Linear Pipeline Architecture (`main()`)
The massive, nested logic blocks have been decoupled into single-responsibility functions:
1. `check_ready_state()`
2. `install_system_deps()`
3. `find_or_install_python()`
4. `verify_python()`
5. `create_venv_and_deps()`
6. `start_services()`

This guarantees that successful installation logically "falls through" to the next step rather than dead-ending or crashing out due to trapped sub-shell variables.

### 3. Automated "Set-and-Forget" Deployment
The manual `(y/n)` prompts for dependency installations have been removed. If a clean VM is detected, the script now assumes authorization to install the exact OS packages required by Puppeteer, FFMpeg, and Node.js. 

### 4. Smart Pip Check
`pip install` is now triggered intelligently using bash modification times:
```bash
if [ "requirements.txt" -nt "$MARKER_FILE" ] || ! venv/bin/python -c "import fastapi" 2>/dev/null; then
    pip install -q --upgrade-strategy only-if-needed -r requirements.txt
```
This ensures that if you edit `requirements.txt` to add a new dependency, the launcher detects the modification and installs the new package automatically upon restart without reinstalling the world.

## AI-CHAT Protocol Compliance
- Updated `ai-chat/chatpad.md` with the execution summary.
- Appended `ai-chat/PROJECT_HISTORY.md` to document the architectural pivot to state-aware deployment.
- Committed and pushed changes to `feature/chatty-rag-memory-5472926423524956172`.
