const axios = require('axios');
const state = require('./state');
const { processMessageQueue } = require('./queue');

const PORT = process.env.PORT || 3000;
const PYTHON_WEBHOOK_URL = process.env.PYTHON_WEBHOOK_URL || 'http://localhost:8000/webhook/whatsapp';

const messageCache = new Map();
const MAX_CACHE_SIZE = parseInt(process.env.WHATSAPP_CACHE_MAX_SIZE) || 5000;
const CACHE_TTL = parseInt(process.env.WHATSAPP_CACHE_TTL_SECONDS) || 300;

function registerEvents(client) {
    client.on('qr', (qr) => {
        console.log('QR RECEIVED. Scan it at http://localhost:' + PORT + '/whatsapp/qr');
        state.qrCodeData = qr;
        state.isConnected = false;
    });

    client.on('ready', () => {
        console.log('WhatsApp Client is ready!');
        state.qrCodeData = null;
        state.isConnected = true;
        state.recoveryTier = 0;
        state.consecutiveFailures = 0;
        state.isSettling = true;
        console.log('⏳ Client ready. Entering 4.5s settling period for store hydration...');
        setTimeout(async () => {
            state.isSettling = false;
            console.log('✅ Settling complete. Stores hydrated. Processing queue...');
            await processMessageQueue();
        }, 4500);
    });

    client.on('authenticated', () => {
        console.log('WhatsApp Authenticated');
        console.log('Session restored successfully');
        state.isConnected = true;
    });

    client.on('auth_failure', msg => {
        console.error('AUTHENTICATION FAILURE', msg);
        console.log('Session corrupt - will require QR scan');
        console.log(`Connection state changed to disconnected (isConnected=false). Reason: AUTH_FAILURE`);
        state.isConnected = false;
        state.qrCodeData = null;
    });

    client.on('disconnected', (reason) => {
        console.log('WhatsApp was disconnected:', reason);
        console.log(`Connection state changed to disconnected (isConnected=false). Reason: ${reason}`);
        state.isConnected = false;
        state.qrCodeData = null;
    });

    client.on('message', async msg => {
        // Store mapping: Short Key ID -> Correct Quote ID format
        if (msg.id && msg.id.id && msg.id.remote) {
            const correctQuoteId = msg.id._serialized || `false_${msg.id.remote}_${msg.id.id}`;
            messageCache.set(msg.id.id, correctQuoteId);
            console.log(`[Cache] Storing short ID: ${msg.id.id} -> ${correctQuoteId}`);
            
            // TTL Cleanup
            setTimeout(() => {
                if (messageCache.get(msg.id.id) === correctQuoteId) {
                    messageCache.delete(msg.id.id);
                    console.log(`[Cache] TTL Expired for ${msg.id.id}`);
                }
            }, CACHE_TTL * 1000);

            // Size Limit Cleanup
            if (messageCache.size > MAX_CACHE_SIZE) {
                const firstKey = messageCache.keys().next().value;
                messageCache.delete(firstKey);
            }
        }

        // Forward incoming messages to Python FastAPI backend
        try {
            if (!client.info || !client.pupPage || client.pupPage.isClosed()) {
                console.error('Session state is invalid, ignoring incoming message to prevent getChat error.');
                return;
            }

            const chat = await msg.getChat();
            const contact = await msg.getContact();

            let mediaData = null;
            if (msg.hasMedia) {
                try {
                    const media = await msg.downloadMedia();
                    if (media) {
                        mediaData = {
                            mimetype: media.mimetype,
                            data: media.data,
                            filename: media.filename || (media.mimetype.split('/')[1] ? `media.${media.mimetype.split('/')[1]}` : 'media.bin')
                        };
                    }
                } catch (mediaErr) {
                    console.error('Failed to download media for message:', msg.id.id, mediaErr.message);
                }
            }

            let quotedMsgPayload = null;
            let quotedParticipant = null;
            if (msg.hasQuotedMsg) {
                try {
                    const qMsg = await msg.getQuotedMessage();
                    if (qMsg) {
                        quotedParticipant = (qMsg.author || qMsg.from || '').replace(/@c\.us$/, '@s.whatsapp.net');
                        quotedMsgPayload = {
                            conversation: qMsg.body
                        };
                    }
                } catch (e) {
                    console.error('Failed to get quoted message:', e);
                }
            }

            const payload = {
                event: 'messages.upsert',
                instance: 'whatsapp-web-js',
                data: {
                    key: {
                        // Normalize unofficial @c.us suffix to official @s.whatsapp.net.
                        // Do NOT transform @lid entries — they are LID tokens and
                        // must be preserved as-is for accurate reply routing.
                        remoteJid: msg.from.replace(/@c\.us$/, '@s.whatsapp.net'),
                        fromMe: msg.fromMe,
                        id: msg.id.id,
                        participant: (chat.isGroup && msg.author) ? msg.author.replace(/@c\.us$/, '@s.whatsapp.net') : null
                    },
                    message: {
                        conversation: msg.body,
                        extendedTextMessage: {
                            text: msg.body,
                            contextInfo: {
                                // Normalize only @c.us entries; preserve @lid tokens
                                mentionedJid: msg.mentionedIds ? msg.mentionedIds.map(id => id.replace(/@c\.us$/, '@s.whatsapp.net')) : [],
                                ...(quotedMsgPayload ? { quotedMessage: quotedMsgPayload, participant: quotedParticipant } : {})
                            }
                        }
                    },
                    pushName: contact.pushname || contact.name || "Unknown",
                    media_data: mediaData
                }
            };

            // Need to increase payload limits in express and axios if sending base64 files.
            await axios.post(PYTHON_WEBHOOK_URL, payload, { maxBodyLength: Infinity, maxContentLength: Infinity });
        } catch (error) {
            console.error('Error forwarding message to Python backend:', error.message);
        }
    });
}

module.exports = {
    registerEvents,
    messageCache
};
