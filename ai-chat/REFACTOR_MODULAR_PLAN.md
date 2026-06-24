# Refactor Modular Plan: whatsapp-service

## Overview
The `whatsapp-service/index.js` file has grown too large (~600+ lines), handling multiple concerns like client initialization, event registration, session management, recovery logic, queue management, and all HTTP routes. This violates the Modularity constraint and makes recovery logic difficult to reason about.

This plan details the modularization of the gateway into a structured `src/` tree.

## Target Structure
```text
whatsapp-service/
├── index.js                  ← Entry point only (bootstrap, express listen)
├── src/
│   ├── client.js             ← Client factory, initClient(), lock-heal logic
│   ├── events.js             ← registerEvents() — qr, ready, auth_failure, disconnected, message
│   ├── recovery.js           ← Tiered recovery: Tier1/Tier2/Tier3, isSessionCorruptionError()
│   ├── queue.js              ← recoveryMessageQueue, processMessageQueue(), isSettling flag
│   ├── state.js              ← Shared mutable state (isConnected, qrCodeData, metrics)
│   ├── utils/
│   │   ├── jid.js            ← normalizeJid(), resolveWhatsAppId(), isGroupJid()
│   │   └── session.js        ← validateSessionPath(), getSessionState(), purgeLock()
│   └── routes/
│       ├── qr.js             ← GET /whatsapp/qr
│       ├── status.js         ← GET /whatsapp/recovery-status
│       ├── send.js           ← POST /message/sendText  ← primary fix lives here
│       ├── group.js          ← GET /group/findGroupInfos
│       └── session.js        ← POST /whatsapp/reset-session
├── package.json
└── Dockerfile
```

## Module Responsibilities
- `state.js`: Single source of truth for runtime flags (e.g., `isConnected`, `qrCodeData`, `recoveryTier`, `consecutiveFailures`, `isSettling`). It uses a plain mutable object export.
- `utils/jid.js`: All JID normalization in one place, including the new `resolveWhatsAppId()` method which uses `getNumberId` to resolve the LID.
- `utils/session.js`: Session path and lock management (`validateSessionPath`, `purgeStaleLock`).
- `client.js`: Client factory and initialization retry loop (`createClient`, `initClient`).
- `events.js`: All `client.on(...)` registrations (`registerEvents(client)`).
- `recovery.js`: Tier 1/2/3 logic, error pattern matching (`attemptGracefulRecovery`, `isSessionCorruptionError`).
- `queue.js`: Queue drain and settling coordination (`processMessageQueue`).
- `routes/send.js`: The `/message/sendText` handler, applying the `getNumberId` fix.

## Rationale
- Modularity prevents circular dependencies and isolates recovery states.
- Shared `state.js` ensures all components observe the correct connection status.
- Separating routes makes unit-testing HTTP handlers easier.
- Placing the JID/LID logic in a utility function ensures consistent application across routes.
