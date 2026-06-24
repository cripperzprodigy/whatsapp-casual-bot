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
