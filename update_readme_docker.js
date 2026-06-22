const fs = require('fs');
let content = fs.readFileSync('README.md', 'utf8');

const replacement = `### Option 2: Docker Compose

If you prefer containerization (this handles the Node.js and Python dependencies for you automatically):
\`\`\`bash
docker-compose up -d --build
\`\`\`

**Note on Docker and Session Persistence:**
The \`docker-compose.yml\` is pre-configured to use a named volume (\`whatsapp_session\`) to persist the WhatsApp session safely across container restarts. This prevents having to re-scan the QR code every time the container goes down. If you need to completely clear the session to re-link another number, you can do so securely by bringing the stack down, clearing the volume, and starting it again:
\`\`\`bash
docker-compose down -v
docker-compose up -d --build
\`\`\`
`;

content = content.replace(
    /### Option 2: Docker Compose\n\nIf you prefer containerization \(this handles the Node.js and Python dependencies for you automatically\):\n```bash\ndocker-compose up -d --build\n```/,
    replacement
);

fs.writeFileSync('README.md', content);
