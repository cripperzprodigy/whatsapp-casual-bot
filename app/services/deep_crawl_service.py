import asyncio
import ipaddress
import logging
import socket
from typing import List, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.search_service import HybridSearchService, SearchResult
from app.ai_client import ask_llm
from app.prompts.search_prompts import DEEP_CRAWL_SYNTHESIZER_SYSTEM

logger = logging.getLogger(__name__)

# Tags that carry no useful content — stripped during parsing
_JUNK_TAGS = [
    "script", "style", "nav", "footer", "header",
    "aside", "form", "iframe", "noscript", "svg",
]

# Total character budget for ALL pages combined (LLM context ceiling)
_TOTAL_CONTEXT_BUDGET = 15000


# ------------------------------------------------------------------ #
#  SSRF Protection
# ------------------------------------------------------------------ #

def is_safe_url(url: str) -> bool:
    """Validate that a URL does not point to internal/private infrastructure.

    Blocks:
    - Non-HTTP(S) schemes (file://, ftp://, etc.)
    - Private IP ranges (10/8, 172.16/12, 192.168/16)
    - Loopback (127/8, ::1)
    - Link-local (169.254/16, fe80::/10)
    - Multicast (224/4, ff00::/8)
    - Unspecified (0.0.0.0, ::)
    """
    try:
        parsed = urlparse(url)

        # 1. Scheme check
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"SECURITY WARNING: Blocked non-HTTP scheme: {url}")
            return False

        hostname = parsed.hostname
        if not hostname:
            logger.warning(f"SECURITY WARNING: Blocked URL with no hostname: {url}")
            return False

        # 2. Resolve hostname to IP(s)
        try:
            addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            # DNS resolution failed — block to be safe
            logger.warning(f"SECURITY WARNING: DNS resolution failed for {hostname}, blocking: {url}")
            return False

        for addr_info in addr_infos:
            ip_str = addr_info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                logger.warning(f"SECURITY WARNING: Invalid IP '{ip_str}' for {hostname}, blocking: {url}")
                return False

            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                logger.warning(
                    f"SECURITY WARNING: Blocked private/internal IP {ip} "
                    f"(resolved from {hostname}): {url}"
                )
                return False

        return True

    except Exception as e:
        logger.warning(f"SECURITY WARNING: URL validation error for '{url}': {e}")
        return False


