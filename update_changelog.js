const fs = require('fs');

let content = fs.readFileSync('ai-chat/changelog.md', 'utf8');

const newEntry = `- **Gateway Session Persistence Fix**: Resolved an issue where sessions failed to persist across service restarts by standardizing the \`SESSION_PATH\` as an absolute path in \`whatsapp-service/index.js\`. Improved Tier 3 recovery logic to wait 30 seconds before deletion and strictly track an hourly deletion limit to prevent cascading failures. Additionally, integrated a named Docker volume (\`whatsapp_session\`) to guarantee state retention across container recreations.\n`;

content = content.replace(
    /# Changelog\n/,
    `# Changelog\n${newEntry}`
);

fs.writeFileSync('ai-chat/changelog.md', content);
