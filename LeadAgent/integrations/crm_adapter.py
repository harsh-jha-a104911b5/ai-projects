"""CRM integration: protocol + mock + Google Sheets implementations.

MockCRMAdapter: in-memory, deterministic — used in tests and CI.
GoogleSheetsCRMAdapter: appends leads to a Google Sheet via Sheets API v4.

Select via CRM_ADAPTER env var ("sheets" or "mock", default "mock").
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from domain.lead import LeadCapture, LeadCreateResult

logger = structlog.get_logger(__name__)

_HEADERS_ROW = [
    "Lead ID", "Timestamp", "Name", "Email", "Phone",
    "Company", "Use Case", "Budget", "Timeline", "Source",
]


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


class GoogleSheetsCRMAdapter:
    """Google Sheets CRM — appends leads as rows via Sheets API v4.

    Required env vars:
        GOOGLE_SERVICE_ACCOUNT_KEY — path to the JSON key file
        GOOGLE_SHEETS_SPREADSHEET_ID — the spreadsheet ID from the URL
    Optional:
        GOOGLE_SHEETS_SHEET_NAME — sheet tab name (default "Leads")
    """

    def __init__(self) -> None:
        key_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        if not key_path:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_KEY is not set")
        self._spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")
        if not self._spreadsheet_id:
            raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is not set")
        self._sheet_name = os.environ.get("GOOGLE_SHEETS_SHEET_NAME", "Leads")
        self._credentials = self._load_credentials(key_path)
        self._headers_ensured = False

    @staticmethod
    def _load_credentials(key_path: str) -> Any:
        from google.oauth2 import service_account
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
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

    async def _ensure_headers(self, client: httpx.AsyncClient) -> None:
        if self._headers_ensured:
            return
        range_str = f"{self._sheet_name}!A1:J1"
        resp = await client.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"
            f"/values/{range_str}",
            headers=self._headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        values = resp.json().get("values", [])
        if not values:
            await client.put(
                f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"
                f"/values/{range_str}",
                headers=self._headers(),
                params={"valueInputOption": "RAW"},
                json={"values": [_HEADERS_ROW]},
                timeout=10.0,
            )
        self._headers_ensured = True

    async def create_lead(self, lead: LeadCapture) -> LeadCreateResult:
        lead_id = f"lead-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        row = [
            lead_id,
            now,
            lead.name,
            lead.email,
            lead.phone or "",
            lead.company or "",
            lead.use_case or "",
            lead.budget_range or "",
            lead.timeline or "",
            lead.source,
        ]

        async with httpx.AsyncClient() as client:
            await self._ensure_headers(client)
            range_str = f"{self._sheet_name}!A:J"
            resp = await client.post(
                f"https://sheets.googleapis.com/v4/spreadsheets/{self._spreadsheet_id}"
                f"/values/{range_str}:append",
                headers=self._headers(),
                params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                json={"values": [row]},
                timeout=10.0,
            )
            resp.raise_for_status()

        logger.info("sheets_lead_created", lead_id=lead_id, email=lead.email)
        return LeadCreateResult(
            lead_id=lead_id,
            message=f"Lead captured successfully for {lead.email}.",
        )


def get_crm_adapter() -> CRMAdapter:
    """Factory: returns the adapter specified by CRM_ADAPTER env var."""
    adapter_type = os.environ.get("CRM_ADAPTER", "mock").lower()
    if adapter_type == "sheets":
        return GoogleSheetsCRMAdapter()
    return MockCRMAdapter()
