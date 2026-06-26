const fs = require('fs');

const changelogPath = 'ai-chat/changelog.md';
let changelog = fs.readFileSync(changelogPath, 'utf-8');
changelog += '\n- Fixed `ModuleNotFoundError: No module named \'duckduckgo_search\'` by updating `requirements.txt` to use the correct `duckduckgo-search` package instead of the deprecated `ddgs` package.\n';
fs.writeFileSync(changelogPath, changelog);

const issuesPath = 'ai-chat/issues.md';
let issues = fs.readFileSync(issuesPath, 'utf-8');
issues += '\n- Issue: `ModuleNotFoundError: No module named \'duckduckgo_search\'` on startup.\n  - Resolution: Replaced `ddgs` with `duckduckgo-search` in `requirements.txt`.\n';
fs.writeFileSync(issuesPath, issues);

console.log('Docs updated.');
