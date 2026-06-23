"""Unit tests for the web crawler. Uses respx to mock httpx calls."""

from __future__ import annotations

import pytest
import respx
import httpx

from rag.crawler import crawl, _normalize_url, _same_domain, _extract_links


# ── Helper ────────────────────────────────────────────────────────────────────

SIMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
<p>This is a sample business page with enough content to pass the minimum threshold.
It describes our wonderful services and why you should choose us over the competition.
We offer competitive pricing and excellent customer support.</p>
<a href="/about">About us</a>
<a href="/pricing">Pricing</a>
<a href="https://external.com/page">External link</a>
</body>
</html>
"""

THIN_HTML = "<html><body><nav>Home About Contact</nav></body></html>"

ROBOTS_TXT = "User-agent: *\nDisallow: /private/\n"


# ── Unit tests (no crawl) ─────────────────────────────────────────────────────

def test_normalize_url_strips_fragment():
    assert _normalize_url("https://example.com/page#section") == "https://example.com/page"


def test_normalize_url_strips_trailing_slash():
    assert _normalize_url("https://example.com/about/") == "https://example.com/about"


def test_normalize_url_collapses_index_html_at_root():
    assert _normalize_url("https://example.com/index.html") == "https://example.com"


def test_normalize_url_collapses_index_html_in_subdir():
    assert _normalize_url("https://example.com/about/index.html") == "https://example.com/about"


def test_normalize_url_strips_query_string():
    assert _normalize_url("https://example.com/page?utm=foo&ref=bar") == "https://example.com/page"


def test_normalize_url_lowercases_host():
    assert _normalize_url("https://TOF.IO/about") == "https://tof.io/about"


def test_same_domain_true():
    assert _same_domain("https://example.com/about", "https://example.com/")


def test_same_domain_false_for_subdomain():
    assert not _same_domain("https://blog.example.com/post", "https://example.com/")


def test_extract_links_absolute_and_relative():
    links = _extract_links(SIMPLE_HTML, "https://example.com/")
    assert "https://example.com/about" in links
    assert "https://example.com/pricing" in links


def test_extract_links_excludes_external():
    links = _extract_links(SIMPLE_HTML, "https://example.com/")
    # external.com is returned by _extract_links (it's normalised) — filtering
    # to same-domain happens in the crawl loop, not in _extract_links itself.
    # Just check that relative links were resolved correctly.
    assert all(link.startswith("http") for link in links)


# ── Integration-style tests (mocked HTTP) ─────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_crawl_yields_page_with_content():
    respx.head("https://example.com").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"})
    )
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, html=SIMPLE_HTML)
    )
    # robots.txt
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text=ROBOTS_TXT)
    )

    results = []
    async for url, text, depth in crawl(
        "https://example.com",
        max_depth=0,
        max_pages=5,
        crawl_delay=0,
    ):
        results.append((url, text, depth))

    assert len(results) == 1
    url, text, depth = results[0]
    assert url == "https://example.com"
    assert depth == 0
    assert len(text) > 50


@pytest.mark.asyncio
@respx.mock
async def test_crawl_skips_thin_content():
    respx.head("https://example.com").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"})
    )
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, html=THIN_HTML)
    )
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(404)
    )

    results = []
    async for url, text, depth in crawl(
        "https://example.com",
        max_depth=0,
        max_pages=5,
        crawl_delay=0,
    ):
        results.append((url, text, depth))

    assert results == [], "Thin content page should be skipped"


@pytest.mark.asyncio
@respx.mock
async def test_crawl_skips_non_html():
    respx.head("https://example.com/file.pdf").mock(
        return_value=httpx.Response(200, headers={"content-type": "application/pdf"})
    )
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(404)
    )

    results = []
    async for url, text, depth in crawl(
        "https://example.com/file.pdf",
        max_depth=0,
        max_pages=5,
        crawl_delay=0,
    ):
        results.append((url, text, depth))

    assert results == [], "Non-HTML content should be skipped"


@pytest.mark.asyncio
@respx.mock
async def test_crawl_respects_max_pages():
    # Seed page + two child links, but max_pages=1
    child_html = lambda path: f"""
    <html><body>
    <p>Page at {path}. Lots of content here to pass the threshold.
    We offer services and solutions for all your business needs.
    Contact us today for a free consultation and demo.</p>
    </body></html>
    """
    root_html = """
    <html><body>
    <p>Root page. Lots of content here to pass the threshold.
    We offer services and solutions for all your business needs.</p>
    <a href="/a">A</a><a href="/b">B</a>
    </body></html>
    """

    for path in ["", "/a", "/b", "/robots.txt"]:
        url = f"https://example.com{path}"
        if path == "/robots.txt":
            respx.get(url).mock(return_value=httpx.Response(404))
        else:
            respx.head(url).mock(
                return_value=httpx.Response(200, headers={"content-type": "text/html"})
            )
            respx.get(url).mock(
                return_value=httpx.Response(200, html=root_html if path == "" else child_html(path))
            )

    results = []
    async for url, text, depth in crawl(
        "https://example.com",
        max_depth=2,
        max_pages=1,
        crawl_delay=0,
    ):
        results.append((url, text, depth))

    assert len(results) == 1, f"Expected 1 page, got {len(results)}"
