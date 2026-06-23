"""Calendar integration: protocol + mock implementation.

Real adapters (Cal.com, Google Calendar) live here in M5.
For M2 every booking test runs against MockCalendarAdapter.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from domain.lead import BookingResult, TimeSlot

# Deterministic slots for testing and local dev
_MOCK_SLOTS: list[TimeSlot] = [
    TimeSlot(
        slot_id="slot-001",
        start_iso="2026-06-24T14:00:00",
        end_iso="2026-06-24T14:30:00",
        label="Tuesday Jun 24 at 2:00 PM",
    ),
    TimeSlot(
        slot_id="slot-002",
        start_iso="2026-06-24T15:00:00",
        end_iso="2026-06-24T15:30:00",
        label="Tuesday Jun 24 at 3:00 PM",
    ),
    TimeSlot(
        slot_id="slot-003",
        start_iso="2026-06-25T10:00:00",
        end_iso="2026-06-25T10:30:00",
        label="Wednesday Jun 25 at 10:00 AM",
    ),
    TimeSlot(
        slot_id="slot-004",
        start_iso="2026-06-25T14:00:00",
        end_iso="2026-06-25T14:30:00",
        label="Wednesday Jun 25 at 2:00 PM",
    ),
]


@runtime_checkable
class CalendarAdapter(Protocol):
    async def get_availability(self, date_range: str) -> list[TimeSlot]: ...

    async def book_slot(
        self,
        slot_id: str,
        contact_name: str,
        contact_email: str,
    ) -> BookingResult: ...


class MockCalendarAdapter:
    """In-memory calendar adapter. Deterministic slots; rejects double-bookings."""

    def __init__(self) -> None:
        self._booked: dict[str, BookingResult] = {}

    async def get_availability(self, date_range: str) -> list[TimeSlot]:
        return [s for s in _MOCK_SLOTS if s.slot_id not in self._booked]

    async def book_slot(
        self,
        slot_id: str,
        contact_name: str,
        contact_email: str,
    ) -> BookingResult:
        if slot_id in self._booked:
            raise ValueError(f"Slot {slot_id!r} is already booked")
        slot = next((s for s in _MOCK_SLOTS if s.slot_id == slot_id), None)
        if slot is None:
            raise ValueError(f"Unknown slot {slot_id!r}")
        booking = BookingResult(
            booking_id=f"booking-{uuid.uuid4().hex[:8]}",
            slot=slot,
            contact_name=contact_name,
            contact_email=contact_email,
            confirmation_message=(
                f"Your meeting is confirmed for {slot.label}. "
                f"A calendar invite will be sent to {contact_email}."
            ),
        )
        self._booked[slot_id] = booking
        return booking
