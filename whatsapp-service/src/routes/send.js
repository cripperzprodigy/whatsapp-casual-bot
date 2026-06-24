const express = require('express');
const state = require('../state');
const { getClient, initClient } = require('../client');
const { resolveWhatsAppId } = require('../utils/jid');
const { recoveryMessageQueue, processMessageQueue } = require('../queue');
const { attemptGracefulRecovery, isSessionCorruptionError } = require('../recovery');

const router = express.Router();

router.post('/sendText', async (req, res) => {
    const client = getClient();

    if (!state.isConnected || state.isSettling) {
        console.log(`⏳ Message queued (Client ${state.isSettling ? 'settling' : 'disconnected'}).`);
        const queuedBody = { ...req.body, timestamp: Date.now(), retryCount: (req.body.retryCount || 0) };
        recoveryMessageQueue.push(queuedBody);
        return res.status(202).json({
             status: 'QUEUED_FOR_RECOVERY',
             reason: state.isSettling ? 'CLIENT_SETTLING' : 'DISCONNECTED'
         });
    }

    // validateSession() pre-flight check
    const isSessionValid = client && client.info && client.info.wid && client.pupPage && !client.pupPage.isClosed();
    if (isSessionValid) {
        state.sessionLastValidated = Date.now();
    }

    if (!isSessionValid) {
        console.error('validateSession() pre-flight check failed. Session state is invalid.');
        if (state.recoveryTier === 0) {
            attemptGracefulRecovery(client, initClient).then(processMessageQueue).catch(err => console.error("Async recovery failed", err));
        }
        return res.status(503).json({
            status: "error",
            error_code: "SESSION_CORRUPT",
            error: "Session is corrupt, context undefined",
            requires_qr: state.recoveryTier >= 3
        });
    }

    // Pre-send check
    if (state.consecutiveFailures >= 3 || state.recoveryTier > 0) {
        console.error('Pre-send check: High failure rate or recovering. Queuing...');
        const queuedBody = { ...req.body, timestamp: Date.now(), retryCount: (req.body.retryCount || 0) };
        recoveryMessageQueue.push(queuedBody);

        if (state.recoveryTier === 0) {
            attemptGracefulRecovery(client, initClient).then(processMessageQueue).catch(err => console.error("Async recovery failed", err));
        }
        return res.status(202).json({
            status: "queued",
            error_code: "QUEUED_FOR_RECOVERY",
            message: "Gateway is recovering, message queued."
        });
    }

    const { number, textMessage, options } = req.body;
    if (!number || !textMessage || typeof textMessage.text !== 'string' || textMessage.text.trim() === '') {
        return res.status(400).json({ error: 'Missing number or valid text' });
    }

    try {
        let sendOptions = {};

        if (options && options.quoted) {
            sendOptions.quotedMessageId = options.quoted;
        }

        const trimmedText = textMessage.text.trim();
        console.log(`Sending message to: ${number}, Length: ${trimmedText.length}`);

        const maxRetries = 2;
        let attempt = 0;
        let success = false;
        let lastErr = null;

        while (attempt <= maxRetries && !success) {
            try {
                // Resolution fix applied here
                const chatId = await resolveWhatsAppId(client, number);

                const sendPromise = client.sendMessage(chatId, trimmedText, sendOptions);
                let timeoutId;
                const timeoutPromise = new Promise((_, reject) => {
                    timeoutId = setTimeout(() => reject(new Error('sendMessage timed out after 10 seconds')), 10000);
                });

                await Promise.race([sendPromise, timeoutPromise]);
                clearTimeout(timeoutId);
                success = true;
                state.recoveryTier = 0; // Reset on success
            } catch (err) {
                lastErr = err;

                // Hard abort on non-registered numbers
                if (err.message && err.message.includes('NUMBER_NOT_ON_WHATSAPP')) {
                    console.error(`❌ Number not on WhatsApp: ${number}. Aborting.`);
                    return res.status(400).json({ error: err.message, error_code: 'NUMBER_NOT_ON_WHATSAPP' });
                }

                if (err.message && (err.message.includes('getChat') || err.message.includes('undefined'))) {
                    console.error(`⚠️ Store hydration incomplete (getChat undefined). Forcing delay & re-queue.`);
                    const queuedBody = { ...req.body, timestamp: Date.now(), retryCount: (req.body.retryCount || 0) + 1 };
                    recoveryMessageQueue.push(queuedBody);
                    return res.status(202).json({ status: 'REQUEUED_HYDRATION_ERROR' });
                }

                // Detect session corruption
                if (isSessionCorruptionError(err.message)) {
                    console.error(`Session corruption detected (attempt ${attempt + 1}): "${err.message}". Initiating graceful recovery...`);

                    const recovered = await attemptGracefulRecovery(client, initClient);

                    if (recovered) {
                        console.log('Recovery successful. Queuing message to avoid detached frame errors while settling.');
                        const queuedBody = { ...req.body, timestamp: Date.now(), retryCount: (req.body.retryCount || 0) + 1 };
                        recoveryMessageQueue.push(queuedBody);

                        setTimeout(async () => {
                            try {
                                await processMessageQueue();
                            } catch (e) {
                                console.error('Delayed queue processing failed:', e.message);
                            }
                        }, 5000);

                        return res.status(202).json({ status: 'QUEUED_FOR_RECOVERY', reason: 'RECOVERY_INITIATED' });
                    } else if (state.recoveryTier >= 3) {
                        break;
                    }
                }

                attempt++;
                if (attempt <= maxRetries) {
                    console.log(`Attempt ${attempt} failed. Retrying in 2 seconds...`);
                    await new Promise(resolve => setTimeout(resolve, 2000));
                }
            }
        }

        if (!success) {
            throw lastErr;
        }

        // Update connection metrics on success
        state.totalMessagesSent++;
        state.lastSuccessfulSend = new Date().toISOString();
        state.lastErrorMessage = null;
        state.consecutiveFailures = 0;

        if (recoveryMessageQueue.length > 0) {
            processMessageQueue();
        }

        res.json({ status: 'ok' });
    } catch (err) {
        console.error("Error sending message. Details:", err);
        state.lastErrorMessage = err.message;

        if (err.message && (err.message.includes('getChat') || err.message.includes('undefined'))) {
            return res.status(503).json({
                error: 'CLIENT_NOT_READY',
                message: 'Internal page context loading. Please retry shortly.'
            });
        }

        if (!isSessionCorruptionError(err.message)) {
            state.consecutiveFailures++;
        }
        const requiresQr = state.recoveryTier >= 3 || !state.isConnected;

        res.status(requiresQr ? 503 : 500).json({
            status: "error",
            error_code: isSessionCorruptionError(err.message) ? "SESSION_CORRUPT" : "SEND_TIMEOUT",
            error: err.message,
            stack: err.name === 'TimeoutError' ? undefined : err.stack,
            name: err.name,
            requires_qr: requiresQr,
            recovery_tier: state.recoveryTier
        });
    }
});

router.post('/resolve-quote-id', async (req, res) => {
    const { chatId, messageId } = req.body;
    const client = getClient();
    if (!client) return res.status(503).json({ error: 'Client not ready' });

    try {
        const resolvedChatId = await resolveWhatsAppId(client, chatId);
        const chat = await client.getChatById(resolvedChatId);
        const messages = await chat.fetchMessages({ limit: 50 }); // Search recent messages

        const targetMsg = messages.find(m => m.id.id === messageId);

        if (targetMsg) {
            // Return the serialized ID (e.g., "false_6587481374_3EB0...")
            res.json({ resolvedId: targetMsg.id._serialized });
        } else {
            res.status(404).json({ error: 'Message not found in cache' });
        }
    } catch (error) {
        console.error('Error resolving quote ID:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

module.exports = router;
