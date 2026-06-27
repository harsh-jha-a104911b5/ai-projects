"""Unit tests for MockCRMAdapter."""

from __future__ import annotations

import pytest

from domain.lead import LeadCapture
from integrations.crm_adapter import MockCRMAdapter


@pytest.mark.asyncio
async def test_create_lead_returns_id():
    crm = MockCRMAdapter()
    lead = LeadCapture(name="Alice Smith", email="alice@example.com")
    result = await crm.create_lead(lead)
    assert result.lead_id.startswith("lead-")
    assert "captured" in result.message.lower()


@pytest.mark.asyncio
async def test_create_lead_stores_data():
    crm = MockCRMAdapter()
    await crm.create_lead(LeadCapture(name="Alice", email="a@example.com", use_case="staffing"))
    await crm.create_lead(LeadCapture(name="Bob", email="b@example.com"))
    assert len(crm.leads) == 2
    emails = [lead.email for _, lead in crm.leads]
    assert "a@example.com" in emails
    assert "b@example.com" in emails


@pytest.mark.asyncio
async def test_create_lead_ids_are_unique():
    crm = MockCRMAdapter()
    r1 = await crm.create_lead(LeadCapture(name="A", email="a@example.com"))
    r2 = await crm.create_lead(LeadCapture(name="B", email="b@example.com"))
    assert r1.lead_id != r2.lead_id


@pytest.mark.asyncio
async def test_create_lead_optional_fields():
    crm = MockCRMAdapter()
    lead = LeadCapture(
        name="Carol",
        email="carol@example.com",
        phone="+1-555-0100",
        company="ACME Corp",
        use_case="BPO outsourcing",
        budget_range="$10k-20k/month",
        timeline="Q3 2026",
    )
    result = await crm.create_lead(lead)
    assert result.lead_id
    stored = crm.leads[0][1]
    assert stored.company == "ACME Corp"
    assert stored.timeline == "Q3 2026"
