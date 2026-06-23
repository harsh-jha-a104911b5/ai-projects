"""Deterministic assertion checks for eval scenarios.

These run without any LLM calls — suitable for CI. Each assertion checks a specific
invariant using the ToolSession state and agent responses collected during the scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.tools import ToolSession


@dataclass
class AssertionResult:
    name: str
    passed: bool
    detail: str


def run_assertions(
    expected: dict[str, Any],
    session: ToolSession,
    responses: list[str],
) -> list[AssertionResult]:
    """Evaluate all assertions in `expected` against the session state and responses."""
    results: list[AssertionResult] = []
    tool_names = [tc["name"] for tc in session.tool_calls]

    if expected.get("must_escalate"):
        passed = len(session.escalations) > 0
        results.append(AssertionResult(
            name="must_escalate",
            passed=passed,
            detail=f"escalations={session.escalations}" if passed else "No escalation recorded",
        ))

    if expected.get("must_not_escalate"):
        passed = len(session.escalations) == 0
        results.append(AssertionResult(
            name="must_not_escalate",
            passed=passed,
            detail="OK — no escalation" if passed else f"Unexpected escalations: {session.escalations}",
        ))

    if expected.get("must_book"):
        booked = any(
            tc["name"] == "book_meeting" and "booking_id" in tc["result"]
            for tc in session.tool_calls
        )
        results.append(AssertionResult(
            name="must_book",
            passed=booked,
            detail="Booking confirmed" if booked else "No successful booking found",
        ))

    if expected.get("must_not_book"):
        booked = any(
            tc["name"] == "book_meeting" and "booking_id" in tc["result"]
            for tc in session.tool_calls
        )
        results.append(AssertionResult(
            name="must_not_book",
            passed=not booked,
            detail="Correctly no booking" if not booked else "Unexpected booking occurred",
        ))

    if expected.get("must_capture_lead"):
        captured = any(tc["name"] == "capture_lead" for tc in session.tool_calls)
        results.append(AssertionResult(
            name="must_capture_lead",
            passed=captured,
            detail="Lead captured" if captured else "capture_lead was not called",
        ))

    if expected.get("booking_from_offered_slot"):
        # Any book_meeting call that succeeded must have used an offered slot
        illegal_bookings = [
            tc for tc in session.tool_calls
            if tc["name"] == "book_meeting" and "error" in tc["result"]
            and "not returned by check_availability" in tc["result"].get("error", "")
        ]
        passed = len(illegal_bookings) == 0
        results.append(AssertionResult(
            name="booking_from_offered_slot",
            passed=passed,
            detail=(
                "All booking attempts used offered slots"
                if passed
                else f"{len(illegal_bookings)} guardrail violation(s)"
            ),
        ))

    for tool_name in expected.get("must_call_tools", []):
        called = tool_name in tool_names
        results.append(AssertionResult(
            name=f"must_call_tool:{tool_name}",
            passed=called,
            detail=f"Called {tool_name}" if called else f"Did not call {tool_name}",
        ))

    for tool_name in expected.get("must_not_call_tools", []):
        called = tool_name in tool_names
        results.append(AssertionResult(
            name=f"must_not_call_tool:{tool_name}",
            passed=not called,
            detail=f"Correctly did not call {tool_name}" if not called else f"Unexpectedly called {tool_name}",
        ))

    return results


def all_passed(results: list[AssertionResult]) -> bool:
    return all(r.passed for r in results)


def cosine_scores_from_session(session: ToolSession) -> list[float]:
    """Extract top cosine scores from all search_knowledge calls in the session."""
    scores = []
    for tc in session.tool_calls:
        if tc["name"] == "search_knowledge":
            s = tc["result"].get("top_cosine_score", 0.0)
            scores.append(float(s))
    return scores
