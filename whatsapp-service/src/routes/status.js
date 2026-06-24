const express = require('express');
const state = require('../state');
const { getSessionState } = require('../utils/session');

const router = express.Router();

router.get('/status', (req, res) => {
    res.json({
        connected: state.isConnected,
        has_qr: !!state.qrCodeData
    });
});

router.get('/connection-info', (req, res) => {
    const { sessionExists, hasSessionFiles } = getSessionState();
    res.json({
        hasSessionFiles: hasSessionFiles,
        isConnected: state.isConnected,
        totalMessagesSent: state.totalMessagesSent,
        lastSuccessfulSend: state.lastSuccessfulSend,
        lastErrorMessage: state.lastErrorMessage,
        consecutiveFailures: state.consecutiveFailures,
        sessionDirectoryExists: sessionExists
    });
});

router.get('/recovery-status', (req, res) => {
    res.json({
        isConnected: state.isConnected,
        recoveryTier: state.recoveryTier,
        consecutiveFailures: state.consecutiveFailures,
        lastErrorMessage: state.lastErrorMessage,
        totalMessagesSent: state.totalMessagesSent,
        lastSuccessfulSend: state.lastSuccessfulSend
    });
});

router.get('/bot-identity', async (req, res) => {
    const { getClient } = require('../client'); // Import client factory dynamically to avoid circular deps or adjust based on existing
    const client = getClient();

    if (!client || !client.info) {
      return res.status(503).json({
        error: 'Client not ready',
        hint: 'WhatsApp client has not authenticated yet'
      });
    }

    try {
      const wid = client.info.wid;
      const bareNumber = wid.user;

      return res.json({
        jid    : wid._serialized,
        number : bareNumber,
        formats: {
          bare      : bareNumber,
          whatsapp  : bareNumber + '@s.whatsapp.net',
          legacy    : bareNumber + '@c.us',
          lid       : bareNumber + '@lid'
        }
      });
    } catch (err) {
      return res.status(500).json({ error: 'Failed to read client identity',
                                    detail: err.message });
    }
});

module.exports = router;
