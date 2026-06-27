"""Unit tests for MockCalendarAdapter."""

from __future__ import annotations

import pytest

from integrations.calendar_adapter import MockCalendarAdapter


@pytest.mark.asyncio
async def test_get_availability_returns_slots():
    cal = MockCalendarAdapter()
    slots = await cal.get_availability("next week")
    assert len(slots) >= 1
    assert all(s.slot_id for s in slots)
    assert all(s.label for s in slots)


@pytest.mark.asyncio
async def test_book_slot_success():
    cal = MockCalendarAdapter()
    slots = await cal.get_availability("next week")
    slot = slots[0]
    booking = await cal.book_slot(slot.slot_id, "Alice Smith", "alice@example.com")
    assert booking.booking_id.startswith("booking-")
    assert booking.contact_name == "Alice Smith"
    assert booking.contact_email == "alice@example.com"
    assert booking.slot.slot_id == slot.slot_id
    assert "confirmed" in booking.confirmation_message.lower()


@pytest.mark.asyncio
async def test_booked_slot_disappears_from_availability():
    cal = MockCalendarAdapter()
    slots = await cal.get_availability("any")
    slot_id = slots[0].slot_id
    await cal.book_slot(slot_id, "Bob Jones", "bob@example.com")
    remaining = await cal.get_availability("any")
    assert all(s.slot_id != slot_id for s in remaining)


@pytest.mark.asyncio
async def test_double_booking_raises():
    cal = MockCalendarAdapter()
    slots = await cal.get_availability("any")
    slot_id = slots[0].slot_id
    await cal.book_slot(slot_id, "Alice", "alice@example.com")
    with pytest.raises(ValueError, match="already booked"):
        await cal.book_slot(slot_id, "Bob", "bob@example.com")


@pytest.mark.asyncio
async def test_unknown_slot_raises():
    cal = MockCalendarAdapter()
    with pytest.raises(ValueError, match="Unknown slot"):
        await cal.book_slot("nonexistent-slot", "Alice", "alice@example.com")


@pytest.mark.asyncio
async def test_multiple_independent_bookings():
    cal = MockCalendarAdapter()
    slots = await cal.get_availability("any")
    assert len(slots) >= 2
    b1 = await cal.book_slot(slots[0].slot_id, "Alice", "alice@example.com")
    b2 = await cal.book_slot(slots[1].slot_id, "Bob", "bob@example.com")
    assert b1.booking_id != b2.booking_id
    remaining = await cal.get_availability("any")
    assert len(remaining) == len(slots) - 2
