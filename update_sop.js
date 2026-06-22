const fs = require('fs');

let content = fs.readFileSync('ai-chat/SOP.md', 'utf8');

const newSOPRule = `- **Session Path Normalization:** All services, including the Node.js Gateway, must resolve file paths for persistent storage (like \`.wwebjs_auth\`) using absolute paths (e.g. \`path.resolve(__dirname, '...')\`) rather than purely relative strings. Docker deployments must use named volumes for these paths to ensure state survives container teardowns.\n`;

// insert into section 4.3
content = content.replace(
    /## 4.3 WhatsApp Gateway Session Health Monitoring\n/,
    `## 4.3 WhatsApp Gateway Session Health Monitoring\n${newSOPRule}`
);

fs.writeFileSync('ai-chat/SOP.md', content);
