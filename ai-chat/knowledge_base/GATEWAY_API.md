# Gateway API Reference

This document outlines the internal Node.js Gateway API used by the Python application to interact with `wwebjs`.

## Contact & Participant Lookups

### `GET /participant/info`
Actively resolves a participant's Jabber ID (JID) into their true phone number, bypassing local cache restrictions.

#### Request
- **URL Parameter**: `jid` (e.g., `12345@c.us` or `hash@lid`)

#### Responses

**Success (200 OK)**
Returns the resolved phone number and name.
```json
{
  "success": true,
  "phone": "1234567890",
  "name": "John Doe"
}
```

**Privacy Hidden / Not Found (200 OK)**
Returns if WhatsApp privacy settings block the number resolution.
```json
{
  "success": false,
  "reason": "privacy_hidden_or_not_contact"
}
```

**Missing Parameter (400 Bad Request)**
```json
{
  "error": "Missing jid"
}
```

**Gateway Disconnected (503 Service Unavailable)**
```json
{
  "error": "WhatsApp client not connected"
}
```
