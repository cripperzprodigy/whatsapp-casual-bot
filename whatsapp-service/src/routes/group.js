const express = require('express');
const state = require('../state');
const { getClient } = require('../client');

const router = express.Router();

router.get('/findGroupInfos', async (req, res) => {
    if (!state.isConnected) {
        return res.status(503).json({ error: 'WhatsApp client not connected' });
    }

    const { groupJid } = req.query;
    if (!groupJid) {
        return res.status(400).json({ error: 'Missing groupJid' });
    }

    try {
        const client = getClient();
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

module.exports = router;
