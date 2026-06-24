"""Email adapter: sends booking confirmation with .ics attachment.

Adapters:
  NoopEmailAdapter — does nothing (default, tests/CI).
  SendGridEmailAdapter — transactional email via SendGrid HTTP API.
    Uses httpx (already a dependency). Scoped API key via env only.

Select via EMAIL_ADAPTER env var ("sendgrid" or "none", default "none").
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import httpx
import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class EmailAdapter(Protocol):
    async def send_booking_confirmation(
        self,
        *,
        to_email: str,
        to_name: str,
        summary: str,
        start_iso: str,
        end_iso: str,
        booking_id: str,
    ) -> bool: ...


def _make_ics(
    summary: str, start_iso: str, end_iso: str, booking_id: str, organizer_email: str
) -> str:
    """Generate an RFC 5545 VCALENDAR for a single event."""
    start = start_iso.replace("-", "").replace(":", "").split("+")[0].split(".")[0]
    end = end_iso.replace("-", "").replace(":", "").split("+")[0].split(".")[0]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//LeadAgent//Booking//EN\r\n"
        "METHOD:REQUEST\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{booking_id}@leadagent\r\n"
        f"DTSTAMP:{now}\r\n"
        f"DTSTART:{start}Z\r\n"
        f"DTEND:{end}Z\r\n"
        f"SUMMARY:{summary}\r\n"
        f"ORGANIZER:mailto:{organizer_email}\r\n"
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


class NoopEmailAdapter:
    """Does nothing — used when email is not configured."""

    async def send_booking_confirmation(self, **kwargs) -> bool:  # type: ignore[override]
        logger.debug("email_noop", to=kwargs.get("to_email"))
        return False


class SendGridEmailAdapter:
    """Sends booking confirmations via SendGrid v3 Mail Send API.

    Required env vars:
        SENDGRID_API_KEY — scoped to Mail Send only
        SENDGRID_FROM_EMAIL — verified sender address
        SENDGRID_FROM_NAME — display name (optional, default "LeadAgent")
    """

    _API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self) -> None:
        self._api_key = os.environ.get("SENDGRID_API_KEY", "")
        self._from_email = os.environ.get("SENDGRID_FROM_EMAIL", "")
        self._from_name = os.environ.get("SENDGRID_FROM_NAME", "LeadAgent")
        if not self._api_key or not self._from_email:
            raise RuntimeError("SENDGRID_API_KEY and SENDGRID_FROM_EMAIL must be set")

    async def send_booking_confirmation(
        self,
        *,
        to_email: str,
        to_name: str,
        summary: str,
        start_iso: str,
        end_iso: str,
        booking_id: str,
    ) -> bool:
        start_display = start_iso.replace("T", " ").split("+")[0]
        plain_body = (
            f"Hi {to_name},\n\n"
            f"Your meeting has been confirmed!\n\n"
            f"What: {summary}\n"
            f"When: {start_display} UTC\n"
            f"Booking ID: {booking_id}\n\n"
            f"An .ics calendar invite is attached — open it to add the event "
            f"to Google Calendar, Apple Calendar, or Outlook.\n\n"
            f"See you there!"
        )

        ics = _make_ics(summary, start_iso, end_iso, booking_id, self._from_email)
        ics_b64 = base64.b64encode(ics.encode("utf-8")).decode("ascii")

        payload = {
            "personalizations": [{"to": [{"email": to_email, "name": to_name}]}],
            "from": {"email": self._from_email, "name": self._from_name},
            "subject": f"Meeting Confirmed: {summary}",
            "content": [{"type": "text/plain", "value": plain_body}],
            "attachments": [
                {
                    "content": ics_b64,
                    "type": "text/calendar",
                    "filename": "invite.ics",
                    "disposition": "attachment",
                }
            ],
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._API_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=15.0,
                )
            if resp.status_code in (200, 201, 202):
                logger.info("email_sent", to=to_email, booking_id=booking_id, status=resp.status_code)
                return True
            logger.error("email_send_failed", to=to_email, status=resp.status_code, body=resp.text[:200])
            return False
        except Exception:
            logger.error("email_send_error", to=to_email, exc_info=True)
            return False


def get_email_adapter() -> EmailAdapter:
    """Factory: returns the adapter specified by EMAIL_ADAPTER env var."""
    adapter_type = os.environ.get("EMAIL_ADAPTER", "none").lower()
    if adapter_type == "sendgrid":
        return SendGridEmailAdapter()
    return NoopEmailAdapter()
