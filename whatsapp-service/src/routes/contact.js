const express = require('express');
const state = require('../state');
const { getClient } = require('../client');

const router = express.Router();

router.get('/info', async (req, res) => {
    if (!state.isConnected) {
        return res.status(503).json({ error: 'WhatsApp client not connected' });
    }

    const { jid } = req.query;
    if (!jid) {
        return res.status(400).json({ error: 'Missing jid' });
    }

    try {
        const client = getClient();
        const contact = await client.getContactById(jid);
        if (!contact) {
            return res.status(404).json({ error: 'Contact not found' });
        }

        res.json({
            jid: contact.id._serialized,
            phone: contact.number,
            name: contact.name || contact.pushname,
            isBusiness: contact.isBusiness,
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

module.exports = router;
