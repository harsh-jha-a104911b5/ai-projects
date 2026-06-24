"""Turn-level trace logging — writes each agent turn to the Postgres traces table.

Each row stores: user message, assistant response, tool calls, retrieval chunks,
latency, and model name. Conversations are grouped by conversation_id.

All writes are best-effort: a logging failure never crashes the agent.
"""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

import psycopg
import psycopg.rows
import structlog

logger = structlog.get_logger(__name__)


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


async def ensure_conversation(conversation_id: UUID) -> None:
    """Insert a conversation row if it doesn't exist (best-effort)."""
    url = _database_url()
    if not url:
        return
    try:
        aconn = await psycopg.AsyncConnection.connect(url)
        async with aconn:
            async with aconn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO conversations (id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (str(conversation_id),),
                )
    except Exception:
        logger.warning("trace_ensure_conversation_failed", conversation_id=str(conversation_id), exc_info=True)


async def log_turn(
    *,
    conversation_id: UUID,
    turn_index: int,
    user_message: str,
    assistant_message: str,
    tool_calls: list[dict[str, Any]],
    retrieval_chunks: list[dict[str, Any]] | None = None,
    latency_ms: int = 0,
    model: str = "",
) -> None:
    """Write one turn to the traces table. Best-effort — never raises."""
    url = _database_url()
    if not url:
        return
    try:
        aconn = await psycopg.AsyncConnection.connect(url)
        async with aconn:
            async with aconn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO traces
                       (conversation_id, turn_index, user_message, assistant_message,
                        tool_calls, retrieval_chunks, latency_ms, llm_model)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        str(conversation_id),
                        turn_index,
                        user_message,
                        assistant_message,
                        json.dumps(tool_calls),
                        json.dumps(retrieval_chunks) if retrieval_chunks else None,
                        latency_ms,
                        model,
                    ),
                )
        logger.debug("trace_logged", conversation_id=str(conversation_id), turn=turn_index)
    except Exception:
        logger.warning("trace_log_failed", conversation_id=str(conversation_id), exc_info=True)


async def get_conversation(conversation_id: UUID) -> list[dict[str, Any]]:
    """Return all turns for a conversation, ordered by turn_index."""
    url = _database_url()
    if not url:
        return []
    aconn = await psycopg.AsyncConnection.connect(url, row_factory=psycopg.rows.dict_row)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """SELECT turn_index, user_message, assistant_message, tool_calls,
                          retrieval_chunks, latency_ms, llm_model, created_at
                   FROM traces WHERE conversation_id = %s ORDER BY turn_index""",
                (str(conversation_id),),
            )
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def list_conversations(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent conversations with turn counts."""
    url = _database_url()
    if not url:
        return []
    aconn = await psycopg.AsyncConnection.connect(url, row_factory=psycopg.rows.dict_row)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """SELECT c.id, c.status, c.created_at,
                          COUNT(t.id) AS turn_count,
                          MAX(t.created_at) AS last_turn_at
                   FROM conversations c
                   LEFT JOIN traces t ON t.conversation_id = c.id
                   GROUP BY c.id
                   ORDER BY c.created_at DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_conversation(conversation_id: UUID) -> bool:
    """Delete a conversation and all its traces. Returns True if found."""
    url = _database_url()
    if not url:
        return False
    aconn = await psycopg.AsyncConnection.connect(url)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                "DELETE FROM traces WHERE conversation_id = %s",
                (str(conversation_id),),
            )
            await cur.execute(
                "DELETE FROM conversations WHERE id = %s RETURNING id",
                (str(conversation_id),),
            )
            row = await cur.fetchone()
    return row is not None


async def purge_old_data(days: int) -> int:
    """Delete conversations and traces older than N days. Returns count deleted."""
    url = _database_url()
    if not url:
        return 0
    aconn = await psycopg.AsyncConnection.connect(url)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """DELETE FROM traces WHERE conversation_id IN (
                       SELECT id FROM conversations
                       WHERE created_at < now() - make_interval(days => %s)
                   )""",
                (days,),
            )
            await cur.execute(
                """DELETE FROM conversations
                   WHERE created_at < now() - make_interval(days => %s)
                   RETURNING id""",
                (days,),
            )
            rows = await cur.fetchall()
    return len(rows)
