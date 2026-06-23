"""Retrieval quality gate.

Runs 10 representative questions through search_knowledge and prints a Rich table
showing top-3 retrieved chunks per question with scores and source URLs.

Computes recall@3: a question is a HIT if any top-3 chunk contains at least one
expected_keyword (case-insensitive). Exits 1 if hit rate < 70%.

Usage:
    python checks/check_retrieval.py [--url-filter DOMAIN] [--top-k N]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

from rag.retriever import search_knowledge

QUESTIONS_FILE = Path(__file__).parent / "retrieval_questions.yaml"
HIT_RATE_THRESHOLD = 0.70
console = Console()


def _is_hit(chunks: list[object], keywords: list[str]) -> bool:
    for chunk in chunks:
        text = getattr(chunk, "content", "").lower()
        if any(kw.lower() in text for kw in keywords):
            return True
    return False


async def run(url_filter: str | None, top_k: int) -> None:
    data = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = data["questions"]

    hits = 0
    total = len(questions)

    for entry in questions:
        question: str = entry["question"]
        expected_keywords: list[str] = entry.get("expected_keywords", [])

        chunks = await search_knowledge(question, top_k=top_k, url_filter=url_filter)

        hit = _is_hit(chunks, expected_keywords)
        if hit:
            hits += 1

        # Build per-question table
        table = Table(
            title=f"[bold]Q:[/bold] {question}  {'[green]HIT[/green]' if hit else '[red]MISS[/red]'}",
            show_lines=True,
        )
        table.add_column("Rank", style="dim", width=4)
        table.add_column("RRF", width=6)
        table.add_column("Cos", width=6)
        table.add_column("BM25", width=6)
        table.add_column("Source", style="cyan", max_width=40)
        table.add_column("Content preview", max_width=80)

        if not chunks:
            table.add_row("—", "—", "—", "—", "—", "[italic dim]No results[/italic dim]")
        else:
            for rank, chunk in enumerate(chunks, 1):
                preview = chunk.content.replace("\n", " ")[:120]
                table.add_row(
                    str(rank),
                    f"{chunk.rrf_score:.4f}",
                    f"{chunk.cosine_score:.3f}",
                    f"{chunk.text_score:.4f}",
                    chunk.source_url,
                    preview,
                )

        console.print(table)
        console.print()

    hit_rate = hits / total if total > 0 else 0.0
    color = "green" if hit_rate >= HIT_RATE_THRESHOLD else "red"
    console.print(
        f"[bold {color}]Recall@{top_k}: {hits}/{total} questions had a relevant chunk in top-{top_k} "
        f"({hit_rate:.0%})[/bold {color}]"
    )

    if hit_rate < HIT_RATE_THRESHOLD:
        console.print(
            f"[red]FAIL: hit rate {hit_rate:.0%} is below threshold {HIT_RATE_THRESHOLD:.0%}[/red]"
        )
        sys.exit(1)
    else:
        console.print("[green]PASS[/green]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check retrieval quality.")
    parser.add_argument(
        "--url-filter",
        default=None,
        help="Restrict search to chunks from URLs containing this string",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of chunks to retrieve per question (default: 3)",
    )
    args = parser.parse_args()

    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args.url_filter, args.top_k))


if __name__ == "__main__":
    main()
