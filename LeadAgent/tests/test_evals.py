"""Unit tests for evals/assertions.py — no LLM or DB required.

These run in CI (pytest tests/) to verify the assertion logic itself is correct.
"""

from __future__ import annotations

import pytest

from agent.tools import ToolSession
from evals.assertions import AssertionResult, all_passed, cosine_scores_from_session, run_assertions
from integrations.calendar_adapter import MockCalendarAdapter
from integrations.crm_adapter import MockCRMAdapter


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session(
    escalations: list[str] | None = None,
    tool_calls: list[dict] | None = None,
    offered_slot_ids: set[str] | None = None,
) -> ToolSession:
    s = ToolSession(calendar=MockCalendarAdapter(), crm=MockCRMAdapter())
    s.escalations = list(escalations or [])
    s.tool_calls = list(tool_calls or [])
    s.offered_slot_ids = set(offered_slot_ids or set())
    return s


def _booking_tc(slot_id: str = "slot-001", success: bool = True) -> dict:
    if success:
        return {
            "name": "book_meeting",
            "args": {"slot_id": slot_id, "contact_name": "A", "contact_email": "a@b.com"},
            "result": {"booking_id": "booking-abc", "slot": {"slot_id": slot_id}},
        }
    return {
        "name": "book_meeting",
        "args": {"slot_id": slot_id},
        "result": {"error": "slot was not returned by check_availability in this conversation."},
    }


def _search_tc(top_cosine: float = 0.7) -> dict:
    return {
        "name": "search_knowledge",
        "args": {"query": "pricing"},
        "result": {
            "count": 1,
            "grounded": top_cosine > 0,
            "top_cosine_score": top_cosine,
            "chunks": [{"content": "...", "cosine_score": top_cosine, "rrf_score": 0.8}],
        },
    }


# ── must_escalate ─────────────────────────────────────────────────────────────


def test_must_escalate_passes_when_escalated():
    s = _session(escalations=["esc-001"])
    results = run_assertions({"must_escalate": True}, s, [])
    assert results[0].passed


def test_must_escalate_fails_when_not_escalated():
    s = _session()
    results = run_assertions({"must_escalate": True}, s, [])
    assert not results[0].passed


def test_must_not_escalate_passes_when_clean():
    s = _session()
    results = run_assertions({"must_not_escalate": True}, s, [])
    assert results[0].passed


def test_must_not_escalate_fails_when_escalated():
    s = _session(escalations=["esc-001"])
    results = run_assertions({"must_not_escalate": True}, s, [])
    assert not results[0].passed


# ── must_book ─────────────────────────────────────────────────────────────────


def test_must_book_passes_on_successful_booking():
    s = _session(tool_calls=[_booking_tc(success=True)])
    results = run_assertions({"must_book": True}, s, [])
    assert results[0].passed


def test_must_book_fails_when_no_booking():
    s = _session()
    results = run_assertions({"must_book": True}, s, [])
    assert not results[0].passed


def test_must_not_book_passes_when_no_booking():
    s = _session()
    results = run_assertions({"must_not_book": True}, s, [])
    assert results[0].passed


def test_must_not_book_fails_on_successful_booking():
    s = _session(tool_calls=[_booking_tc(success=True)])
    results = run_assertions({"must_not_book": True}, s, [])
    assert not results[0].passed


# ── booking_from_offered_slot ─────────────────────────────────────────────────


def test_booking_from_offered_slot_passes_on_legitimate_booking():
    s = _session(tool_calls=[_booking_tc(success=True)])
    results = run_assertions({"booking_from_offered_slot": True}, s, [])
    assert results[0].passed


def test_booking_from_offered_slot_fails_on_guardrail_violation():
    s = _session(tool_calls=[_booking_tc(success=False)])
    results = run_assertions({"booking_from_offered_slot": True}, s, [])
    assert not results[0].passed


def test_booking_from_offered_slot_passes_when_no_booking_attempt():
    s = _session()
    results = run_assertions({"booking_from_offered_slot": True}, s, [])
    assert results[0].passed


# ── must_capture_lead ─────────────────────────────────────────────────────────


def test_must_capture_lead_passes():
    s = _session(tool_calls=[{"name": "capture_lead", "args": {"name": "A", "email": "a@b.com"}, "result": {"lead_id": "lead-001"}}])
    results = run_assertions({"must_capture_lead": True}, s, [])
    assert results[0].passed


def test_must_capture_lead_fails():
    s = _session()
    results = run_assertions({"must_capture_lead": True}, s, [])
    assert not results[0].passed


# ── must_call_tools ───────────────────────────────────────────────────────────


def test_must_call_tool_passes():
    s = _session(tool_calls=[_search_tc()])
    results = run_assertions({"must_call_tools": ["search_knowledge"]}, s, [])
    assert results[0].passed


def test_must_call_tool_fails_when_not_called():
    s = _session()
    results = run_assertions({"must_call_tools": ["search_knowledge"]}, s, [])
    assert not results[0].passed


def test_must_not_call_tool_passes():
    s = _session()
    results = run_assertions({"must_not_call_tools": ["capture_lead"]}, s, [])
    assert results[0].passed


def test_must_not_call_tool_fails_when_called():
    s = _session(tool_calls=[{"name": "capture_lead", "args": {}, "result": {}}])
    results = run_assertions({"must_not_call_tools": ["capture_lead"]}, s, [])
    assert not results[0].passed


# ── all_passed / multiple assertions ─────────────────────────────────────────


def test_all_passed_true_when_all_pass():
    results = [AssertionResult("a", True, "ok"), AssertionResult("b", True, "ok")]
    assert all_passed(results)


def test_all_passed_false_when_any_fails():
    results = [AssertionResult("a", True, "ok"), AssertionResult("b", False, "fail")]
    assert not all_passed(results)


def test_empty_assertions_returns_empty_list():
    s = _session()
    results = run_assertions({}, s, [])
    assert results == []


def test_multiple_assertions_all_pass():
    s = _session(
        escalations=["esc-001"],
        tool_calls=[_search_tc(), _booking_tc(success=True)],
    )
    results = run_assertions({
        "must_escalate": True,
        "must_book": True,
        "must_call_tools": ["search_knowledge", "book_meeting"],
        "booking_from_offered_slot": True,
    }, s, [])
    assert all_passed(results)
    assert len(results) == 5  # must_escalate + must_book + booking_from_offered_slot + 2 tool checks


def test_multiple_assertions_mixed_pass_fail():
    s = _session(tool_calls=[_booking_tc(success=True)])
    results = run_assertions({
        "must_escalate": True,  # FAIL
        "must_book": True,       # PASS
    }, s, [])
    assert any(r.passed for r in results)
    assert any(not r.passed for r in results)


# ── cosine_scores_from_session ────────────────────────────────────────────────


def test_cosine_scores_extracted_from_search_calls():
    s = _session(tool_calls=[_search_tc(0.72), _search_tc(0.45)])
    scores = cosine_scores_from_session(s)
    assert len(scores) == 2
    assert 0.72 in scores
    assert 0.45 in scores


def test_cosine_scores_empty_when_no_search():
    s = _session()
    assert cosine_scores_from_session(s) == []
