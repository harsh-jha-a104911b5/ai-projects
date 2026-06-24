"""POST /chat — SSE-streamed agent conversation endpoint."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import structlog
import tiktoken
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.loop import AgentLoop
from api.middleware import _get_client_ip
from integrations.calendar_adapter import get_calendar_adapter
from integrations.crm_adapter import get_crm_adapter
from integrations.email_adapter import get_email_adapter

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_MESSAGE_LENGTH = int(os.environ.get("MAX_MESSAGE_LENGTH", "2000"))
_MAX_CONVERSATION_TURNS = int(os.environ.get("MAX_CONVERSATION_TURNS", "50"))
_SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "3600"))
_CONVERSATION_TOKEN_BUDGET = int(os.environ.get("CONVERSATION_TOKEN_BUDGET", "50000"))
_DAILY_TOKEN_CEILING = int(os.environ.get("DAILY_TOKEN_CEILING", "500000"))

_enc = tiktoken.get_encoding("cl100k_base")


# ── In-memory session store ──────────────────────────────────────────────────


@dataclass
class Session:
    loop: AgentLoop
    history: list[Any] = field(default_factory=list)
    turn_count: int = 0
    token_count: int = 0
    created_at: float = field(default_factory=time.time)


_sessions: dict[str, Session] = {}


# ── Daily token tracking ────────────────────────────────────────────────────

_daily_tokens: dict[str, int] = defaultdict(int)
_daily_tokens_date: str = ""


def _get_daily_tokens(ip: str) -> int:
    import datetime
    today = datetime.date.today().isoformat()
    global _daily_tokens_date
    if _daily_tokens_date != today:
        _daily_tokens.clear()
        _daily_tokens_date = today
    return _daily_tokens[ip]


def _add_daily_tokens(ip: str, count: int) -> None:
    import datetime
    today = datetime.date.today().isoformat()
    global _daily_tokens_date
    if _daily_tokens_date != today:
        _daily_tokens.clear()
        _daily_tokens_date = today
    _daily_tokens[ip] += count


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text, disallowed_special=()))


def _get_or_create_session(conversation_id: str | None) -> tuple[str, Session]:
    _evict_stale()
    if conversation_id and conversation_id in _sessions:
        return conversation_id, _sessions[conversation_id]
    calendar = get_calendar_adapter()
    crm = get_crm_adapter()
    email = get_email_adapter()
    loop = AgentLoop(calendar, crm=crm, email=email)
    cid = str(loop.conversation_id)
    session = Session(loop=loop)
    _sessions[cid] = session
    return cid, session


def _evict_stale() -> None:
    now = time.time()
    stale = [k for k, v in _sessions.items() if now - v.created_at > _SESSION_TTL_SECONDS]
    for k in stale:
        del _sessions[k]


# ── Request / response models ────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None


# ── SSE endpoint ─────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    if len(req.message) > _MAX_MESSAGE_LENGTH:
        return _error_response(400, f"Message too long (max {_MAX_MESSAGE_LENGTH} chars)")

    ip = _get_client_ip(request)

    if _get_daily_tokens(ip) >= _DAILY_TOKEN_CEILING:
        logger.warning("daily_token_ceiling_hit", ip=ip)
        return _error_response(429, "Daily usage limit reached. Please try again tomorrow.")

    cid, session = _get_or_create_session(req.conversation_id)

    if session.turn_count >= _MAX_CONVERSATION_TURNS:
        return _error_response(
            400,
            f"Conversation limit reached ({_MAX_CONVERSATION_TURNS} turns). Start a new conversation.",
        )

    if session.token_count >= _CONVERSATION_TOKEN_BUDGET:
        logger.warning("conversation_token_budget_exceeded", conversation_id=cid)
        return _error_response(
            400,
            "This conversation has reached its token budget. Please start a new conversation.",
        )

    session.turn_count += 1
    input_tokens = _count_tokens(req.message)

    async def event_stream():
        yield _sse("session", {"conversation_id": cid})
        response_text = ""
        try:
            async for evt in session.loop.turn_stream(req.message, session.history):
                yield _sse(evt["event"], evt["data"])
                if evt["event"] == "token":
                    response_text += evt["data"].get("content", "")
            session.history = session.loop.last_history
        except Exception as exc:
            logger.error("chat_stream_error", error=str(exc), conversation_id=cid, exc_info=True)
            yield _sse("error", {"content": "An internal error occurred. Please try again."})
            yield _sse("done", {"conversation_id": cid})
        finally:
            output_tokens = _count_tokens(response_text)
            total = input_tokens + output_tokens
            session.token_count += total
            _add_daily_tokens(ip, total)
            if session.token_count > _CONVERSATION_TOKEN_BUDGET * 0.8:
                logger.warning(
                    "conversation_token_budget_warning",
                    conversation_id=cid,
                    used=session.token_count,
                    budget=_CONVERSATION_TOKEN_BUDGET,
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _error_response(status: int, message: str) -> StreamingResponse:
    async def stream():
        yield _sse("error", {"content": message})
        yield _sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream", status_code=status)
