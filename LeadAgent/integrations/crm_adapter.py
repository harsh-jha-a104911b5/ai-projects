"""CRM integration: protocol + mock implementation.

Real adapters (GHL, HubSpot, Postgres leads table) live here in M5.
For M3 every capture_lead call runs against MockCRMAdapter.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from domain.lead import LeadCapture, LeadCreateResult


@runtime_checkable
class CRMAdapter(Protocol):
    async def create_lead(self, lead: LeadCapture) -> LeadCreateResult: ...


class MockCRMAdapter:
    """In-memory CRM. Stores leads as (lead_id, LeadCapture) pairs."""

    def __init__(self) -> None:
        self._leads: list[tuple[str, LeadCapture]] = []

    async def create_lead(self, lead: LeadCapture) -> LeadCreateResult:
        lead_id = f"lead-{uuid.uuid4().hex[:8]}"
        self._leads.append((lead_id, lead))
        return LeadCreateResult(
            lead_id=lead_id,
            message=f"Lead captured successfully for {lead.email}.",
        )

    @property
    def leads(self) -> list[tuple[str, LeadCapture]]:
        return list(self._leads)
