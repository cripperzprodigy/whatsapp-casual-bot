const fs = require('fs');

let content = fs.readFileSync('docker-compose.yml', 'utf8');

// replace local mount with named volume
content = content.replace(
    /- \.\/\.wwebjs_auth:\/app\/\.wwebjs_auth/g,
    '- whatsapp_session:/app/.wwebjs_auth'
);

if (!content.includes('volumes:\n  whatsapp_session:')) {
    content += '\nvolumes:\n  whatsapp_session:\n';
}

fs.writeFileSync('docker-compose.yml', content);
