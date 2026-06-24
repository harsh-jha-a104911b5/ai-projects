"""FastAPI application — chat API + admin trace viewer.

Serves the embeddable widget as static files from web/.
"""

from __future__ import annotations

import os

import structlog
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from api.routes.admin import router as admin_router
from api.routes.chat import router as chat_router

logger = structlog.get_logger(__name__)

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]

app = FastAPI(
    title="LeadAgent",
    version="0.1.0",
    docs_url="/admin/docs" if os.environ.get("ENV") == "dev" else None,
    redoc_url=None,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)

app.include_router(chat_router)
app.include_router(admin_router)

_WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/widget", StaticFiles(directory=_WEB_DIR), name="widget")


@app.exception_handler(Exception)
async def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", path=str(request.url.path), error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "An internal error occurred."},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
