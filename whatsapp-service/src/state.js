// src/state.js
const state = {
    isConnected: false,
    qrCodeData: null,
    totalMessagesSent: 0,
    lastErrorMessage: null,
    lastSuccessfulSend: null,
    consecutiveFailures: 0,
    isSettling: false,
    recoveryTier: 0,
    sessionLastValidated: Date.now(),
    deletionCountPerHour: 0,
    lastDeletionHour: Math.floor(Date.now() / 3600000)
};

module.exports = state;