class DeepCrawlService:
    """Fetches full page content for top search results and synthesises
    a comprehensive answer.

    Follows the Single-Response Contract: ``search_and_crawl`` ALWAYS
    returns a ``str`` and NEVER raises.  The caller can blindly pass
    the return value to ``send_long_message``.
    """

    def __init__(
        self,
        search_service: HybridSearchService,
        max_urls: int = 5,
        timeout: float = 10.0,
    ):
        self.search_service = search_service
        self.max_urls = max_urls
        self.timeout = timeout
        # Dynamic budget: distribute total budget evenly across pages
        self._chars_per_page = _TOTAL_CONTEXT_BUDGET // max(1, max_urls)
        # Limit concurrent outbound fetches to 3 to avoid overwhelming network
        self._semaphore = asyncio.Semaphore(3)

    # -------------------------------------------------------------- #
    #  Public Entry Point (Single-Response Contract)
    # -------------------------------------------------------------- #

    async def search_and_crawl(self, query: str) -> str:
        """Top-level entry.  ALWAYS returns str — never raises."""
        try:
            return await asyncio.wait_for(
                self._execute_deep_crawl(query),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"DeepCrawlService global timeout for query '{query}'")
            return "⚠️ Deep crawl took too long. Please try a simpler query or use `!s` for a faster search."
        except Exception as exc:
            logger.error(f"DeepCrawlService unexpected error for query '{query}': {exc}", exc_info=True)
            return "⚠️ Deep crawl encountered an error. Please try again later."

    # -------------------------------------------------------------- #
    #  Internal Orchestration
    # -------------------------------------------------------------- #

    async def _execute_deep_crawl(self, query: str) -> str:
        # 1. Search for top URLs via existing HybridSearchService
        try:
            results: List[SearchResult] = await asyncio.wait_for(
                self.search_service.search(query, max_results=self.max_urls),
                timeout=15.0,
            )
        except Exception as e:
            logger.error(f"Deep crawl search step failed: {e}")
            return f"⚠️ Could not find search results for '{query}'. Please try again."

        if not results:
            return f"🔍 No results found for '{query}'."

        # 2. SSRF filter — only crawl safe URLs
        safe_results = []
        for r in results:
            if r.url and is_safe_url(r.url):
                safe_results.append(r)
            elif r.url:
                logger.info(f"Skipping unsafe URL: {r.url}")

        if not safe_results:
            logger.warning("All URLs blocked by SSRF filter. Falling back to snippet synthesis.")
            snippet_context = self._format_snippets(results)
            return await self._synthesize(query, snippet_context, snippet_fallback=True)

        # 3. Fetch and parse pages concurrently (bounded by semaphore)
        tasks = [
            self._fetch_and_parse(r.url, r.title)
            for r in safe_results
        ]
        fetched: List[Tuple[str, str, str]] = await asyncio.gather(*tasks)

        # Filter out empty results (failed fetches)
        contents = [(title, url, text) for title, url, text in fetched if text]

        if not contents:
            # All fetches failed — fallback to snippet-based answer
            logger.warning("All page fetches failed. Falling back to snippet synthesis.")
            snippet_context = self._format_snippets(results)
            return await self._synthesize(query, snippet_context, snippet_fallback=True)

        # 4. Aggregate context with dynamic budget
        context = self._aggregate_context(contents)

        # 5. Synthesize via LLM
        return await self._synthesize(query, context, snippet_fallback=False)

    # -------------------------------------------------------------- #
    #  Fetch + Parse
    # -------------------------------------------------------------- #

    async def _fetch_and_parse(self, url: str, title: str) -> Tuple[str, str, str]:
        """Fetch a single URL and extract clean text.

        Returns ``(title, url, extracted_text)``; returns empty text on
        any failure so the caller can skip it gracefully.
        """
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; WhatsAppBot/1.0)"},
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()

                    content_type = resp.headers.get("content-type", "")
                    if "text/html" not in content_type and "text/plain" not in content_type:
                        logger.info(f"Skipping non-HTML content from {url}: {content_type}")
                        return (title, url, "")

                    text = self._clean_html(resp.text)
                    return (title, url, text)

            except httpx.TimeoutException:
                logger.warning(f"Timeout fetching {url}")
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP {e.response.status_code} from {url}")
            except Exception as e:
                logger.warning(f"Failed to crawl {url}: {e}")

            return (title, url, "")

    # -------------------------------------------------------------- #
    #  HTML Cleaning
    # -------------------------------------------------------------- #

    def _clean_html(self, html: str) -> str:
        """Strip non-content elements and extract readable text.

        Uses dynamic per-page budget calculated from TOTAL_BUDGET // MAX_URLS.
        """
        soup = BeautifulSoup(html, "lxml")

        # Remove junk tags
        for tag in soup(_JUNK_TAGS):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        # Collapse multiple whitespace
        text = " ".join(text.split())

        # Truncate to dynamic per-page limit
        if len(text) > self._chars_per_page:
            text = text[:self._chars_per_page] + "…"

        return text

    # -------------------------------------------------------------- #
    #  Context Formatting
    # -------------------------------------------------------------- #

    def _aggregate_context(self, contents: List[Tuple[str, str, str]]) -> str:
        """Format crawled pages into a single context string for the LLM.

        Enforces ``_TOTAL_CONTEXT_BUDGET`` as a hard ceiling.
        """
        sections = []
        total_chars = 0

        for title, url, text in contents:
            section = f"--- Content from: {title} ({url}) ---\n{text}\n"
            if total_chars + len(section) > _TOTAL_CONTEXT_BUDGET:
                # Truncate this section to fit within budget
                remaining = _TOTAL_CONTEXT_BUDGET - total_chars
                if remaining > 200:
                    section = section[:remaining] + "\n[Truncated]"
                    sections.append(section)
                break
            sections.append(section)
            total_chars += len(section)

        return "\n".join(sections)

    def _format_snippets(self, results: List[SearchResult]) -> str:
        """Fallback: format search snippets when all crawls fail."""
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}\nSnippet: {r.snippet}\nURL: {r.url}")
        return "\n\n".join(lines)

    # -------------------------------------------------------------- #
    #  LLM Synthesis
    # -------------------------------------------------------------- #

    async def _synthesize(self, query: str, context: str, snippet_fallback: bool) -> str:
        """Send aggregated context to the LLM for synthesis."""
        fallback_note = ""
        if snippet_fallback:
            fallback_note = (
                "\n\nNote: Full page content could not be retrieved. "
                "The context below contains only search snippets. "
                "Provide the best answer possible from the available information."
            )

        prompt = (
            f"Original Query: '{query}'\n\n"
            f"Using the following {'page contents' if not snippet_fallback else 'search snippets'}, "
            f"write a comprehensive, detailed answer. "
            f"Cite sources by referencing URLs where relevant. "
            f"Tone: Helpful and authoritative. Format in Markdown."
            f"{fallback_note}\n\n"
            f"Context:\n{context}"
        )

        try:
            return await asyncio.wait_for(
                ask_llm(
                    prompt=prompt,
                    task_type="search_answer",
                    system_override=DEEP_CRAWL_SYNTHESIZER_SYSTEM,
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Deep crawl synthesis timed out.")
            return (
                "⚠️ I gathered page content but took too long to write the final answer.\n\n"
                + context[:3000]
                + "\n[Raw content truncated]"
            )
        except Exception as e:
            logger.error(f"Deep crawl synthesis failed: {e}")
            return (
                "⚠️ I fetched page content but couldn't synthesize a report. "
                "Here are the raw findings:\n\n"
                + context[:3000]
                + "\n[Raw content truncated]"
            )
