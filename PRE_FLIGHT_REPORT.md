# Pre-Flight Dependency Installer Report

## Overview
A new standalone bash script, `install_deps.sh`, has been integrated into the bot's deployment workflow to gracefully handle environments where essential OS packages (like `python3.12` and `libsqlite3-dev`) are absent or require complex compilation. This ensures the bot can be installed safely across diverse minimal Linux distributions (such as minimal cloud Oracle VMs on Ubuntu 20.04 to 26.04).

## Features
1. **Automated OS Detection & Fallback Logic:**
   - Dynamically checks OS versions and uses `apt` to install standard toolchains (`build-essential`, `curl`, `wget`, `git`).
   - If apt fails entirely due to dead repositories (e.g., EOL versions), it attempts to rewrite `sources.list` to target `old-releases.ubuntu.com` automatically.
2. **Smart SQLite3 Compilation:**
   - Evaluates if `libsqlite3-dev` is accessible via standard repos. If not, it falls back to downloading the SQLite source tarball, compiling, and installing it manually.
3. **Resilient Python 3.12 Compilation:**
   - Adds `ppa:deadsnakes/ppa` strictly for Ubuntu versions `< 23.10` where `3.12` is not natively available via apt.
   - Installs `python3.12-venv` and `python3.12-dev`.
4. **Validation:**
   - Employs strict exit-code assertions to confirm that `python3.12` successfully loads `import sqlite3` before greenlighting the rest of the application's bootloader sequence.

## Integration
The script is injected directly at the top of the core `start.sh` boot sequence. If `install_deps.sh` encounters an unrecoverable failure, it will print a color-coded error detailing the specific missing packages and halt safely before attempting to manipulate the virtual environments.
