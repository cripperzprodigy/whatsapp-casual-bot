const fs = require('fs');

let content = fs.readFileSync('whatsapp-service/index.js', 'utf8');

// 1. Absolute Path Resolution
content = content.replace(
    /const SESSION_PATH = process\.env\.WHATSAPP_SESSION_PATH \|\| '\.\/\.wwebjs_auth';/,
    `const path = require('path');
const SESSION_PATH = process.env.WHATSAPP_SESSION_PATH || path.resolve(__dirname, '.wwebjs_auth');`
);

// 2. Add session existence check
const sessionStateCode = `
function getSessionState() {
    const sessionExists = fs.existsSync(SESSION_PATH);
    const hasSessionFiles = sessionExists && fs.readdirSync(SESSION_PATH).length > 0;
    return { sessionExists, hasSessionFiles };
}
`;
content = content.replace(
    /let client;\n/,
    `let client;\n${sessionStateCode}`
);

// 3. Update connection info
content = content.replace(
    /const sessionExists = fs\.existsSync\(SESSION_PATH\);\n\s*res\.json\(\{/,
    `const { sessionExists, hasSessionFiles } = getSessionState();\n    res.json({\n        hasSessionFiles: hasSessionFiles,`
);

// 4. Log session state on startup
content = content.replace(
    /function initClient\(\) \{/,
    `function initClient() {
    const { sessionExists, hasSessionFiles } = getSessionState();
    if (!hasSessionFiles) {
        console.log('No session found - QR scan required');
    } else {
        console.log('Session found - attempting to restore');
    }
`
);

content = content.replace(
    /console\.log\('WhatsApp Authenticated'\);/,
    `console.log('WhatsApp Authenticated');
        console.log('Session restored successfully');`
);

content = content.replace(
    /console\.error\('AUTHENTICATION FAILURE', msg\);/,
    `console.error('AUTHENTICATION FAILURE', msg);
        console.log('Session corrupt - will require QR scan');`
);

fs.writeFileSync('whatsapp-service/index.js', content);
