"""Bounded tool-calling agent loop using the OpenAI-compatible API (DeepSeek).

Each AgentLoop instance represents one conversation. A single ToolSession is
created in __init__ and reused across every call to turn(), so offered_slot_ids
and other per-conversation state accumulate correctly.

Each call to AgentLoop.turn():
  1. Appends the user message to the conversation history (list of dicts).
  2. Calls the model with the system prompt, history, and tool spec.
  3. If the model returns tool_calls, executes them and feeds results back.
  4. Repeats up to AGENT_MAX_TOOL_ROUNDS times, then returns the final text response.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from uuid import uuid4

import structlog
from openai import AsyncOpenAI

from agent.prompts import build_system_prompt
from agent.tools import TOOL_SPEC, ToolSession, dispatch
from integrations.calendar_adapter import CalendarAdapter
from integrations.crm_adapter import CRMAdapter, MockCRMAdapter
from integrations.email_adapter import EmailAdapter, NoopEmailAdapter
from observability.logger import ensure_conversation, log_turn

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_MAX_ROUNDS = 8


class AgentLoop:
    """One conversation: greets, searches KB, captures lead, checks calendar, books."""

    def __init__(
        self,
        calendar: CalendarAdapter,
        *,
        crm: CRMAdapter | None = None,
        email: EmailAdapter | None = None,
        system_prompt: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._system_prompt = system_prompt or build_system_prompt()
        self._model = os.environ.get("AGENT_MODEL", _DEFAULT_MODEL)
        self._max_rounds = int(
            os.environ.get("AGENT_MAX_TOOL_ROUNDS", str(_DEFAULT_MAX_ROUNDS))
        )

        if client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError("DEEPSEEK_API_KEY is not set")
            client = AsyncOpenAI(base_url="https://api.deepseek.com", api_key=api_key)
        self._client = client

        # One session per conversation; persists across all turn() calls
        self._session = ToolSession(
            calendar=calendar,
            crm=crm or MockCRMAdapter(),
            email=email or NoopEmailAdapter(),
        )

        self.conversation_id = uuid4()
        self._turn_index = 0
        self._conversation_created = False

    async def turn(
        self,
        user_message: str,
        history: list[Any],
    ) -> tuple[str, list[Any]]:
        """Process one user message. Returns (response_text, updated_history).

        history is the list of message dicts from all previous turns.
        Pass the returned history back on the next call to maintain context.
        The system prompt is prepended on each API call and is NOT stored in history.
        """
        if not self._conversation_created:
            await ensure_conversation(self.conversation_id)
            self._conversation_created = True

        self._turn_index += 1
        turn_idx = self._turn_index
        turn_start = time.monotonic()
        tool_calls_snapshot_start = len(self._session.tool_calls)

        contents: list[dict[str, Any]] = list(history) + [
            {"role": "user", "content": user_message}
        ]

        tool_rounds = 0

        while True:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": self._system_prompt}] + contents,
                tools=TOOL_SPEC,
                temperature=0.1,
            )

            msg = response.choices[0].message
            tool_calls = msg.tool_calls  # list[ToolCall] or None

            if not tool_calls:
                text = (msg.content or "").strip()

                # Grounding backstop: if search_knowledge returned grounded=false
                # and the model is about to answer without escalating, force it.
                if self._session.pending_grounding_escalation:
                    esc_args = {
                        "reason": "no_grounding",
                        "context": "Automatic escalation: knowledge base had no relevant results.",
                    }
                    esc_result = await dispatch(
                        "escalate_to_human", esc_args, self._session
                    )
                    logger.warning(
                        "grounding_backstop_triggered",
                        escalation_id=esc_result.get("escalation_id"),
                    )
                    text = esc_result["user_message"]

                contents.append({"role": "assistant", "content": text})
                logger.info(
                    "agent_turn_complete",
                    user_preview=user_message[:80],
                    tool_rounds=tool_rounds,
                    response_len=len(text),
                    offered_slots=len(self._session.offered_slot_ids),
                    escalations=len(self._session.escalations),
                )
                await self._log_turn(
                    turn_idx, user_message, text,
                    tool_calls_snapshot_start, turn_start,
                )
                return text, contents

            tool_rounds += 1
            if tool_rounds > self._max_rounds:
                logger.warning(
                    "agent_max_tool_rounds_exceeded",
                    rounds=tool_rounds,
                    user_preview=user_message[:80],
                )
                fallback = (
                    "I'm sorry, I ran into an internal issue. Please try again or "
                    "contact us directly."
                )
                contents.append({"role": "assistant", "content": fallback})
                await self._log_turn(
                    turn_idx, user_message, fallback,
                    tool_calls_snapshot_start, turn_start,
                )
                return fallback, contents

            # Append assistant's tool-call turn to history
            contents.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Execute each tool and append its result
            for tc in tool_calls:
                args = json.loads(tc.function.arguments)
                result = await dispatch(tc.function.name, args, self._session)
                logger.info(
                    "tool_dispatched",
                    name=tc.function.name,
                    round=tool_rounds,
                    result_keys=list(result.keys()),
                )
                contents.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

    async def turn_stream(
        self,
        user_message: str,
        history: list[Any],
    ) -> Any:
        """Async generator yielding SSE events. Final history in self.last_history."""
        if not self._conversation_created:
            await ensure_conversation(self.conversation_id)
            self._conversation_created = True

        self._turn_index += 1
        turn_idx = self._turn_index
        turn_start = time.monotonic()
        tc_snapshot_start = len(self._session.tool_calls)

        contents: list[dict[str, Any]] = list(history) + [
            {"role": "user", "content": user_message}
        ]
        tool_rounds = 0

        _STATUS = {
            "search_knowledge": "Searching knowledge base…",
            "check_availability": "Checking calendar…",
            "book_meeting": "Booking meeting…",
            "capture_lead": "Saving contact…",
            "escalate_to_human": "Connecting to team…",
        }

        while True:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": self._system_prompt}] + contents,
                tools=TOOL_SPEC,
                temperature=0.1,
                stream=True,
            )

            collected_text: list[str] = []
            tc_acc: dict[int, dict[str, str]] = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    collected_text.append(delta.content)
                    yield {"event": "token", "data": {"content": delta.content}}

                if delta.tool_calls:
                    for tcd in delta.tool_calls:
                        idx = tcd.index
                        if idx not in tc_acc:
                            tc_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tcd.id:
                            tc_acc[idx]["id"] = tcd.id
                        if tcd.function:
                            if tcd.function.name:
                                tc_acc[idx]["name"] = tcd.function.name
                            if tcd.function.arguments:
                                tc_acc[idx]["arguments"] += tcd.function.arguments

            if not tc_acc:
                text = "".join(collected_text).strip()

                if self._session.pending_grounding_escalation:
                    esc_result = await dispatch(
                        "escalate_to_human",
                        {"reason": "no_grounding", "context": "Automatic escalation: KB had no relevant results."},
                        self._session,
                    )
                    logger.warning("grounding_backstop_triggered", escalation_id=esc_result.get("escalation_id"))
                    text = esc_result["user_message"]
                    yield {"event": "replace", "data": {"content": text}}

                contents.append({"role": "assistant", "content": text})
                await self._log_turn(turn_idx, user_message, text, tc_snapshot_start, turn_start)
                yield {"event": "done", "data": {"conversation_id": str(self.conversation_id)}}
                self.last_history = contents
                return

            tool_rounds += 1
            if tool_rounds > self._max_rounds:
                fallback = (
                    "I'm sorry, I ran into an internal issue. Please try again or "
                    "contact us directly."
                )
                contents.append({"role": "assistant", "content": fallback})
                await self._log_turn(turn_idx, user_message, fallback, tc_snapshot_start, turn_start)
                yield {"event": "message", "data": {"content": fallback}}
                yield {"event": "done", "data": {"conversation_id": str(self.conversation_id)}}
                self.last_history = contents
                return

            if collected_text:
                yield {"event": "clear", "data": {}}

            sorted_tcs = [tc_acc[i] for i in sorted(tc_acc)]
            contents.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in sorted_tcs
                ],
            })

            for tc in sorted_tcs:
                yield {"event": "status", "data": {"content": _STATUS.get(tc["name"], "Processing…")}}
                args = json.loads(tc["arguments"])
                result = await dispatch(tc["name"], args, self._session)
                contents.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result),
                })

    async def _log_turn(
        self,
        turn_idx: int,
        user_message: str,
        assistant_message: str,
        tool_calls_start: int,
        turn_start: float,
    ) -> None:
        """Best-effort trace logging — never raises."""
        latency_ms = int((time.monotonic() - turn_start) * 1000)
        turn_tool_calls = self._session.tool_calls[tool_calls_start:]
        retrieval_chunks = None
        for tc in turn_tool_calls:
            if tc["name"] == "search_knowledge":
                retrieval_chunks = tc["result"].get("chunks", [])
                break
        try:
            await log_turn(
                conversation_id=self.conversation_id,
                turn_index=turn_idx,
                user_message=user_message,
                assistant_message=assistant_message,
                tool_calls=turn_tool_calls,
                retrieval_chunks=retrieval_chunks,
                latency_ms=latency_ms,
                model=self._model,
            )
        except Exception:
            logger.warning("turn_logging_failed", turn=turn_idx, exc_info=True)
