"""API server entry point — sets Windows event loop policy before uvicorn starts."""

from __future__ import annotations

import asyncio
import io
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import uvicorn

if __name__ == "__main__":
    reload = os.environ.get("ENV", "dev") == "dev"
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
    )
