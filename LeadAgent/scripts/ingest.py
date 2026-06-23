"""Ingest a website into the RAG knowledge base.

Usage:
    python scripts/ingest.py --url https://example.com [--depth 2] [--max-pages 200] [--dry-run]

--dry-run crawls and chunks but skips embedding and storing. Use it first to confirm
trafilatura can extract real content from the target site. If all pages return < 50 chars,
the site is likely client-rendered — add Playwright before proceeding (see TODO.md).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from dotenv import load_dotenv

load_dotenv()

import structlog.stdlib

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

from domain.chunk import ChunkMetadata, DocumentChunk
from rag.chunker import chunk_text
from rag.crawler import crawl
from rag.embedder import embed_texts
from rag.store import upsert_chunks

logger = structlog.get_logger(__name__)


async def run(
    url: str,
    depth: int,
    max_pages: int,
    dry_run: bool,
) -> None:
    crawl_delay = float(os.environ.get("CRAWLER_CRAWL_DELAY_SECONDS", "0.5"))
    request_timeout = float(os.environ.get("CRAWLER_REQUEST_TIMEOUT_SECONDS", "10.0"))
    user_agent = os.environ.get("CRAWLER_USER_AGENT", "LeadAgent-Crawler/1.0")
    chunk_tokens = int(os.environ.get("CHUNK_TOKENS", "256"))
    chunk_overlap = int(os.environ.get("CHUNK_OVERLAP_TOKENS", "32"))

    logger.info("ingest_start", url=url, depth=depth, max_pages=max_pages,
                chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap, dry_run=dry_run)

    total_pages = 0
    total_chunks = 0
    empty_pages = 0

    async for page_url, text, page_depth in crawl(
        url,
        max_depth=depth,
        max_pages=max_pages,
        crawl_delay=crawl_delay,
        request_timeout=request_timeout,
        user_agent=user_agent,
    ):
        total_pages += 1
        chunks_text = chunk_text(text, chunk_tokens=chunk_tokens, overlap_tokens=chunk_overlap)

        if not chunks_text:
            empty_pages += 1
            continue

        logger.info(
            "page_chunked",
            url=page_url,
            depth=page_depth,
            chunks=len(chunks_text),
        )

        if dry_run:
            total_chunks += len(chunks_text)
            # Print a preview of the first chunk for inspection
            preview = chunks_text[0][:200].replace("\n", " ")
            print(f"  [{page_depth}] {page_url} -> {len(chunks_text)} chunks")
            print(f"      preview: {preview}")
            continue

        # Build domain objects
        crawled_at = datetime.now(timezone.utc)
        domain_chunks = [
            DocumentChunk(
                content=chunk,
                source_url=page_url,
                chunk_index=i,
                metadata=ChunkMetadata(
                    crawled_at=crawled_at,
                    depth=page_depth,
                    word_count=len(chunk.split()),
                ),
            )
            for i, chunk in enumerate(chunks_text)
        ]

        embeddings = await embed_texts(chunks_text)
        await upsert_chunks(domain_chunks, embeddings)
        total_chunks += len(domain_chunks)

    mode = "DRY RUN" if dry_run else "COMPLETE"
    logger.info(
        "ingest_done",
        mode=mode,
        seed_url=url,
        total_pages=total_pages,
        total_chunks=total_chunks,
        empty_pages=empty_pages,
    )

    if dry_run:
        print(f"\n--- DRY RUN SUMMARY ---")
        print(f"Pages crawled:  {total_pages}")
        print(f"Chunks created: {total_chunks}")
        print(f"Empty pages:    {empty_pages}")
        if total_pages > 0 and total_chunks == 0:
            print("\nWARNING: Zero chunks extracted. Site may be client-rendered (React/Vue SPA).")
            print("Consider adding Playwright support. See TODO.md.")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a website into the RAG knowledge base.")
    parser.add_argument("--url", required=True, help="Seed URL to crawl")
    parser.add_argument("--depth", type=int, default=2, help="Max crawl depth (default: 2)")
    parser.add_argument("--max-pages", type=int, default=200, help="Max pages to crawl (default: 200)")
    parser.add_argument("--dry-run", action="store_true", help="Crawl and chunk but skip embed+store")
    args = parser.parse_args()

    # psycopg3 async requires SelectorEventLoop; Windows defaults to ProactorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run(args.url, args.depth, args.max_pages, args.dry_run))


if __name__ == "__main__":
    main()
