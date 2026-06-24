"""Calendar integration: protocol + mock + Google Calendar implementations.

MockCalendarAdapter: in-memory, deterministic — used in tests and CI.
GoogleCalendarAdapter: real Google Calendar API via service account — used in live/staging.

Select via CALENDAR_ADAPTER env var ("google" or "mock", default "mock").
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from domain.lead import BookingResult, TimeSlot

logger = structlog.get_logger(__name__)

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


class GoogleCalendarAdapter:
    """Google Calendar adapter using service account credentials.

    Required env vars:
        GOOGLE_SERVICE_ACCOUNT_KEY — path to the JSON key file
        GOOGLE_CALENDAR_ID — the calendar ID (email or "primary")
        GOOGLE_SLOT_DURATION_MINUTES — slot duration, default 30
    """

    def __init__(self) -> None:
        key_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        if not key_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_KEY is not set")
        self._calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        self._slot_minutes = int(os.environ.get("GOOGLE_SLOT_DURATION_MINUTES", "30"))
        self._credentials = self._load_credentials(key_path)
        self._offered_events: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _load_credentials(key_path: str) -> Any:
        from google.oauth2 import service_account
        scopes = ["https://www.googleapis.com/auth/calendar"]
        return service_account.Credentials.from_service_account_file(key_path, scopes=scopes)

    def _get_token(self) -> str:
        from google.auth.transport.requests import Request
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials.token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    async def get_availability(self, date_range: str) -> list[TimeSlot]:
        """Query Google Calendar freebusy and return available slots.

        Generates 30-min slots across the next 5 business days,
        excluding times that overlap existing events.
        """
        now = datetime.now(timezone.utc)
        time_min = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if time_min < now:
            time_min += timedelta(days=1)
        time_max = time_min + timedelta(days=7)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers=self._headers(),
                json={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "items": [{"id": self._calendar_id}],
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        busy_periods = data.get("calendars", {}).get(self._calendar_id, {}).get("busy", [])
        busy_ranges = [
            (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
            for b in busy_periods
        ]

        slots: list[TimeSlot] = []
        current = time_min
        while current < time_max and len(slots) < 8:
            if current.weekday() >= 5:
                current += timedelta(days=1)
                current = current.replace(hour=9, minute=0)
                continue
            if current.hour < 9 or current.hour >= 17:
                current += timedelta(days=1)
                current = current.replace(hour=9, minute=0)
                continue

            slot_end = current + timedelta(minutes=self._slot_minutes)
            is_busy = any(
                not (slot_end <= bs or current >= be) for bs, be in busy_ranges
            )
            if not is_busy:
                slot_id = f"gcal-{current.strftime('%Y%m%d-%H%M')}"
                label = current.strftime("%A %b %d at %-I:%M %p") if os.name != "nt" else current.strftime("%A %b %d at %#I:%M %p")
                slot = TimeSlot(
                    slot_id=slot_id,
                    start_iso=current.isoformat(),
                    end_iso=slot_end.isoformat(),
                    label=label,
                )
                slots.append(slot)
                self._offered_events[slot_id] = {
                    "start": current.isoformat(),
                    "end": slot_end.isoformat(),
                }

            current += timedelta(minutes=self._slot_minutes)

        logger.info("gcal_availability", slots=len(slots), calendar=self._calendar_id)
        return slots

    async def book_slot(
        self,
        slot_id: str,
        contact_name: str,
        contact_email: str,
    ) -> BookingResult:
        """Create a Google Calendar event for the given slot."""
        slot_info = self._offered_events.get(slot_id)
        if not slot_info:
            raise ValueError(f"Slot {slot_id!r} was not offered in this session")

        event_body = {
            "summary": f"Discovery Call — {contact_name}",
            "description": f"Lead: {contact_name} <{contact_email}>",
            "start": {"dateTime": slot_info["start"], "timeZone": "UTC"},
            "end": {"dateTime": slot_info["end"], "timeZone": "UTC"},
            "attendees": [{"email": contact_email}],
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{self._calendar_id}/events",
                headers=self._headers(),
                json=event_body,
                params={"sendUpdates": "all"},
                timeout=15.0,
            )
            resp.raise_for_status()
            event = resp.json()

        booking_id = event.get("id", f"booking-{uuid.uuid4().hex[:8]}")
        slot = TimeSlot(
            slot_id=slot_id,
            start_iso=slot_info["start"],
            end_iso=slot_info["end"],
            label=event.get("summary", slot_id),
        )

        logger.info("gcal_booked", booking_id=booking_id, slot_id=slot_id, contact=contact_email)
        return BookingResult(
            booking_id=booking_id,
            slot=slot,
            contact_name=contact_name,
            contact_email=contact_email,
            confirmation_message=(
                f"Your meeting is confirmed. "
                f"A calendar invite has been sent to {contact_email}."
            ),
        )


def get_calendar_adapter() -> CalendarAdapter:
    """Factory: returns the adapter specified by CALENDAR_ADAPTER env var."""
    adapter_type = os.environ.get("CALENDAR_ADAPTER", "mock").lower()
    if adapter_type == "google":
        return GoogleCalendarAdapter()
    return MockCalendarAdapter()
