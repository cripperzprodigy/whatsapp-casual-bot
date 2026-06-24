const fs = require('fs');
const state = require('./state');
const { SESSION_PATH, getSessionState } = require('./utils/session');

function isSessionCorruptionError(errMessage) {
    return errMessage && (
        errMessage.includes('session') ||
        errMessage.includes('corrupt') ||
        errMessage.includes('invalid') ||
        errMessage.includes('ExecutionContext')
    );
}

// Note: attemptGracefulRecovery takes the client and initClient function as arguments
// to avoid circular dependencies with client.js
async function attemptGracefulRecovery(client, initClient) {
    state.recoveryTier++;

    if (state.recoveryTier === 1) {
        // Tier 1: Restart Puppeteer context without destroying session
        console.log('Recovery Tier 1: Attempting Puppeteer context restart...');
        try {
            const page = client.pupPage; // Access underlying Puppeteer page
            await page.reload({ waitUntil: 'networkidle0', timeout: 30000 });
            await new Promise(resolve => setTimeout(resolve, 3000));
            console.log('Tier 1 recovery successful');
            return true;
        } catch (tier1Err) {
            console.error('Tier 1 recovery failed:', tier1Err.message);
            return false;
        }
    }

    if (state.recoveryTier === 2) {
        // Tier 2: Reinitialize client WITHOUT deleting session
        console.log('Recovery Tier 2: Reinitializing client (preserving session)...');
        try {
            await client.destroy();
            await new Promise(resolve => setTimeout(resolve, 2000));
            await initClient(); // Reuses existing session
            await new Promise(resolve => setTimeout(resolve, 5000));
            console.log('Tier 2 recovery successful');
            return true;
        } catch (tier2Err) {
            console.error('Tier 2 recovery failed:', tier2Err.message);
            return false;
        }
    }

    if (state.recoveryTier >= 3) {
        // Tier 3: Nuclear option - delete session and force QR scan
        console.log(`Recovery Tier 3: Checking if deletion is safe and necessary for path: ${SESSION_PATH}...`);

        const currentHour = Math.floor(Date.now() / 3600000);
        if (currentHour > state.lastDeletionHour) {
            state.deletionCountPerHour = 0;
            state.lastDeletionHour = currentHour;
        }

        if (state.deletionCountPerHour >= 3) {
             console.log('Rate limit exceeded, skipping Tier 3. Too many deletions in the last hour. Skipping deletion to prevent cascading failures.');
             state.recoveryTier = 0;
             return false;
        }

        const { hasSessionFiles } = getSessionState();

        // Wait 30 seconds before deletion to allow transient errors to resolve
        console.log('Waiting 30 seconds before proceeding with deletion...');
        await new Promise(resolve => setTimeout(resolve, 30000));

        if (hasSessionFiles) {
             console.log(`Deleting session (last resort) at absolute path: ${SESSION_PATH}...`);
             try {
                await client.destroy();
                fs.rmSync(SESSION_PATH, { recursive: true, force: true });
                state.deletionCountPerHour++;
                state.recoveryTier = 0; // Reset for fresh start
                await new Promise(resolve => setTimeout(resolve, 1000));
                await initClient();
                return false; // Requires QR scan
             } catch (tier3Err) {
                console.error('Tier 3 recovery failed:', tier3Err.message);
                return false;
             }
        } else {
             console.log('No session files found. Initializing client...');
             state.recoveryTier = 0;
             await initClient();
             return false;
        }
    }
}

module.exports = {
    isSessionCorruptionError,
    attemptGracefulRecovery
};
