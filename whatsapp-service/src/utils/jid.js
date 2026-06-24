/**
 * Resolves a raw phone number to a fully qualified WhatsApp LID (Linked ID).
 *
 * @param {Client} client - The whatsapp-web.js client instance.
 * @param {string} number - The raw phone number or JID to resolve.
 * @returns {Promise<string>} The resolved serialized ID.
 */
async function resolveWhatsAppId(client, number) {
    // Groups don't use LID routing — pass the JID directly
    if (number.endsWith('@g.us')) {
        return number;
    }

    // Strip suffix, get raw phone number
    const phoneNumber = number.replace(/@.*$/, '');

    const registered = await client.getNumberId(phoneNumber);
    if (!registered) {
        throw new Error(`NUMBER_NOT_ON_WHATSAPP: ${phoneNumber}`);
    }
    return registered._serialized;
}

module.exports = {
    resolveWhatsAppId
};
