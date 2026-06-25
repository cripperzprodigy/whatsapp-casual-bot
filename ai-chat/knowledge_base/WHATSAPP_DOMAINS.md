# WhatsApp Domain Suffixes Knowledge Base

When dealing with WhatsApp APIs and Node gateways, it's critical to understand the various domain suffixes attached to phone numbers and identifiers.

Depending on the underlying gateway architecture (official Cloud API vs. reverse-engineered clients like `whatsapp-web.js`, Baileys, or Evolution API), the suffixes used to route messages vary significantly.

## Known Suffixes

- **`@s.whatsapp.net` (Official Individual User)**
  - This is the actual, official domain suffix WhatsApp servers use for 1-on-1 chats.
  - Required by robust frameworks like Baileys and Evolution API.
  - *Note: Our Python backend strictly uses this official format.*

- **`@c.us` (Unofficial Client User)**
  - An abstraction/alias created by reverse-engineered wrapper libraries (like `whatsapp-web.js`, Venom, WAPP).
  - It resolves equivalently to `@s.whatsapp.net`, but specific API gateways use it to simplify their internal routing trees.
  - *Note: Our Node.js gateway adapter dynamically translates this to `@s.whatsapp.net` before passing data to Python.*

- **`@g.us` (Groups)**
  - The standard suffix for all WhatsApp Group chats.
  - Universally recognized across both official and unofficial APIs.

- **`@broadcast` (Status / Broadcast)**
  - Used for routing WhatsApp Status updates and broadcast lists.

- **`@newsletter` (Channels)**
  - The suffix used for routing messages in WhatsApp Channels (a relatively new addition).

- **`@lid` (Linked Device)**
  - Used internally by WhatsApp for multi-device routing and sync protocols.
  - *Note: Our webhook router explicitly accepts `@lid` suffixes for private Direct Messages to gracefully handle unhydrated multi-device accounts, bypassing the system domain guard rails.*

## Architectural Decision: Adapter Pattern

To maintain a clean and framework-agnostic Python backend, **never leak unofficial suffixes (like `@c.us`) into the Python logic.**

The Node.js gateway (e.g., `whatsapp-service/index.js`) must always function as a pure adapter:
1. **Inbound:** Strip/replace `@c.us` with `@s.whatsapp.net` when emitting JSON payloads to the webhook router.
2. **Outbound:** When receiving commands from the backend, replace `@s.whatsapp.net` with `@c.us` (or whatever the active gateway library demands) immediately before executing the `sendMessage` hook.

## Outbound LID Resolution (getNumberId)
When sending direct messages, raw phone numbers must be converted to fully qualified multi-device IDs using `client.getNumberId()`. Because of the Linked ID (LID) architecture, directly sending to `number@c.us` will throw `No LID for user` if the mapping isn't fully cached in the store.
Group messages (`@g.us`) do not require LID resolution and can be passed to `sendMessage` directly.
