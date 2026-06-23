"""Unit tests for tool dispatch, the booking guardrail, and M3 tools.

These tests run entirely in-process — no DB, no Gemini API.
search_knowledge is monkeypatched to return fake chunks.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from domain.chunk import ChunkMetadata, RetrievedChunk
from integrations.calendar_adapter import MockCalendarAdapter
from integrations.crm_adapter import MockCRMAdapter
from agent.tools import ToolSession, dispatch


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def session() -> ToolSession:
    return ToolSession(calendar=MockCalendarAdapter(), crm=MockCRMAdapter())


def _fake_chunks(n: int = 2) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=uuid4(),
            content=f"Chunk {i}: We offer competitive pricing plans for small businesses.",
            source_url="https://example.com",
            chunk_index=i,
            metadata=ChunkMetadata(),
            rrf_score=0.9 - i * 0.1,
            cosine_score=0.8,
            text_score=0.0,
        )
        for i in range(n)
    ]


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


# ── search_knowledge ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_knowledge_returns_structured_result(session, monkeypatch):
    monkeypatch.setattr("agent.tools._search_kb", _async_return(_fake_chunks(2)))
    result = await dispatch("search_knowledge", {"query": "pricing"}, session)
    assert result["count"] == 2
    assert len(result["chunks"]) == 2
    assert result["chunks"][0]["content"].startswith("Chunk 0")
    assert "example.com" in result["sources"][0]


@pytest.mark.asyncio
async def test_search_knowledge_grounded_true_when_chunks_found(session, monkeypatch):
    monkeypatch.setattr("agent.tools._search_kb", _async_return(_fake_chunks(1)))
    result = await dispatch("search_knowledge", {"query": "pricing"}, session)
    assert result["grounded"] is True
    assert "grounding_note" not in result


@pytest.mark.asyncio
async def test_search_knowledge_grounded_false_when_empty(session, monkeypatch):
    monkeypatch.setattr("agent.tools._search_kb", _async_return([]))
    result = await dispatch("search_knowledge", {"query": "nonexistent topic"}, session)
    assert result["count"] == 0
    assert result["grounded"] is False
    assert "grounding_note" in result
    assert "escalate_to_human" in result["grounding_note"]


# ── check_availability ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_availability_returns_slots(session):
    result = await dispatch("check_availability", {"date_range": "next week"}, session)
    assert result["count"] > 0
    assert len(result["slots"]) == result["count"]
    first = result["slots"][0]
    assert "slot_id" in first
    assert "label" in first


@pytest.mark.asyncio
async def test_check_availability_populates_offered_slot_ids(session):
    assert len(session.offered_slot_ids) == 0
    result = await dispatch("check_availability", {"date_range": "next week"}, session)
    assert len(session.offered_slot_ids) == result["count"]


# ── book_meeting guardrail ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_book_meeting_blocked_without_availability_check(session):
    """Guardrail: slot_id not in offered_slot_ids → error, no booking."""
    result = await dispatch(
        "book_meeting",
        {"slot_id": "slot-001", "contact_name": "Eve", "contact_email": "eve@example.com"},
        session,
    )
    assert "error" in result
    assert "check_availability" in result["error"]


@pytest.mark.asyncio
async def test_book_meeting_succeeds_after_availability_check(session):
    await dispatch("check_availability", {"date_range": "next week"}, session)
    result = await dispatch(
        "book_meeting",
        {"slot_id": "slot-001", "contact_name": "Eve", "contact_email": "eve@example.com"},
        session,
    )
    assert "booking_id" in result
    assert result["contact_email"] == "eve@example.com"
    assert result["slot"]["slot_id"] == "slot-001"


@pytest.mark.asyncio
async def test_book_meeting_slot_must_be_from_current_session():
    """Two sessions: slot offered in one cannot be used in the other."""
    cal = MockCalendarAdapter()
    session_a = ToolSession(calendar=cal, crm=MockCRMAdapter())
    session_b = ToolSession(calendar=cal, crm=MockCRMAdapter())

    await dispatch("check_availability", {"date_range": "this week"}, session_a)
    assert "slot-001" in session_a.offered_slot_ids

    result = await dispatch(
        "book_meeting",
        {"slot_id": "slot-001", "contact_name": "Mallory", "contact_email": "m@x.com"},
        session_b,
    )
    assert "error" in result, "Session B must not book a slot it never saw"


# ── capture_lead ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_lead_returns_lead_id(session):
    result = await dispatch(
        "capture_lead",
        {"name": "Alice Smith", "email": "alice@example.com"},
        session,
    )
    assert "lead_id" in result
    assert result["lead_id"].startswith("lead-")
    assert "message" in result


@pytest.mark.asyncio
async def test_capture_lead_with_all_optional_fields(session):
    result = await dispatch(
        "capture_lead",
        {
            "name": "Bob Jones",
            "email": "bob@example.com",
            "phone": "+1-555-0100",
            "company": "ACME Corp",
            "use_case": "BPO outsourcing",
            "budget_range": "$10k-20k/month",
            "timeline": "Q3 2026",
        },
        session,
    )
    assert "lead_id" in result


@pytest.mark.asyncio
async def test_capture_lead_missing_required_raises(session):
    with pytest.raises(Exception):
        await dispatch("capture_lead", {"name": "Alice"}, session)  # email missing


@pytest.mark.asyncio
async def test_capture_lead_missing_name_raises(session):
    with pytest.raises(Exception):
        await dispatch("capture_lead", {"email": "a@example.com"}, session)  # name missing


# ── escalate_to_human ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalate_returns_structured_result(session):
    result = await dispatch(
        "escalate_to_human",
        {"reason": "no_grounding", "context": "User asked about pricing not in KB."},
        session,
    )
    assert result["recorded"] is True
    assert result["escalation_id"].startswith("esc-")
    assert "user_message" in result
    assert "team" in result["user_message"].lower()


@pytest.mark.asyncio
async def test_escalate_records_id_in_session(session):
    assert len(session.escalations) == 0
    await dispatch(
        "escalate_to_human",
        {"reason": "customer_request", "context": "User wants a human."},
        session,
    )
    assert len(session.escalations) == 1


@pytest.mark.asyncio
async def test_escalate_multiple_times_accumulates(session):
    for i in range(3):
        await dispatch(
            "escalate_to_human",
            {"reason": "no_grounding", "context": f"Question {i}"},
            session,
        )
    assert len(session.escalations) == 3
    assert len(set(session.escalations)) == 3  # unique IDs


# ── unknown tool ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(session):
    result = await dispatch("nonexistent_tool", {}, session)
    assert "error" in result
    assert "nonexistent_tool" in result["error"]
