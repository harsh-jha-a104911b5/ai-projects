"""Domain models for leads and conversations. Zero I/O."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    HANDED_OFF = "handed_off"


class ConversationChannel(str, Enum):
    WEB = "web"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class Lead(BaseModel):
    id: UUID | None = None
    email: str | None = None
    name: str | None = None
    phone: str | None = None
    metadata: dict[str, str] = {}
    created_at: datetime | None = None


class ConversationTurn(BaseModel):
    role: str  # 'user' | 'assistant' | 'tool'
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    created_at: datetime | None = None


# ── Calendar / booking types (M2+) ───────────────────────────────────────────


class TimeSlot(BaseModel):
    """A bookable calendar slot returned by check_availability."""

    slot_id: str
    start_iso: str  # ISO 8601 local datetime, e.g. "2026-06-24T14:00:00"
    end_iso: str
    label: str      # human-readable, e.g. "Tuesday Jun 24 at 2:00 PM"


class BookingResult(BaseModel):
    """Confirmation returned after a successful book_meeting call."""

    booking_id: str
    slot: TimeSlot
    contact_name: str
    contact_email: str
    confirmation_message: str


# ── Lead capture / CRM types (M3+) ───────────────────────────────────────────


class LeadCapture(BaseModel):
    """Qualified prospect data collected during a conversation."""

    name: str
    email: str
    phone: str | None = None
    company: str | None = None
    use_case: str | None = None
    budget_range: str | None = None
    timeline: str | None = None
    source: str = "chat"


class LeadCreateResult(BaseModel):
    lead_id: str
    message: str


class EscalationRecord(BaseModel):
    escalation_id: str
    reason: str
    context: str
    created_at: datetime
