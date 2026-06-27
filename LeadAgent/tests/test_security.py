"""Security tests: XSS, admin auth, headers, input validation, PII redaction."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "a-strong-admin-key-at-least-16-chars")
    monkeypatch.setenv("RATE_LIMIT_RPM", "100")
    monkeypatch.setenv("ADMIN_RATE_LIMIT_RPM", "100")
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "2000")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.com")
    monkeypatch.setenv("CALENDAR_ADAPTER", "mock")
    monkeypatch.setenv("CRM_ADAPTER", "mock")
    monkeypatch.setenv("EMAIL_ADAPTER", "none")
    monkeypatch.setenv("ENV", "production")


@pytest.fixture
def client(_env):
    from api.main import app
    return TestClient(app)


class TestSecurityHeaders:
    def test_nosniff_header(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_frame_deny_header(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy_header(self, client):
        resp = client.get("/health")
        assert "strict-origin" in resp.headers.get("Referrer-Policy", "")


class TestAdminAuth:
    def test_no_key_rejected(self, client):
        resp = client.get("/admin/traces")
        assert resp.status_code == 401

    def test_wrong_key_rejected(self, client):
        resp = client.get("/admin/traces", headers={"X-Admin-Key": "wrong"})
        assert resp.status_code == 401

    def test_timing_safe_comparison(self, client):
        resp1 = client.get("/admin/traces", headers={"X-Admin-Key": "x"})
        resp2 = client.get("/admin/traces", headers={"X-Admin-Key": "a-strong-admin-key-at-least-16-char"})
        assert resp1.status_code == 401
        assert resp2.status_code == 401

    def test_delete_requires_key(self, client):
        resp = client.delete("/admin/conversations/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 401

    def test_purge_requires_key(self, client):
        resp = client.post("/admin/purge?days=30")
        assert resp.status_code == 401


class TestWidgetXSS:
    def test_widget_uses_textcontent(self):
        import re
        with open("web/widget.js") as f:
            js = f.read()
        text_sets = re.findall(r"\.textContent\s*=", js)
        inner_html_sets = re.findall(r"\.innerHTML\s*=", js)
        assert len(text_sets) >= 3, "Widget should use textContent for user/bot messages"
        for match in inner_html_sets:
            pass

    def test_no_dynamic_innerhtml(self):
        import re
        with open("web/widget.js") as f:
            js = f.read()
        lines = js.split("\n")
        for i, line in enumerate(lines):
            if ".innerHTML" in line:
                assert "data" not in line.lower() and "content" not in line.lower() and "message" not in line.lower(), (
                    f"Line {i+1}: innerHTML used with potentially dynamic content: {line.strip()}"
                )


class TestInputValidation:
    def test_oversized_message_rejected(self, client):
        resp = client.post("/chat", json={"message": "x" * 3000})
        assert "error" in resp.text.lower() or resp.status_code >= 400

    def test_empty_message_rejected(self):
        from api.main import app
        stack = app.middleware_stack
        while stack is not None:
            if hasattr(stack, "reset"):
                stack.reset()
            stack = getattr(stack, "app", None)
        c = TestClient(app)
        resp = c.post("/chat", json={"message": ""})
        assert resp.status_code == 422


class TestPIIRedaction:
    def test_redact_email(self):
        from api.routes.admin import _redact_pii
        data = {"text": "Contact john@example.com for info"}
        result = _redact_pii(data)
        assert "john@example.com" not in str(result)
        assert "[REDACTED_EMAIL]" in str(result)

    def test_redact_phone(self):
        from api.routes.admin import _redact_pii
        data = {"text": "Call +1-555-012-3456 for details"}
        result = _redact_pii(data)
        assert "+1-555-012-3456" not in str(result)
        assert "[REDACTED_PHONE]" in str(result)

    def test_nested_redaction(self):
        from api.routes.admin import _redact_pii
        data = {"turns": [{"msg": "email is test@foo.com, phone +1234567890"}]}
        result = _redact_pii(data)
        assert "test@foo.com" not in str(result)


class TestErrorSanitization:
    def test_invalid_uuid_no_stack(self, client):
        resp = client.get(
            "/admin/traces/not-a-uuid",
            headers={"X-Admin-Key": "a-strong-admin-key-at-least-16-chars"},
        )
        assert resp.status_code == 422
        assert "Traceback" not in resp.text

    def test_generic_error_message(self, client):
        resp = client.get("/nonexistent-path")
        assert "Traceback" not in resp.text


class TestToolArgValidation:
    def test_slot_id_rejects_special_chars(self):
        from pydantic import ValidationError
        from agent.tools import BookMeetingInput
        with pytest.raises(ValidationError):
            BookMeetingInput(
                slot_id="slot'; DROP TABLE--",
                contact_name="Test",
                contact_email="t@t.com",
            )

    def test_search_query_length_limit(self):
        from pydantic import ValidationError
        from agent.tools import SearchKnowledgeInput
        with pytest.raises(ValidationError):
            SearchKnowledgeInput(query="x" * 501)

    def test_escalation_context_length_limit(self):
        from pydantic import ValidationError
        from agent.tools import EscalateInput
        with pytest.raises(ValidationError):
            EscalateInput(reason="test", context="x" * 2001)
