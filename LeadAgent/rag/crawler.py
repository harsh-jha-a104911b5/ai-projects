"""Web crawler: BFS from a seed URL, extracts clean text via trafilatura.

Respects robots.txt. Skips non-HTML and pages with < MIN_CONTENT_CHARS of text
(navigation pages, error pages, JS-only shells). Yields (url, text) pairs.
"""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import datetime
from html.parser import HTMLParser
from typing import AsyncIterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog
import trafilatura

logger = structlog.get_logger(__name__)

MIN_CONTENT_CHARS = 50
DEFAULT_CRAWL_DELAY = 0.5
DEFAULT_TIMEOUT = 10.0


class _LinkExtractor(HTMLParser):
    """Extracts href values from <a> tags."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def _normalize_url(url: str) -> str:
    """Canonical URL for dedup: lowercase host, strip query/fragment, collapse index files."""
    parsed = urlparse(url)
    path = parsed.path
    # /index.html and /index.htm are equivalent to the parent directory
    if path.endswith("/index.html") or path.endswith("/index.htm"):
        path = path[: path.rfind("/") + 1]
    canonical = parsed._replace(
        netloc=parsed.netloc.lower(),
        path=path,
        query="",
        fragment="",
    ).geturl()
    return canonical.rstrip("/")


def _same_domain(url: str, seed: str) -> bool:
    return urlparse(url).netloc == urlparse(seed).netloc


def _is_html_content_type(content_type: str) -> bool:
    return "text/html" in content_type


def _extract_links(html: str, base_url: str) -> list[str]:
    parser = _LinkExtractor()
    parser.feed(html)
    links = []
    for href in parser.links:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        # drop mailto, tel, javascript, etc.
        if parsed.scheme in ("http", "https"):
            links.append(_normalize_url(absolute))
    return links


def _build_robots_parser(base_url: str, user_agent: str) -> RobotFileParser:
    robots_url = urljoin(base_url, "/robots.txt")
    rp = RobotFileParser(robots_url)
    try:
        rp.read()
    except Exception:
        pass  # if robots.txt is unreachable, allow all
    return rp


async def crawl(
    seed_url: str,
    *,
    max_depth: int = 2,
    max_pages: int = 200,
    crawl_delay: float = DEFAULT_CRAWL_DELAY,
    request_timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = "LeadAgent-Crawler/1.0",
) -> AsyncIterator[tuple[str, str, int]]:
    """Yield (url, clean_text, depth) tuples for each successfully extracted page."""
    seed_url = _normalize_url(seed_url)
    robots = _build_robots_parser(seed_url, user_agent)

    headers = {"User-Agent": user_agent}
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
    pages_crawled = 0

    async with httpx.AsyncClient(
        headers=headers,
        timeout=request_timeout,
        follow_redirects=True,
    ) as client:
        while queue and pages_crawled < max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            if not robots.can_fetch(user_agent, url):
                logger.info("robots_disallow", url=url)
                continue

            try:
                # HEAD first to check Content-Type cheaply
                head = await client.head(url)
                ct = head.headers.get("content-type", "")
                if not _is_html_content_type(ct):
                    logger.debug("skip_non_html", url=url, content_type=ct)
                    continue

                response = await client.get(url)
                response.raise_for_status()
            except Exception as exc:
                logger.warning("fetch_error", url=url, error=str(exc))
                continue

            html = response.text
            text = trafilatura.extract(
                html,
                include_links=False,
                include_images=False,
                include_tables=True,
                no_fallback=False,
            )

            if not text or len(text) < MIN_CONTENT_CHARS:
                logger.debug("skip_thin_content", url=url, chars=len(text) if text else 0)
            else:
                pages_crawled += 1
                logger.info(
                    "crawled",
                    url=url,
                    depth=depth,
                    chars=len(text),
                    page=pages_crawled,
                )
                yield url, text, depth

            # Enqueue child links if we haven't hit max depth
            if depth < max_depth:
                for link in _extract_links(html, url):
                    if link not in visited and _same_domain(link, seed_url):
                        queue.append((link, depth + 1))

            if crawl_delay > 0:
                await asyncio.sleep(crawl_delay)

    logger.info("crawl_complete", seed=seed_url, pages_crawled=pages_crawled)


# Allow running as a quick diagnostic: python -m rag.crawler https://example.com
if __name__ == "__main__":
    import sys

    async def _main() -> None:
        url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
        async for page_url, text, depth in crawl(url, max_depth=1, max_pages=10):
            print(f"[depth={depth}] {page_url} ({len(text)} chars)")
            print(text[:200])
            print("---")

    asyncio.run(_main())
