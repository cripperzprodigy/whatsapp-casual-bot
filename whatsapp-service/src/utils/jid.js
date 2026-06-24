/**
 * Resolves a raw phone number to a fully qualified WhatsApp LID (Linked ID).
 *
 * @param {Client} client - The whatsapp-web.js client instance.
 * @param {string} number - The raw phone number or JID to resolve.
 * @returns {Promise<string>} The resolved serialized ID.
 */
async function resolveWhatsAppId(client, number) {
    if (number.endsWith('@g.us')) return number;

    const isJid = number.includes('@');
    const phoneNumber = isJid ? number.split('@')[0] : number;

    let registered = null;
    try {
        registered = await client.getNumberId(phoneNumber);
    } catch (lookupErr) {
        // getNumberId itself crashed (e.g. session error)
        if (isJid) {
            console.warn(`[LID-FALLBACK] getNumberId threw for "${phoneNumber}": ${lookupErr.message}. Using original JID "${number}".`);
            return number;
        }
        throw lookupErr;
    }

    if (registered) {
        return registered._serialized || number;
    }

    if (isJid) {
        console.warn(`[LID-FALLBACK] getNumberId null for "${phoneNumber}". Using original JID "${number}" (LID migration).`);
        return number;
    }

    throw new Error(`NUMBER_NOT_ON_WHATSAPP: ${phoneNumber}`);
}

module.exports = {
    resolveWhatsAppId
};
