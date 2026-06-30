# Performance Tuning

## Smart Contact Caching

To reduce API calls to the WhatsApp gateway and significantly speed up commands like `!contacts global`, we implemented a smart caching layer in `app/contact_sync.py`.

### Mechanism
- The cache is stored locally at `data/contact_resolution_cache.json`.
- When a JID is looked up, the system checks this JSON file first.
- If the cached data is less than 24 hours old (`CACHE_TTL = 86400`), the gateway query is skipped entirely.
- To prevent file corruption during concurrent operations, reads and writes are wrapped in a `filelock.FileLock` using the `data/contact_resolution_cache.json.lock` lockfile.

## Batch Processing

Instead of making individual HTTP requests to `/participant/info` for each user in a group:
- `commands.py` iterates over the requested users and filters out those already present in the Smart Cache.
- The unresolved users are chunked into batches of 10.
- A single HTTP request is sent to `POST /participant/info/batch`.
- A deliberate `0.2s` delay (`asyncio.sleep(0.2)`) is executed between batches to prevent overwhelming the Node.js `wwebjs` client or triggering WhatsApp API rate limits.
