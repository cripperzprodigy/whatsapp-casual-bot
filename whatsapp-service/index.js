const { Client, LocalAuth } = require('whatsapp-web.js');
const express = require('express');
const qrcode = require('qrcode');
const axios = require('axios');
const fs = require('fs');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;
const PYTHON_WEBHOOK_URL = process.env.PYTHON_WEBHOOK_URL || 'http://localhost:8000/webhook/whatsapp';
const SESSION_PATH = process.env.WHATSAPP_SESSION_PATH || './.wwebjs_auth';

let qrCodeData = null;
let isConnected = false;

// Initialize WhatsApp Client with local session persistence
let client;

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
        isConnected = false;
        qrCodeData = null;
    });

    client.on('disconnected', (reason) => {
        console.log('WhatsApp was disconnected:', reason);
        isConnected = false;
        qrCodeData = null;
    });

    client.on('message', async msg => {
        // Forward incoming messages to Python FastAPI backend
        try {
            const chat = await msg.getChat();
            const contact = await msg.getContact();
            
            const payload = {
                event: 'messages.upsert',
                data: {
                    key: {
                        remoteJid: msg.from,
                        fromMe: msg.fromMe,
                        id: msg.id.id,
                        participant: chat.isGroup ? msg.author : null
                    },
                    message: {
                        conversation: msg.body
                    },
                    pushName: contact.pushname || contact.name || "Unknown"
                }
            };
            
            await axios.post(PYTHON_WEBHOOK_URL, payload);
        } catch (error) {
            console.error('Error forwarding message to Python backend:', error.message);
        }
    });

    client.initialize();
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

// 4. Send Message (Internal API for Python)
app.post('/message/sendText', async (req, res) => {
    if (!isConnected) {
        return res.status(503).json({ error: 'WhatsApp client not connected' });
    }
    
    const { number, textMessage } = req.body;
    if (!number || !textMessage || !textMessage.text) {
        return res.status(400).json({ error: 'Missing number or text' });
    }

    try {
        // whatsapp-web.js requires the id format `number@c.us` or `number@g.us`
        await client.sendMessage(number, textMessage.text);
        res.json({ status: 'ok' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
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
                id: p.id._serialized,
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
