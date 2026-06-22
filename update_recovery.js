const fs = require('fs');

let content = fs.readFileSync('whatsapp-service/index.js', 'utf8');

// Add session variables
content = content.replace(
    /let recoveryTier = 0;/,
    `let recoveryTier = 0;
let sessionLastValidated = Date.now();
let deletionCountPerHour = 0;
let lastDeletionHour = Math.floor(Date.now() / 3600000);`
);

// Modify Tier 3 recovery
const oldTier3 = `    if (recoveryTier >= 3) {
        // Tier 3: Nuclear option - delete session and force QR scan
        console.log('Recovery Tier 3: Deleting session (last resort)...');
        try {
            await client.destroy();
            fs.rmSync(SESSION_PATH, { recursive: true, force: true });
            recoveryTier = 0; // Reset for fresh start
            await new Promise(resolve => setTimeout(resolve, 1000));
            initClient();
            return false; // Requires QR scan
        } catch (tier3Err) {
            console.error('Tier 3 recovery failed:', tier3Err.message);
            return false;
        }
    }`;

const newTier3 = `    if (recoveryTier >= 3) {
        // Tier 3: Nuclear option - delete session and force QR scan
        console.log('Recovery Tier 3: Checking if deletion is safe and necessary...');

        const currentHour = Math.floor(Date.now() / 3600000);
        if (currentHour > lastDeletionHour) {
            deletionCountPerHour = 0;
            lastDeletionHour = currentHour;
        }

        const { hasSessionFiles } = getSessionState();

        // Wait 30 seconds before deletion to allow transient errors to resolve
        console.log('Waiting 30 seconds before proceeding with deletion...');
        await new Promise(resolve => setTimeout(resolve, 30000));

        if (hasSessionFiles && deletionCountPerHour < 3) {
             console.log('Deleting session (last resort)...');
             try {
                await client.destroy();
                fs.rmSync(SESSION_PATH, { recursive: true, force: true });
                deletionCountPerHour++;
                recoveryTier = 0; // Reset for fresh start
                await new Promise(resolve => setTimeout(resolve, 1000));
                initClient();
                return false; // Requires QR scan
             } catch (tier3Err) {
                console.error('Tier 3 recovery failed:', tier3Err.message);
                return false;
             }
        } else if (deletionCountPerHour >= 3) {
             console.log('Too many deletions in the last hour. Skipping deletion to prevent cascading failures.');
             recoveryTier = 0;
             return false;
        } else {
             console.log('No session files found. Initializing client...');
             recoveryTier = 0;
             initClient();
             return false;
        }
    }`;

content = content.replace(oldTier3, newTier3);

// Update sessionLastValidated when valid
content = content.replace(
    /const isSessionValid = client && client\.info && client\.info\.wid && client\.pupPage && !client\.pupPage\.isClosed\(\);/,
    `const isSessionValid = client && client.info && client.info.wid && client.pupPage && !client.pupPage.isClosed();
    if (isSessionValid) {
        sessionLastValidated = Date.now();
    }`
);

fs.writeFileSync('whatsapp-service/index.js', content);
