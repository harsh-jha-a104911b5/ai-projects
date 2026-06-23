"""Integration tests for the agent loop.

The OpenAI client is replaced with a scripted mock that returns pre-defined
responses in sequence. This tests the loop's control flow, tool dispatch, and
the booking guardrail — without hitting the real API.

Key invariants tested:
  (a) The loop executes tool calls and feeds results back before returning text.
  (b) A full search → availability → booking conversation completes cleanly.
  (c) book_meeting is blocked when check_availability was never called.
  (d) History grows correctly across turns.
  (e) ToolSession persists across turns of the same AgentLoop (slot-offer scope fix).
  (f) ToolSession is isolated across different AgentLoop instances (separate conversations).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent.loop import AgentLoop
from integrations.calendar_adapter import MockCalendarAdapter
from integrations.crm_adapter import MockCRMAdapter


# ── Scripted OpenAI-compatible client ─────────────────────────────────────────


@dataclass
class _FunctionCall:
    name: str
    arguments: str  # JSON string


@dataclass
class _ToolCall:
    id: str
    function: _FunctionCall
    type: str = "function"


@dataclass
class _Message:
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]


def _text_resp(text: str) -> _Response:
    return _Response([_Choice(_Message(content=text))])


def _fn_resp(tool_name: str, **kwargs: Any) -> _Response:
    tc = _ToolCall(
        id=f"call_{tool_name}",
        function=_FunctionCall(name=tool_name, arguments=json.dumps(kwargs)),
    )
    return _Response([_Choice(_Message(tool_calls=[tc]))])


class _ScriptedClient:
    """Returns scripted responses in order; falls back to a safe message when exhausted."""

    def __init__(self, responses: list[_Response]) -> None:
        self._responses = list(responses)
        self._idx = 0

    @property
    def chat(self) -> "_ScriptedClient":
        return self

    @property
    def completions(self) -> "_ScriptedClient":
        return self

    async def create(self, **kwargs: Any) -> _Response:
        if self._idx >= len(self._responses):
            return _text_resp("[script exhausted]")
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


# ── Helper: fake search chunks ────────────────────────────────────────────────


def _make_fake_search():
    from uuid import uuid4

    from domain.chunk import ChunkMetadata, RetrievedChunk

    async def _fake_search(query, **kwargs):
        return [
            RetrievedChunk(
                chunk_id=uuid4(),
                content="We offer end-to-end staffing and BPO services.",
                source_url="https://example.com",
                chunk_index=0,
                metadata=ChunkMetadata(),
                rrf_score=0.9,
                cosine_score=0.85,
                text_score=0.0,
            )
        ]

    return _fake_search


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_response_returned_directly():
    """If model returns text on first call, turn() returns it immediately."""
    client = _ScriptedClient([_text_resp("Hello! How can I help you today?")])
    loop = AgentLoop(MockCalendarAdapter(), client=client)
    response, history = await loop.turn("Hi", [])
    assert response == "Hello! How can I help you today?"
    assert len(history) == 2


@pytest.mark.asyncio
async def test_tool_call_then_text(monkeypatch):
    """Model calls search_knowledge, gets result, then answers."""
    monkeypatch.setattr("agent.tools._search_kb", _make_fake_search())

    client = _ScriptedClient([
        _fn_resp("search_knowledge", query="staffing services"),
        _text_resp("We provide end-to-end staffing and BPO solutions."),
    ])
    loop = AgentLoop(MockCalendarAdapter(), client=client)
    response, history = await loop.turn("Tell me about your staffing services", [])
    assert "staffing" in response.lower()
    assert len(history) == 4  # user + model-fn-call + tool-result + model-text


@pytest.mark.asyncio
async def test_full_booking_conversation(monkeypatch):
    """Multi-turn: question → search → availability → booking → confirm."""
    monkeypatch.setattr("agent.tools._search_kb", _make_fake_search())

    calendar = MockCalendarAdapter()

    # Turn 1: prospect asks about services (own loop, own client)
    turn1_client = _ScriptedClient([
        _fn_resp("search_knowledge", query="managed staffing services"),
        _text_resp("We offer managed staffing, BPO, and digital marketing."),
    ])
    loop = AgentLoop(calendar, client=turn1_client)
    history: list = []
    resp1, history = await loop.turn("What services do you offer?", history)
    assert resp1
    turn1_len = len(history)  # 4

    # Turn 2: same loop, prospect books (check_availability then book_meeting)
    loop._client = _ScriptedClient([
        _fn_resp("check_availability", date_range="next week"),
        _fn_resp(
            "book_meeting",
            slot_id="slot-001",
            contact_name="Alice Smith",
            contact_email="alice@example.com",
        ),
        _text_resp("Your meeting is confirmed for Tuesday Jun 24 at 2:00 PM!"),
    ])
    resp2, history = await loop.turn("I'd like to book a call for next week", history)
    assert "confirmed" in resp2.lower()
    # +1 user + 2 rounds × (fn-call + tool-result) + 1 text = +6
    assert len(history) == turn1_len + 6


@pytest.mark.asyncio
async def test_booking_guardrail_in_loop():
    """Loop enforces: book_meeting without prior check_availability returns error, not booking."""
    calendar = MockCalendarAdapter()
    client = _ScriptedClient([
        _fn_resp("book_meeting", slot_id="slot-001", contact_name="Eve", contact_email="eve@example.com"),
        _text_resp("I need to check availability first before booking."),
    ])
    loop = AgentLoop(calendar, client=client)
    response, _ = await loop.turn("Book me now", [])
    assert response
    remaining = await calendar.get_availability("any")
    assert len(remaining) == 4  # no slots were booked


@pytest.mark.asyncio
async def test_slots_persist_across_turns_same_loop():
    """Slots offered in turn 1 are bookable in turn 2 on the SAME AgentLoop.

    This is the core behavior fixed by making ToolSession per-loop (not per-turn).
    """
    calendar = MockCalendarAdapter()

    client = _ScriptedClient([
        # Turn 1: check availability, respond with slots
        _fn_resp("check_availability", date_range="next week"),
        _text_resp("Here are 4 slots available. Which one works for you?"),
        # Turn 2: book using a slot from turn 1 (no re-check)
        _fn_resp("book_meeting", slot_id="slot-001", contact_name="Alice", contact_email="alice@example.com"),
        _text_resp("Your meeting is confirmed!"),
    ])
    loop = AgentLoop(calendar, client=client)

    # Turn 1: get slots
    resp1, history = await loop.turn("What times are available next week?", [])
    assert "slots" in resp1.lower() or "available" in resp1.lower()
    # slot-001 is now in loop._session.offered_slot_ids
    assert "slot-001" in loop._session.offered_slot_ids

    # Turn 2: book without re-checking (guardrail should allow it)
    resp2, history = await loop.turn(
        "I'll take Tuesday at 2pm. I'm Alice, alice@example.com", history
    )
    assert "confirmed" in resp2.lower()

    # Verify the booking was actually made
    remaining = await calendar.get_availability("any")
    assert len(remaining) == 3  # 4 - 1 = 3


@pytest.mark.asyncio
async def test_slot_offers_isolated_across_conversations():
    """Slots offered to conversation A cannot be used in conversation B.

    Two separate AgentLoop instances = two conversations = isolated sessions.
    """
    calendar = MockCalendarAdapter()

    # Conversation A: checks availability
    client_a = _ScriptedClient([
        _fn_resp("check_availability", date_range="next week"),
        _text_resp("Here are the available slots."),
    ])
    loop_a = AgentLoop(calendar, client=client_a)
    _, _ = await loop_a.turn("What slots are available?", [])
    assert "slot-001" in loop_a._session.offered_slot_ids

    # Conversation B: tries to book slot-001 without ever calling check_availability
    client_b = _ScriptedClient([
        _fn_resp("book_meeting", slot_id="slot-001", contact_name="Mallory", contact_email="m@x.com"),
        _text_resp("I need to check availability first."),
    ])
    loop_b = AgentLoop(calendar, client=client_b)
    _, _ = await loop_b.turn("Book me now", [])

    # The booking from loop_b must have been blocked by the guardrail
    remaining = await calendar.get_availability("any")
    assert len(remaining) == 4  # no slots booked


@pytest.mark.asyncio
async def test_history_carries_across_turns():
    """History returned from turn N is passed into turn N+1 correctly."""
    calendar = MockCalendarAdapter()
    client = _ScriptedClient([
        _text_resp("Turn 1 response."),
        _text_resp("Turn 2 response."),
    ])
    loop = AgentLoop(calendar, client=client)

    _, history = await loop.turn("Message 1", [])
    assert len(history) == 2

    _, history = await loop.turn("Message 2", history)
    assert len(history) == 4


@pytest.mark.asyncio
async def test_max_tool_rounds_safety():
    """Loop exits gracefully when tool rounds exceed the cap."""
    repeating = [_fn_resp("check_availability", date_range="next week")] * 20
    client = _ScriptedClient(repeating)

    loop = AgentLoop(MockCalendarAdapter(), client=client)
    loop._max_rounds = 3
    response, _ = await loop.turn("Keep checking", [])
    assert response
    assert client._idx <= 4  # at most max_rounds + 1 calls made


@pytest.mark.asyncio
async def test_capture_lead_tool_in_loop():
    """capture_lead called by the model creates a lead in the CRM."""
    crm = MockCRMAdapter()
    client = _ScriptedClient([
        _fn_resp("capture_lead", name="Alice Smith", email="alice@example.com", use_case="BPO"),
        _text_resp("I've recorded your details. Let me check available times."),
    ])
    loop = AgentLoop(MockCalendarAdapter(), crm=crm, client=client)
    response, _ = await loop.turn("I'm Alice, alice@example.com. I need BPO services.", [])
    assert "recorded" in response.lower() or "check" in response.lower()
    assert len(crm.leads) == 1
    assert crm.leads[0][1].email == "alice@example.com"


@pytest.mark.asyncio
async def test_escalate_tool_in_loop():
    """escalate_to_human called by the model records escalation and returns acknowledgment."""
    client = _ScriptedClient([
        _fn_resp("escalate_to_human", reason="no_grounding", context="Asked about custom pricing."),
        _text_resp("A team member will follow up with you shortly."),
    ])
    loop = AgentLoop(MockCalendarAdapter(), client=client)
    response, _ = await loop.turn("What's the price for 500 agents?", [])
    assert response
    # Escalation ID recorded in session
    assert len(loop._session.escalations) == 1
