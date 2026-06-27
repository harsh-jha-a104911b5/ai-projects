"""API server entry point.

On production startup:
  1. Sets Windows event loop policy if needed
  2. Runs pending database migrations (safe — idempotent, single-instance)
  3. Starts uvicorn
"""

from __future__ import annotations

import asyncio
import io
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_migrations() -> None:
    """Run pending migrations if DATABASE_URL is set."""
    from dotenv import load_dotenv
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("No DATABASE_URL — skipping migrations.")
        return
    try:
        from db.apply_migrations import main as migrate
        print("Running migrations...")
        migrate()
    except Exception as exc:
        print(f"Migration warning: {exc}")


if __name__ == "__main__":
    _run_migrations()

    import uvicorn
    env = os.environ.get("ENV", "dev")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=(env == "dev"),
        log_level="info",
    )
