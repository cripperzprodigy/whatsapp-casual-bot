const axios = require('axios');
const state = require('./state');
const PORT = process.env.PORT || 3000;

const recoveryMessageQueue = [];

async function processMessageQueue() {
    if (state.isSettling || !state.isConnected) return;
    if (recoveryMessageQueue.length === 0) return;

    console.log(`📬 Processing ${recoveryMessageQueue.length} queued messages...`);

    // Drain snapshot — do not iterate the live array
    const batch = recoveryMessageQueue.splice(0, recoveryMessageQueue.length);

    for (const msg of batch) {
        if (state.isSettling || !state.isConnected) {
            // Re-queue remaining on state change
            recoveryMessageQueue.unshift(msg);
            break;
        }
        if ((msg.retryCount || 0) >= 3) {
            console.error(`❌ Dropping message to ${msg.number} — exceeded retry limit.`);
            continue;
        }
        try {
            const response = await axios.post(
                `http://localhost:${PORT}/message/sendText`,
                msg
            );
            if (response.status === 202) {
                console.warn('⚠️ Queue paused: gateway not ready. Will retry on next ready event.');
                recoveryMessageQueue.unshift(msg); // put back at front
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
