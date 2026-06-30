# SearXNG Deployment Guide

This guide is the definitive source of truth for deploying a local SearXNG Docker container to power the WhatsApp Bot's Agentic Search (`!s`) and basic search (`!search`) commands.

## A. Prerequisites
- Docker (Engine v20.10+)
- Docker Compose (v2.0+)
- Ubuntu/Linux host (recommended) or Windows/macOS.

## B. Directory Structure Tree
To keep the deployment modular and isolated from the main bot repository, create a dedicated `searxng` directory anywhere on your host system (e.g., alongside the bot folder):

```text
searxng/
├── docker-compose.yml
├── .env
├── searxng-data/      (auto-created by docker)
└── settings.yml
```

## C. Step-by-Step Installation

### 1. Create the Structure
```bash
mkdir searxng
cd searxng
```

### 2. Populate `docker-compose.yml`
Create a `docker-compose.yml` file with the following contents:

```yaml
version: '3.8'
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    network_mode: "host" 
    volumes:
      - ./searxng-data:/etc/searxng
      - ./settings.yml:/etc/searxng/settings.yml
    environment:
      - SEARXNG_BASE_URL=http://localhost:8080/
    restart: unless-stopped
```
*(Note: `network_mode: "host"` binds SearXNG directly to the host's network interfaces, simplifying bot connectivity on Linux. If using Windows/Mac, replace `network_mode: "host"` with `ports: - "8080:8080"`).*

### 3. Populate `settings.yml`
Create a `settings.yml` file. This is critical for overriding SearXNG's strict default limiters and specifying the required output formats for the bot (JSON).

```yaml
use_default_settings: true

server:
  # CHANGE_THIS to a unique cryptographic string
  secret_key: "UNIQUE_SECRET_KEY_CHANGE_ME"
  # Disable rate limiter for local API queries from the bot
  limiter: false
  # Bind to all interfaces (required for host network mode)
  bind_address: "0.0.0.0"
  port: 8080

search:
  formats:
    - html
    - json

engines:
  - name: google
    engine: google
    shortcut: go
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
  - name: bing
    engine: bing
    shortcut: bi
```

### 4. Populate Bot's `.env`
Navigate to the WhatsApp bot's directory and update its `.env` file to point to this new instance:

```env
# Enable hybrid mode to fallback to DuckDuckGo if SearXNG fails
SEARCH_PROVIDER_MODE=hybrid

# URL where the bot will reach SearXNG (if both are on host network or bare-metal)
SEARXNG_BASE_URL=http://localhost:8080

# Enable Agentic Search
ENABLE_AGENTIC_SEARCH=true
```

## D. Networking Explanation
The bot connects to SearXNG via standard HTTP GET requests.
- **Topology:** We use `network_mode: "host"`. This means the SearXNG container does not sit behind a Docker bridge network. It binds directly to the host OS's loopback (`127.0.0.1:8080`).
- **Bot Access:** Because SearXNG is on the host loopback, the Python bot (running natively via `start.sh`) can simply request `http://localhost:8080`.
- **Firewall:** Port 8080 does not need to be exposed to the public internet. It only needs to be accessible locally by the bot. Keep it firewalled for privacy.

## E. Starting the Service
From inside your `searxng` directory, execute:
```bash
docker-compose up -d
```
Docker will pull the image and mount your custom `settings.yml`.

## F. Verification Steps

1. **Verify Web UI:** Open a terminal on the host and run:
   ```bash
   curl -I http://localhost:8080/
   ```
   You should receive an `HTTP/1.1 200 OK`.
2. **Verify JSON Output:** Test a dummy query requesting JSON (the format the bot uses):
   ```bash
   curl "http://localhost:8080/search?q=test&format=json"
   ```
   You should receive a massive JSON payload with search results.
3. **Verify WhatsApp:** Send `!s test query` in a WhatsApp chat with the bot.

## G. Troubleshooting Section

### 1. Connection Refused / Timeout
- **Symptoms:** The bot logs `httpx.ConnectError` or `asyncio.TimeoutError`.
- **Cause:** SearXNG is down, or the bot cannot resolve `localhost`.
- **Fix:** Run `docker-compose logs -f searxng`. Ensure no boot errors occurred. If you aren't using `network_mode: "host"`, change `SEARXNG_BASE_URL` in the bot's `.env` to the Docker bridge IP or LAN IP.

### 2. "Configuration Error" on Boot
- **Symptoms:** Container restarts continuously. Logs show `Missing secret_key`.
- **Fix:** Ensure you replaced `UNIQUE_SECRET_KEY_CHANGE_ME` in `settings.yml` with an actual string.

### 3. Rate Limit / 429 Errors from Upstream
- **Symptoms:** Queries return no results or fail. Logs show Google/Bing blocking requests.
- **Fix:** SearXNG aggregates from upstream engines. If your server IP is blocked by Google, edit `settings.yml` to disable the `google` engine or add proxies. The bot will automatically fallback to `DuckDuckGoProvider` if SearXNG fails, provided `SEARCH_PROVIDER_MODE=hybrid`.

### 4. How to Reset SearXNG Data
If the internal Redis cache or config is corrupted:
```bash
docker-compose down
sudo rm -rf searxng-data/
docker-compose up -d
```
