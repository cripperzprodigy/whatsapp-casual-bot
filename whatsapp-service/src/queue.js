const axios = require('axios');
const state = require('./state');
const PORT = process.env.PORT || 3000;

const recoveryMessageQueue = [];

async function processMessageQueue() {
    if (state.isSettling || !state.isConnected || recoveryMessageQueue.length === 0) return;

    console.log(`📬 Processing ${recoveryMessageQueue.length} queued messages...`);

    while (recoveryMessageQueue.length > 0) {
        if (state.isSettling) break; // Stop if settling starts mid-process

        const msg = recoveryMessageQueue.shift();

        // Skip if too many retries
        if ((msg.retryCount || 0) > 3) {
            console.error(`❌ Dropping message to ${msg.number} after 3 retries.`);
            continue;
        }

        try {
            const response = await axios.post(`http://localhost:${PORT}/message/sendText`, msg);
            if (response.status === 202) {
                console.warn("⚠️ Queue paused: Received 202 Queued (Settling/Disconnected). Waiting for next ready event.");
                // If it returned 202, the handler itself should have requeued it.
                break;
            }
            // Delay between messages to prevent flooding
            await new Promise(r => setTimeout(r, 500));
        } catch (e) {
            console.error('Failed to send queued message:', e.message);
        }
    }
}

module.exports = {
    recoveryMessageQueue,
    processMessageQueue
};
