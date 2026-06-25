# Session Persistence Guide

## Problem
Previously, the WhatsApp session (`.wwebjs_auth`) was being resolved via a relative path, which meant depending on the working directory, the session files could be created in the wrong place and lost on restarts. Furthermore, during a transient failure (e.g. "No LID for user"), the session was overly aggressively purged.

## Solution Architecture
1. **Absolute Pathing:** We now use `path.resolve(__dirname, '.wwebjs_auth')` in `whatsapp-service/index.js` to ensure deterministic session paths regardless of how the Node process is launched.
2. **Safe Pre-Flight Validation:** The gateway performs robust checks on `hasSessionFiles` before concluding a QR code is needed.
3. **Safe Deletion Logic:** We instituted a 30-second wait period, and track deletions per hour (`deletionCountPerHour < 3`) to prevent cascading deletion failures.
4. **Docker Container Persistence:** The `docker-compose.yml` mounts a named volume (`whatsapp_session`) into `/app/.wwebjs_auth` inside the container. This guarantees data survives container restarts safely.

## Deployment Instructions
If you are deploying using Docker Compose:
- Run `docker-compose up -d --build`
- Your session is mapped to a named volume. To delete your session cleanly:
  - `docker-compose down -v`
  - `docker-compose up -d --build`

If you are running the `start.sh` or `start.bat` script, no action is needed. The `whatsapp-service/` directory will safely store `.wwebjs_auth` within itself using the absolute path rules.
