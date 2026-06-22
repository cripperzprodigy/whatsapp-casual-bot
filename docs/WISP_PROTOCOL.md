# WhatsApp Inter-Service Protocol (WISP)

## 1. Overview
The WhatsApp Inter-Service Protocol (WISP) is a standardized JSON-based communication contract between the Python Backend and the Node.js WhatsApp Gateway. It ensures strict schema validation, predictable error propagation, and state visibility, solving implicit crashes caused by session corruption.

## 2. Gateway State Machine
The Node.js Gateway operates in one of three strict states:
*   **CONNECTED**: The session is active, Puppeteer is stable, and `sendMessage` attempts are permitted.
*   **RECOVERING**: The session encountered a transient error (e.g., `No LID for user`) and is executing tiered recovery. Messages sent during this state are acknowledged with `202 Accepted` and queued.
*   **DISCONNECTED**: The session is corrupted beyond automated recovery, or a QR scan is required. Messages sent during this state return `503 Service Unavailable`.

## 3. JSON Schemas

### 3.1. OutboundMessageRequest (Python -> Node)
```json
{
  "number": "628123456789@s.whatsapp.net",
  "textMessage": {
    "text": "Hello world"
  },
  "options": {
    "quoted": "false_628123456789@s.whatsapp.net_1234567890"
  }
}
```

### 3.2. DeliveryResponse (Node -> Python)
**Success (200 OK)**
```json
{
  "status": "ok",
  "message_id": "true_628123456789@c.us_0987654321"
}
```

**Queued (202 Accepted)**
```json
{
  "status": "queued",
  "error_code": "QUEUED_FOR_RECOVERY",
  "message": "Gateway is recovering, message queued."
}
```

**Failure (503 Service Unavailable / 500 Internal Server Error)**
```json
{
  "status": "error",
  "error_code": "SESSION_CORRUPT",
  "error": "Cannot read properties of undefined (reading 'getChat')",
  "requires_qr": true,
  "recovery_tier": 3
}
```

### 3.3. SessionStateWebhook (Node -> Python, Async)
(Future enhancement, currently state is inferred via responses and `/whatsapp/recovery-status`)

### 3.4. HealthCheckResponse (Node -> Python)
```json
{
  "isConnected": true,
  "recoveryTier": 0,
  "consecutiveFailures": 0,
  "lastErrorMessage": null,
  "totalMessagesSent": 150,
  "lastSuccessfulSend": "2023-10-25T12:00:00Z"
}
```

## 4. Error Codes (Enum)
*   `SESSION_CORRUPT`: Unrecoverable session state, Puppeteer context lost.
*   `RATE_LIMITED`: Too many messages sent in a short period.
*   `INVALID_JID`: The provided phone number or group ID is malformed.
*   `QUEUED_FOR_RECOVERY`: Message accepted but delayed due to ongoing tiered recovery.
*   `SEND_OK`: Message successfully delivered to WhatsApp.
*   `SEND_TIMEOUT`: Timeout while attempting to send.
