const fs = require('fs');

let content = fs.readFileSync('ai-chat/issues.md', 'utf8');

const newIssue = `- [CLOSED] Gateway Session Fails to Persist: Resolved bug where manual QR scans were required on every restart despite LocalAuth configured. Fixed by making \`SESSION_PATH\` absolute, updating docker-compose with a named volume, and restricting Tier 3 aggressive session purges.\n`;

content = content.replace(
    /# Issues\n/,
    `# Issues\n${newIssue}`
);

fs.writeFileSync('ai-chat/issues.md', content);
