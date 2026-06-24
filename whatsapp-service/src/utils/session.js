const fs = require('fs');
const path = require('path');

const SESSION_PATH = process.env.WHATSAPP_SESSION_PATH
    ? path.resolve(process.env.WHATSAPP_SESSION_PATH)
    : path.resolve(__dirname, '../../.wwebjs_auth');

function validateSessionPath() {
    if (!fs.existsSync(SESSION_PATH)) {
        console.log(`📁 Creating session directory at: ${SESSION_PATH}`);
        fs.mkdirSync(SESSION_PATH, { recursive: true });
        return 'NO_SESSION';
    }

    // Check for session files
    const files = fs.readdirSync(SESSION_PATH);
    if (files.length === 0) {
        console.log(`⚠️  Session directory exists but is empty: ${SESSION_PATH}`);
        return 'NO_SESSION';
    }

    console.log(`✅ Session directory validated: ${SESSION_PATH} (${files.length} files)`);
    return 'SESSION_EXISTS';
}

function getSessionState() {
    const sessionExists = fs.existsSync(SESSION_PATH);
    const hasSessionFiles = sessionExists && fs.readdirSync(SESSION_PATH).length > 0;
    return { sessionExists, hasSessionFiles };
}

function purgeStaleLock() {
    const lockPath = path.join(SESSION_PATH, 'session', 'Default', 'SingletonLock');
    if (fs.existsSync(lockPath)) {
        console.log(`🗑️ Deleting stale lock: ${lockPath}`);
        try {
            fs.unlinkSync(lockPath);
        } catch (e) {
            console.error(`Failed to delete stale lock: ${e.message}`);
        }
    }
}

module.exports = {
    SESSION_PATH,
    validateSessionPath,
    getSessionState,
    purgeStaleLock
};
