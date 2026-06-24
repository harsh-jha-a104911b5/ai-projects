"""CLI to view traced conversations.

Usage:
    python scripts/traces.py                       # list recent conversations
    python scripts/traces.py <conversation_id>     # show full trace for one conversation
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from observability.logger import get_conversation, list_conversations

console = Console()


async def show_conversation(conversation_id: UUID) -> None:
    turns = await get_conversation(conversation_id)
    if not turns:
        console.print(f"[red]No traces found for conversation {conversation_id}[/red]")
        return

    console.rule(f"[bold]Conversation {conversation_id}[/bold]")
    for turn in turns:
        console.print(f"\n[dim]Turn {turn['turn_index']} — {turn['llm_model']} — {turn['latency_ms']}ms[/dim]")
        console.print(Panel(turn["user_message"] or "(empty)", title="User", border_style="blue"))
        console.print(Panel(turn["assistant_message"] or "(empty)", title="Agent", border_style="green"))

        tool_calls = turn.get("tool_calls")
        if isinstance(tool_calls, str):
            tool_calls = json.loads(tool_calls)
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("name", "?")
                args = tc.get("args", {})
                result_keys = list(tc.get("result", {}).keys())
                console.print(
                    f"  [yellow]tool:[/yellow] {name}({json.dumps(args, default=str)[:80]}) "
                    f"→ {result_keys}"
                )


async def show_list() -> None:
    convos = await list_conversations(limit=20)
    if not convos:
        console.print("[dim]No conversations logged yet.[/dim]")
        return

    table = Table(title="Recent Conversations", show_lines=True)
    table.add_column("ID", style="dim", width=38)
    table.add_column("Status", width=10)
    table.add_column("Turns", width=6, justify="right")
    table.add_column("Last Turn", width=22)
    table.add_column("Created", width=22)

    for c in convos:
        table.add_row(
            str(c["id"]),
            c.get("status", "?"),
            str(c.get("turn_count", 0)),
            str(c.get("last_turn_at", "—"))[:19],
            str(c.get("created_at", "—"))[:19],
        )

    console.print(table)
    console.print("\n[dim]View a conversation: python scripts/traces.py <id>[/dim]")


async def main() -> None:
    if len(sys.argv) > 1:
        try:
            cid = UUID(sys.argv[1])
        except ValueError:
            console.print(f"[red]Invalid UUID: {sys.argv[1]}[/red]")
            sys.exit(1)
        await show_conversation(cid)
    else:
        await show_list()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
