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

module.exports = router;
