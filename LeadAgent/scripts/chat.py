"""Interactive CLI to drive a live conversation with LeadAgent.

Usage:
    python scripts/chat.py

Type 'quit' or press Ctrl-C to exit.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from dotenv import load_dotenv

load_dotenv()

import structlog.stdlib

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

from agent.loop import AgentLoop
from integrations.calendar_adapter import get_calendar_adapter
from integrations.crm_adapter import get_crm_adapter
from integrations.email_adapter import get_email_adapter


async def main() -> None:
    print("=" * 60)
    print("LeadAgent Chat  (type 'quit' to exit)")
    print("=" * 60 + "\n")

    calendar = get_calendar_adapter()
    crm = get_crm_adapter()
    email = get_email_adapter()
    loop = AgentLoop(calendar, crm=crm, email=email)
    history: list = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if not user_input:
            continue

        try:
            response, history = await loop.turn(user_input, history)
            print(f"\nAgent: {response}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[Error: {exc}]\n")


def main_sync() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        # Ensure stdout/stderr handle Unicode on Windows console
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
