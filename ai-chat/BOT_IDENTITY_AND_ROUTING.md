# Bot Identity and Routing Knowledge Base

In most WhatsApp bot projects, the bot's own WhatsApp number is **not "detected" dynamically from messages**. It is usually **configured explicitly** or obtained from the WhatsApp provider/API metadata.

How it's commonly handled depends on the platform you use.

---

## 1. WhatsApp Cloud API / Meta API

For the official WhatsApp Cloud API, your bot is tied to a **Phone Number ID**.

When you receive a webhook message, Meta includes metadata like:

```json
{
  "metadata": {
    "display_phone_number": "15551234567",
    "phone_number_id": "123456789"
  },
  "messages": [
    {
      "from": "6591234567",
      "text": {
        "body": "hello"
      }
    }
  ]
}
```

The important fields are:

- `metadata.display_phone_number` → the bot's WhatsApp number
- `metadata.phone_number_id` → Meta's internal ID for that number
- `messages[0].from` → the user/customer who sent the message

So in most projects, the bot identifies itself using:

```javascript
const botNumber = webhook.entry[0].changes[0].value.metadata.display_phone_number;
const botPhoneNumberId = webhook.entry[0].changes[0].value.metadata.phone_number_id;
```

Most production projects store the bot number or `phone_number_id` in environment variables or a database.

Example:

```env
WHATSAPP_PHONE_NUMBER_ID=123456789
WHATSAPP_DISPLAY_NUMBER=15551234567
```

Then when sending messages, they use:

```http
POST /{WHATSAPP_PHONE_NUMBER_ID}/messages
```

---

## 2. Twilio WhatsApp API

With Twilio, the bot's WhatsApp number is usually sent in the webhook as the `To` field.

Example webhook payload:

```txt
From=whatsapp:+6591234567
To=whatsapp:+14155238886
Body=hello
```

Here:

- `From` = user's WhatsApp number
- `To` = your bot's WhatsApp number

So you can read:

```javascript
const userNumber = req.body.From;
const botNumber = req.body.To;
```

---

## 3. Baileys / whatsapp-web.js / unofficial WhatsApp Web bots

For libraries like:

- `whatsapp-web.js`
- `Baileys`
- `venom-bot`

The bot is logged in as a WhatsApp account. The library usually exposes the logged-in user info.

For example in `whatsapp-web.js`:

```javascript
const client = new Client();

client.on('ready', () => {
  console.log(client.info.wid.user);
});
```

You might get something like:

```txt
6598765432
```

In Baileys, you can access something like:

```javascript
sock.user.id
```

Usually this returns a WhatsApp JID:

```txt
6598765432@s.whatsapp.net
```

You then normalize it to just the phone number:

```javascript
const botNumber = sock.user.id.split('@')[0].split(':')[0];
```

---

## 4. Common production approach

Most projects do **both**:

### Store the bot number in config

```env
BOT_WHATSAPP_NUMBER=6598765432
```

### Also verify it from the provider/webhook

This helps when handling multiple WhatsApp numbers.

Example:

```javascript
const incomingBotNumber = req.body.To || webhook.metadata?.display_phone_number;

if (incomingBotNumber !== process.env.BOT_WHATSAPP_NUMBER) {
  console.warn('Message received for unexpected WhatsApp number');
}
```

---

## 5. Multi-number bots

If one backend handles multiple WhatsApp bots, the bot number or phone number ID is used to route the message.

Example:

```javascript
const phoneNumberId = value.metadata.phone_number_id;

const botConfig = await BotConfig.findOne({
  whatsappPhoneNumberId: phoneNumberId
});

if (!botConfig) {
  throw new Error('Unknown bot number');
}
```

Then each bot can have its own:

- access token
- business profile
- AI prompt
- webhook settings
- database records
- reply rules

---

## Summary

Most projects detect the bot's own WhatsApp number like this:

| Platform | Bot number source |
|---|---|
| WhatsApp Cloud API | `metadata.display_phone_number` or `phone_number_id` |
| Twilio | webhook `To` field |
| whatsapp-web.js | `client.info.wid.user` |
| Baileys | `sock.user.id` |
| Production apps | environment variable or database config |

In general, the safest approach is:

```txt
Use provider metadata to identify the bot number,
but store your expected bot number/ID in config or database.
```

---

## 6. Auto-Sync Bot Number (WhatsApp Casual Bot Specific)

To prevent mention failures due to static configuration mismatches, the bot now features an **auto-sync mechanism**. 

If the environment variable `AUTO_SYNC_BOT_NUMBER` is set to `True`, the `BotIdentityManager` will:
1. Fetch the actual bot identity from the gateway.
2. Compare it with the `BOT_NUMBER` in `.env`.
3. If they differ, automatically update the `.env` file using a safe, file-locked read-modify-write operation.
4. Reload its settings so the new value is immediately active.

### Troubleshooting Identity Mismatches
If you notice the bot is not responding to `@mentions` in group chats:
1. Run the `!botid` command to view the diagnostic status.
2. Check if the "Match status" is "MISMATCH".
3. If mismatched, either manually update `BOT_NUMBER` in `.env` to match the "Detected value" and restart, or set `AUTO_SYNC_BOT_NUMBER=True` in `.env` and restart the bot so it automatically corrects itself.
