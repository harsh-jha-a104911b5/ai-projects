"""Admin endpoints — trace viewer + data lifecycle, gated behind ADMIN_API_KEY."""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from observability.logger import (
    delete_conversation,
    get_conversation,
    list_conversations,
    purge_old_data,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin")

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{6,}\d")


def _require_admin_key(request: Request) -> None:
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(503, "ADMIN_API_KEY not configured")
    if len(expected) < 16:
        logger.warning("admin_key_too_short", length=len(expected))
    provided = request.headers.get("X-Admin-Key", "")
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        logger.warning(
            "admin_auth_failed",
            ip=request.client.host if request.client else "unknown",
            path=str(request.url.path),
        )
        raise HTTPException(401, "Invalid admin key")
    logger.info(
        "admin_access",
        ip=request.client.host if request.client else "unknown",
        path=str(request.url.path),
        method=request.method,
    )


def _jsonable(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _redact_pii(obj: object) -> object:
    """Redact emails and phone numbers from trace data."""
    if isinstance(obj, str):
        result = _EMAIL_RE.sub("[REDACTED_EMAIL]", obj)
        return _PHONE_RE.sub("[REDACTED_PHONE]", result)
    if isinstance(obj, dict):
        return {k: _redact_pii(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_pii(v) for v in obj]
    return obj


@router.get("/traces", dependencies=[Depends(_require_admin_key)])
async def traces_list(limit: int = 20):
    rows = await list_conversations(limit=min(limit, 100))
    return JSONResponse(content=_jsonable(rows))


@router.get("/traces/{conversation_id}", dependencies=[Depends(_require_admin_key)])
async def traces_detail(conversation_id: UUID, redact: bool = False):
    turns = await get_conversation(conversation_id)
    if not turns:
        raise HTTPException(404, "Conversation not found")
    data = {"conversation_id": str(conversation_id), "turns": turns}
    data = _jsonable(data)
    if redact:
        data = _redact_pii(data)
    return JSONResponse(content=data)


@router.delete("/conversations/{conversation_id}", dependencies=[Depends(_require_admin_key)])
async def delete_conversation_endpoint(conversation_id: UUID):
    deleted = await delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(404, "Conversation not found")
    logger.info("admin_deleted_conversation", conversation_id=str(conversation_id))
    return {"deleted": True, "conversation_id": str(conversation_id)}


@router.post("/purge", dependencies=[Depends(_require_admin_key)])
async def purge_old(days: int = 90):
    if days < 1:
        raise HTTPException(400, "days must be >= 1")
    count = await purge_old_data(days)
    logger.info("admin_purge", days=days, deleted_conversations=count)
    return {"purged_conversations": count, "older_than_days": days}
