const express = require('express');
const { initClient, getClient } = require('./src/client');

// Import routers
const qrRouter = require('./src/routes/qr');
const statusRouter = require('./src/routes/status');
const sessionRouter = require('./src/routes/session');
const groupRouter = require('./src/routes/group');
const sendRouter = require('./src/routes/send');

const app = express();
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

const PORT = process.env.PORT || 3000;

// Register routes
app.use('/whatsapp', qrRouter);
app.use('/whatsapp', statusRouter);
app.use('/whatsapp', sessionRouter);
app.use('/group', groupRouter);
app.use('/message', sendRouter);

app.get('/participant/info', async (req, res) => {
    const { jid } = req.query;
    if (!jid) return res.status(400).json({ error: 'Missing jid' });
    
    try {
        const client = getClient();
        if (!client) return res.status(503).json({ error: 'WhatsApp client not connected' });

        // Attempt to resolve number
        const contact = await client.getContactById(jid);
        if (contact && contact.number) {
            return res.json({ success: true, phone: contact.number, name: contact.name || contact.pushname });
        }
        
        // Fallback: try getNumberId
        const numberId = await client.getNumberId(jid.split('@')[0]);
        if (numberId) {
            return res.json({ success: true, phone: numberId.user, name: contact ? contact.name : undefined });
        }
        
        return res.json({ success: false, reason: 'privacy_hidden_or_not_contact' });
    } catch (e) {
        console.error('Resolve error:', e);
        return res.json({ success: false, reason: 'lookup_failed' });
    }
});
// Graceful Shutdown
const shutdown = async () => {
    console.log('Shutting down gracefully...');
    const client = getClient();
    if (client) {
        try {
            await client.destroy();
            console.log('WhatsApp client destroyed.');
        } catch (e) {
            console.error('Error destroying client:', e.message);
        }
    }
    process.exit(0);
};

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

async function main() {
    await initClient();
    
    app.listen(PORT, () => {
        console.log(`🌐 HTTP server listening on port ${PORT}`);
    });
}

main().catch(err => {
    console.error('Failed to start application:', err);
    process.exit(1);
});
