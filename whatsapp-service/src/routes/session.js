const express = require('express');
const fs = require('fs');
const state = require('../state');
const { SESSION_PATH } = require('../utils/session');
const { getClient, initClient } = require('../client');

const router = express.Router();

router.post('/reset-session', async (req, res) => {
    console.log('Resetting WhatsApp session...');
    try {
        const client = getClient();
        if (client) {
            await client.destroy();
        }
        fs.rmSync(SESSION_PATH, { recursive: true, force: true });
        state.qrCodeData = null;
        state.isConnected = false;
        initClient(); // Restart client to generate new QR
        res.json({ status: 'ok', message: 'Session cleared. Wait a moment and fetch a new QR.' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

module.exports = router;
