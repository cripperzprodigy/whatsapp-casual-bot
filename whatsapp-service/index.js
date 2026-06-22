const { Client, LocalAuth } = require('whatsapp-web.js');
const express = require('express');
const qrcode = require('qrcode');
const axios = require('axios');
const fs = require('fs');

const app = express();
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

const PORT = process.env.PORT || 3000;
const PYTHON_WEBHOOK_URL = process.env.PYTHON_WEBHOOK_URL || 'http://localhost:8000/webhook/whatsapp';
const SESSION_PATH = process.env.WHATSAPP_SESSION_PATH || './.wwebjs_auth';

let qrCodeData = null;
let isConnected = false;

// Connection Metrics
let totalMessagesSent = 0;
let lastErrorMessage = null;
let lastSuccessfulSend = null;
let consecutiveFailures = 0;

// Initialize WhatsApp Client with local session persistence
let client;

// Message Queue for Recovering State
let recoveryMessageQueue = [];

function initClient() {
    client = new Client({
        authStrategy: new LocalAuth({ dataPath: SESSION_PATH }),
        puppeteer: { 
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox'] 
        }
    });

    client.on('qr', (qr) => {
        console.log('QR RECEIVED. Scan it at http://localhost:' + PORT + '/whatsapp/qr');
        qrCodeData = qr;
        isConnected = false;
    });

    client.on('ready', () => {
        console.log('WhatsApp Client is ready!');
        qrCodeData = null;
        isConnected = true;
    });

    client.on('authenticated', () => {
        console.log('WhatsApp Authenticated');
        isConnected = true;
    });

    client.on('auth_failure', msg => {
        console.error('AUTHENTICATION FAILURE', msg);
        console.log(`Connection state changed to disconnected (isConnected=false). Reason: AUTH_FAILURE`);
        isConnected = false;
        qrCodeData = null;
    });

    client.on('disconnected', (reason) => {
        console.log('WhatsApp was disconnected:', reason);
        console.log(`Connection state changed to disconnected (isConnected=false). Reason: ${reason}`);
        isConnected = false;
        qrCodeData = null;
    });

    client.on('message', async msg => {
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

            const payload = {
                event: 'messages.upsert',
                instance: 'whatsapp-web-js', // Issue 1: populate instance for Python schema
                // JID Normalization: Convert @c.us (unofficial web.js suffix) and @lid (linked device suffix)
                // to the official @s.whatsapp.net. This ensures the Python backend sees standardized JIDs.
                // Linked device messages (from connected devices, not system messages) are legitimate user communications
                // and must be normalized so the Python guard rail can distinguish them from true @lid system domains.
                data: {
                    key: {
                        remoteJid: msg.from.replace(/@c\.us$/, '@s.whatsapp.net').replace(/@lid$/, '@s.whatsapp.net'),
                        fromMe: msg.fromMe,
                        id: msg.id.id,
                        participant: (chat.isGroup && msg.author) ? msg.author.replace(/@c\.us$/, '@s.whatsapp.net').replace(/@lid$/, '@s.whatsapp.net') : null
                    },
                    message: {
                        conversation: msg.body,
                        extendedTextMessage: {
                            text: msg.body,
                            contextInfo: {
                                mentionedJid: msg.mentionedIds ? msg.mentionedIds.map(id => id.replace(/@c\.us$/, '@s.whatsapp.net').replace(/@lid$/, '@s.whatsapp.net')) : []
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

    try {
        client.initialize();
    } catch (err) {
        console.error("Failed to initialize WhatsApp client:", err);
    }
}

initClient();

// API ENDPOINTS

// 1. Get QR Code HTML Page
app.get('/whatsapp/qr', async (req, res) => {
    if (isConnected) {
        return res.send('<h2>WhatsApp is already connected. Session active.</h2>');
    }
    if (!qrCodeData) {
        return res.send('<h2>Waiting for QR code generation. Please refresh in a few seconds...</h2>');
    }
    try {
        const url = await qrcode.toDataURL(qrCodeData);
        res.send(`
            <html>
                <head><title>Link WhatsApp</title></head>
                <body style="display:flex;flex-direction:column;align-items:center;margin-top:50px;font-family:sans-serif;">
                    <h2>Scan this QR code with your WhatsApp App</h2>
                    <p>Go to WhatsApp -> Linked Devices -> Link a Device</p>
                    <img src="${url}" style="width:300px;height:300px;border:1px solid #ccc;padding:10px;" />
                    <script>
                        setInterval(() => window.location.reload(), 10000);
                    </script>
                </body>
            </html>
        `);
    } catch (err) {
        res.status(500).send('Error generating QR code image');
    }
});

// 2. Status Check
app.get('/whatsapp/status', (req, res) => {
    res.json({
        connected: isConnected,
        has_qr: !!qrCodeData
    });
});

// 2b. Connection Info
app.get('/whatsapp/connection-info', (req, res) => {
    const sessionExists = fs.existsSync(SESSION_PATH);
    res.json({
        isConnected: isConnected,
        totalMessagesSent: totalMessagesSent,
        lastSuccessfulSend: lastSuccessfulSend,
        lastErrorMessage: lastErrorMessage,
        consecutiveFailures: consecutiveFailures,
        sessionDirectoryExists: sessionExists
    });
});

// 3. Reset Session
app.post('/whatsapp/reset-session', async (req, res) => {
    console.log('Resetting WhatsApp session...');
    try {
        await client.destroy();
        fs.rmSync(SESSION_PATH, { recursive: true, force: true });
        qrCodeData = null;
        isConnected = false;
        initClient(); // Restart client to generate new QR
        res.json({ status: 'ok', message: 'Session cleared. Wait a moment and fetch a new QR.' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Recovery tiers: 1=Restart Puppeteer, 2=Reinitialize Client, 3=Delete Session (last resort)
let recoveryTier = 0;
function isSessionCorruptionError(errMessage) {
    return errMessage && (
        errMessage.includes('No LID') ||
        errMessage.includes('session') ||
        errMessage.includes('corrupt') ||
        errMessage.includes('invalid') ||
        errMessage.includes('ExecutionContext')
    );
}

async function attemptGracefulRecovery() {
    recoveryTier++;
    
    if (recoveryTier === 1) {
        // Tier 1: Restart Puppeteer context without destroying session
        console.log('Recovery Tier 1: Attempting Puppeteer context restart...');
        try {
            const page = client.pupPage; // Access underlying Puppeteer page
            await page.reload({ waitUntil: 'networkidle0', timeout: 30000 });
            await new Promise(resolve => setTimeout(resolve, 3000));
            console.log('Tier 1 recovery successful');
            return true;
        } catch (tier1Err) {
            console.error('Tier 1 recovery failed:', tier1Err.message);
            return false;
        }
    }
    
    if (recoveryTier === 2) {
        // Tier 2: Reinitialize client WITHOUT deleting session
        console.log('Recovery Tier 2: Reinitializing client (preserving session)...');
        try {
            await client.destroy();
            await new Promise(resolve => setTimeout(resolve, 2000));
            initClient(); // Reuses existing session
            await new Promise(resolve => setTimeout(resolve, 5000));
            console.log('Tier 2 recovery successful');
            return true;
        } catch (tier2Err) {
            console.error('Tier 2 recovery failed:', tier2Err.message);
            return false;
        }
    }
    
    if (recoveryTier >= 3) {
        // Tier 3: Nuclear option - delete session and force QR scan
        console.log('Recovery Tier 3: Deleting session (last resort)...');
        try {
            await client.destroy();
            fs.rmSync(SESSION_PATH, { recursive: true, force: true });
            recoveryTier = 0; // Reset for fresh start
            await new Promise(resolve => setTimeout(resolve, 1000));
            initClient();
            return false; // Requires QR scan
        } catch (tier3Err) {
            console.error('Tier 3 recovery failed:', tier3Err.message);
            return false;
        }
    }
}

// 4. Send Message (Internal API for Python)
// Process the message queue when connection is restored
async function processMessageQueue() {
    if (recoveryMessageQueue.length === 0 || !isConnected || recoveryTier > 0) return;

    console.log(`Processing ${recoveryMessageQueue.length} queued messages...`);
    const queueToProcess = [...recoveryMessageQueue];
    recoveryMessageQueue = []; // Clear queue before processing

    for (const msg of queueToProcess) {
        try {
            await axios.post(`http://localhost:${PORT}/message/sendText`, msg);
            await new Promise(resolve => setTimeout(resolve, 1000)); // Rate limit processing
        } catch (err) {
            console.error('Failed to send queued message:', err.message);
        }
    }
}

app.post('/message/sendText', async (req, res) => {
    // validateSession() pre-flight check
    const isSessionValid = client && client.info && client.info.wid && client.pupPage && !client.pupPage.isClosed();

    if (!isSessionValid) {
        console.error('validateSession() pre-flight check failed. Session state is invalid.');
        // Trigger recovery if not already recovering?
        if (recoveryTier === 0) {
            attemptGracefulRecovery().then(processMessageQueue).catch(err => console.error("Async recovery failed", err));
        }
        return res.status(503).json({
            status: "error",
            error_code: "SESSION_CORRUPT",
            error: "Session is corrupt, context undefined",
            requires_qr: recoveryTier >= 3
        });
    }

    // Check if recovery is needed BEFORE attempting send
    if (!isConnected || consecutiveFailures >= 3 || recoveryTier > 0) {
        console.error('Pre-send check: WhatsApp not connected, high failure rate, or recovering. Queuing...');

        recoveryMessageQueue.push(req.body);

        if (recoveryTier === 0) {
            attemptGracefulRecovery().then(processMessageQueue).catch(err => console.error("Async recovery failed", err));
        }
        return res.status(202).json({
            status: "queued",
            error_code: "QUEUED_FOR_RECOVERY",
            message: "Gateway is recovering, message queued."
        });
    }
    
    const { number, textMessage, options } = req.body;
    if (!number || !textMessage || typeof textMessage.text !== 'string' || textMessage.text.trim() === '') {
        return res.status(400).json({ error: 'Missing number or valid text' });
    }

    try {
        let sendOptions = {};
        
        // If a reply message ID was provided, pass it to whatsapp-web.js
        // so it natively quotes the original message.
        if (options && options.quoted) {
            // whatsapp-web.js uses the 'quotedMessageId' option for this
            sendOptions.quotedMessageId = options.quoted;
        }

        let wwebjsNumber;
        if (number.endsWith('@g.us')) {
            // Groups keep their @g.us suffix (whatsapp-web.js accepts this)
            wwebjsNumber = number;
        } else if (number.endsWith('@s.whatsapp.net')) {
            // DMs need conversion from official to unofficial suffix
            wwebjsNumber = number.replace('@s.whatsapp.net', '@c.us');
        } else {
            // Already in whatsapp-web.js format or invalid
            wwebjsNumber = number;
        }

        // Optional validation (only for DMs):
        if (!number.endsWith('@g.us') && !wwebjsNumber.match(/^\d+@c\.us$/)) {
            console.error(`Invalid JID format after conversion: ${wwebjsNumber}, original: ${number}`);
            return res.status(400).json({ error: `Invalid recipient format: ${number}` });
        }

        const trimmedText = textMessage.text.trim();
        console.log(`Sending message to: ${wwebjsNumber}, Length: ${trimmedText.length}`);

        const maxRetries = 2;
        let attempt = 0;
        let success = false;
        let lastErr = null;

        while (attempt <= maxRetries && !success) {
            try {
                const sendPromise = client.sendMessage(wwebjsNumber, trimmedText, sendOptions);
                let timeoutId;
                const timeoutPromise = new Promise((_, reject) => {
                    timeoutId = setTimeout(() => reject(new Error('sendMessage timed out after 10 seconds')), 10000);
                });

                await Promise.race([sendPromise, timeoutPromise]);
                clearTimeout(timeoutId);
                success = true;
                recoveryTier = 0; // Reset on success
            } catch (err) {
                lastErr = err;
                
                // Detect session corruption
                if (isSessionCorruptionError(err.message)) {
                    console.error(`Session corruption detected (attempt ${attempt + 1}): "${err.message}". Initiating graceful recovery...`);
                    
                    // Attempt recovery immediately
                    const recovered = await attemptGracefulRecovery();
                    
                    if (recovered) {
                        console.log('Recovery successful, retrying message send...');
                        attempt++; // Allow one more retry after recovery
                        await new Promise(resolve => setTimeout(resolve, 3000));
                        continue;
                    } else if (recoveryTier >= 3) {
                        // Tier 3 reached, requires QR scan
                        break;
                    }
                }
                
                attempt++;
                if (attempt <= maxRetries) {
                    console.log(`Attempt ${attempt} failed. Retrying in 2 seconds...`);
                    await new Promise(resolve => setTimeout(resolve, 2000));
                }
            }
        }

        if (!success) {
            throw lastErr;
        }

        // Update connection metrics on success
        totalMessagesSent++;
        lastSuccessfulSend = new Date().toISOString();
        lastErrorMessage = null;
        consecutiveFailures = 0;

        // Ensure any remaining queued messages are processed
        if (recoveryMessageQueue.length > 0) {
            processMessageQueue();
        }

        res.json({ status: 'ok' });
    } catch (err) {
        console.error("Error sending message. Details:", err);
        console.error("Stack trace:", err.stack);
        console.error("Request payload:", { number, textMessageLength: textMessage.text ? textMessage.text.length : 0, options });
        lastErrorMessage = err.message;
        
        // Only increment if NOT a session corruption error (those are handled separately)
        if (!isSessionCorruptionError(err.message)) {
            consecutiveFailures++;
        }
        // Determine if QR scan is required
        const requiresQr = recoveryTier >= 3 || !isConnected;
        
        res.status(requiresQr ? 503 : 500).json({
            status: "error",
            error_code: isSessionCorruptionError(err.message) ? "SESSION_CORRUPT" : "SEND_TIMEOUT",
            error: err.message,
            stack: err.name === 'TimeoutError' ? undefined : err.stack,
            name: err.name,
            requires_qr: requiresQr,
            recovery_tier: recoveryTier
        });
    }
});

// 5b. Recovery Status
app.get('/whatsapp/recovery-status', (req, res) => {
    res.json({
        isConnected: isConnected,
        recoveryTier: recoveryTier,
        consecutiveFailures: consecutiveFailures,
        lastErrorMessage: lastErrorMessage,
        totalMessagesSent: totalMessagesSent,
        lastSuccessfulSend: lastSuccessfulSend
    });
});

// 5. Fetch Group Metadata (Internal API for Python)
app.get('/group/findGroupInfos', async (req, res) => {
    if (!isConnected) {
        return res.status(503).json({ error: 'WhatsApp client not connected' });
    }
    
    const { groupJid } = req.query;
    if (!groupJid) {
        return res.status(400).json({ error: 'Missing groupJid' });
    }

    try {
        const chat = await client.getChatById(groupJid);
        if (!chat.isGroup) {
            return res.status(400).json({ error: 'Not a group' });
        }
        
        // Map to format Python expects
        const mappedInfo = {
            subject: chat.name,
            participants: chat.participants.map(p => ({
                id: p.id._serialized.replace('@c.us', '@s.whatsapp.net'),
                admin: p.isAdmin ? 'admin' : (p.isSuperAdmin ? 'superadmin' : null)
            }))
        };
        
        res.json(mappedInfo);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.listen(PORT, () => {
    console.log(`Internal WhatsApp Gateway running on port ${PORT}`);
});
