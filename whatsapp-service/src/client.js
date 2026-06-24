const { Client, LocalAuth } = require('whatsapp-web.js');
const fs = require('fs');
const { SESSION_PATH, validateSessionPath, purgeStaleLock } = require('./utils/session');
const { registerEvents } = require('./events');
const state = require('./state');

let clientInstance = null;

function createClient() {
    return new Client({
        authStrategy: new LocalAuth({
            clientId: 'bot',
            dataPath: SESSION_PATH
        }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        }
    });
}

async function initClient() {
    // Validate path first
    const sessionState = validateSessionPath();
    if (sessionState === 'NO_SESSION') {
        console.log('🆕 No existing session found. New QR code will be generated.');
    } else {
        console.log('Session found - attempting to restore');
    }

    purgeStaleLock();

    clientInstance = createClient();
    registerEvents(clientInstance);

    // --- RETRY LOGIC FOR LOCK ERRORS ---
    let attempts = 0;
    const maxAttempts = 2;
    let initialized = false;

    while (!initialized && attempts <= maxAttempts) {
        try {
            console.log(`🚀 Attempting to initialize client (Attempt ${attempts + 1}/${maxAttempts + 1})...`);
            await clientInstance.initialize();
            initialized = true; // Success
        } catch (err) {
            attempts++;
            console.error(`❌ Initialization failed: ${err.message}`);

            // Check if it's the specific "browser already running" error
            if (err.message.includes('browser is already running') && attempts <= maxAttempts) {
                console.warn('⚠️ Detected stale browser lock. Attempting self-heal...');

                purgeStaleLock();

                // Destroy client to release handles
                try { await clientInstance.destroy(); } catch (e) {}

                // Re-create client instance
                console.log('🔄 Re-instantiating client...');
                clientInstance = createClient();
                // Events already registered internally in the new instance? No, need to register again.
                // Wait, it's safer to just re-register
                registerEvents(clientInstance);

                // Wait before retry
                await new Promise(r => setTimeout(r, 2000));
            } else {
                // Not a lock error or max attempts reached
                console.error('💀 Fatal initialization error. Giving up.');
                throw err;
             }
        }
    }
}

function getClient() {
    return clientInstance;
}

module.exports = {
    initClient,
    getClient
};
