import asyncio
import logging
import time
import warnings
from typing import List, Optional, Protocol

import aiohttp
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

class SearchResult:
    def __init__(self, title: str, url: str, snippet: str):
        self.title = title
        self.url = url
        self.snippet = snippet

class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> List[SearchResult]:
        ...

class SearXNGProvider:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    async def search(self, query: str, limit: int) -> List[SearchResult]:
        url = f"{self.base_url}/search"
        params = {
            "q": query,
            "format": "json",
            "categories": "general"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10.0) as response:
                response.raise_for_status()
                data = await response.json()

                results = []
                for idx, item in enumerate(data.get("results", [])):
                    if idx >= limit:
                        break
                    results.append(SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", "")
                    ))
                return results

class DuckDuckGoProvider:
    def _sync_search(self, query: str, limit: int) -> List[SearchResult]:
        try:
            ddgs = DDGS()
            # duckduckgo_search returns a generator of dicts with 'title', 'href', 'body'
            ddg_results = list(ddgs.text(query, max_results=limit))
            results = []
            seen_urls = set()
            for item in ddg_results:
                url = item.get("href", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("body", "")
                ))
            return results
        except Exception as e:
            if "429" in str(e):
                logger.warning("DuckDuckGo rate limit (429) hit. Retrying once after 2 seconds...")
                time.sleep(2)
                ddgs = DDGS()
                ddg_results = list(ddgs.text(query, max_results=limit))
                results = []
                seen_urls = set()
                for item in ddg_results:
                    url = item.get("href", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    results.append(SearchResult(
                        title=item.get("title", ""),
                        url=url,
                        snippet=item.get("body", "")
                    ))
                return results
            else:
                raise e

    async def search(self, query: str, limit: int) -> List[SearchResult]:
        return await asyncio.to_thread(self._sync_search, query, limit)

class HybridSearchService:
    def __init__(self, mode: str, searxng_url: Optional[str]):
        self.mode = mode.lower()
        self.searxng_url = searxng_url
        self.ddg_provider = DuckDuckGoProvider()
        self.searxng_provider = SearXNGProvider(searxng_url) if searxng_url else None

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if self.mode == "hybrid":
            if self.searxng_provider:
                try:
                    results = await self.searxng_provider.search(query, max_results)
                    if results:
                        return results
                except Exception as e:
                    logger.warning(f"SearXNG failed or returned no results, falling back to DDG: {e}")

            # Fallback to DDG
            try:
                return await self.ddg_provider.search(query, max_results)
            except Exception as e:
                logger.error(f"DuckDuckGo fallback failed: {e}")
                raise e

        elif self.mode == "searxng":
            if not self.searxng_provider:
                raise ValueError("SearXNG URL is not configured.")
            return await self.searxng_provider.search(query, max_results)

        elif self.mode == "duckduckgo":
            return await self.ddg_provider.search(query, max_results)

        else:
            # Default to DDG if unknown mode
            logger.warning(f"Unknown search mode: {self.mode}. Defaulting to duckduckgo.")
            return await self.ddg_provider.search(query, max_results)
