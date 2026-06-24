"""Email adapter: sends booking confirmation with .ics attachment.

Uses Python stdlib smtplib + email — zero new dependencies.
Select via EMAIL_ADAPTER env var ("smtp" or "none", default "none").
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

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
    start = start_iso.replace("-", "").replace(":", "").split("+")[0].split(".")[0]
    end = end_iso.replace("-", "").replace(":", "").split("+")[0].split(".")[0]
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
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


class SmtpEmailAdapter:
    """Sends booking confirmations via SMTP (e.g. Gmail with App Password).

    Required env vars:
        SMTP_HOST — e.g. smtp.gmail.com
        SMTP_PORT — e.g. 587
        SMTP_USER — your email
        SMTP_PASSWORD — app password (not your account password)
        SMTP_FROM_NAME — display name (optional)
    """

    def __init__(self) -> None:
        self._host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self._port = int(os.environ.get("SMTP_PORT", "587"))
        self._user = os.environ.get("SMTP_USER", "")
        self._password = os.environ.get("SMTP_PASSWORD", "")
        self._from_name = os.environ.get("SMTP_FROM_NAME", "LeadAgent")
        if not self._user or not self._password:
            raise RuntimeError("SMTP_USER and SMTP_PASSWORD must be set")

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
        msg = EmailMessage()
        msg["Subject"] = f"Meeting Confirmed: {summary}"
        msg["From"] = f"{self._from_name} <{self._user}>"
        msg["To"] = f"{to_name} <{to_email}>"

        start_display = start_iso.replace("T", " ").split("+")[0]
        msg.set_content(
            f"Hi {to_name},\n\n"
            f"Your meeting has been confirmed!\n\n"
            f"What: {summary}\n"
            f"When: {start_display} UTC\n"
            f"Booking ID: {booking_id}\n\n"
            f"An .ics calendar invite is attached.\n\n"
            f"See you there!"
        )

        ics = _make_ics(summary, start_iso, end_iso, booking_id, self._user)
        msg.add_attachment(
            ics.encode("utf-8"),
            maintype="text",
            subtype="calendar",
            filename="invite.ics",
        )

        try:
            with smtplib.SMTP(self._host, self._port) as server:
                server.starttls()
                server.login(self._user, self._password)
                server.send_message(msg)
            logger.info("email_sent", to=to_email, booking_id=booking_id)
            return True
        except Exception:
            logger.error("email_send_failed", to=to_email, exc_info=True)
            return False


def get_email_adapter() -> EmailAdapter:
    """Factory: returns the adapter specified by EMAIL_ADAPTER env var."""
    adapter_type = os.environ.get("EMAIL_ADAPTER", "none").lower()
    if adapter_type == "smtp":
        return SmtpEmailAdapter()
    return NoopEmailAdapter()
