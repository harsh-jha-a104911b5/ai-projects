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
from typing import Any

import structlog
from openai import AsyncOpenAI

from agent.prompts import build_system_prompt
from agent.tools import TOOL_SPEC, ToolSession, dispatch
from integrations.calendar_adapter import CalendarAdapter
from integrations.crm_adapter import CRMAdapter, MockCRMAdapter

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
        )

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
                contents.append({"role": "assistant", "content": text})
                logger.info(
                    "agent_turn_complete",
                    user_preview=user_message[:80],
                    tool_rounds=tool_rounds,
                    response_len=len(text),
                    offered_slots=len(self._session.offered_slot_ids),
                    escalations=len(self._session.escalations),
                )
                return text, contents

            tool_rounds += 1
            if tool_rounds > self._max_rounds:
                logger.warning(
                    "agent_max_tool_rounds_exceeded",
                    rounds=tool_rounds,
                    user_preview=user_message[:80],
                )
                contents.append({"role": "assistant", "content": msg.content or ""})
                return (
                    "I'm sorry, I ran into an internal issue. Please try again or "
                    "contact us directly.",
                    contents,
                )

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
