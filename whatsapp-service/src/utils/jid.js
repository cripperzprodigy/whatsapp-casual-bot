/**
 * Resolves a raw phone number to a fully qualified WhatsApp LID (Linked ID).
 *
 * @param {Client} client - The whatsapp-web.js client instance.
 * @param {string} number - The raw phone number or JID to resolve.
 * @returns {Promise<string>} The resolved serialized ID.
 */
async function resolveWhatsAppId(client, number) {
    // 1. Group Check
    if (number.endsWith('@g.us')) {
        return number;
    }

    // 2. JID Detection & Stripping
    let phoneNumber = number;
    let isJid = false;
    if (number.includes('@')) {
        isJid = true;
        phoneNumber = number.split('@')[0];
    }

    // 3. Resolution Attempt
    try {
        const registered = await client.getNumberId(phoneNumber);

        if (registered) {
            // Successful LID resolution
            return registered._serialized || number;
        }

        // 4. CRITICAL FIX: Handle Null Response for migrated LID accounts
        if (isJid) {
            // Input was a JID (proven valid by incoming message)
            // Fallback to original JID instead of failing
            console.warn(`[LID-FALLBACK] getNumberId returned null for ${phoneNumber}. Falling back to original JID ${number} (Likely LID migration).`);
            return number;
        } else {
            // Input was a bare number - strict failure still applies
            throw new Error(`NUMBER_NOT_ON_WHATSAPP: ${phoneNumber}`);
        }
    } catch (error) {
        // Re-throw if it wasn't handled by the JID fallback
        throw error;
    }
}

module.exports = {
    resolveWhatsAppId
};
