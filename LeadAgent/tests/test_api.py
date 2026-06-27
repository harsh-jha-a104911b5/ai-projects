"""Tests for the chat API: endpoints, rate limiting, auth gate, message limits."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("RATE_LIMIT_RPM", "5")
    monkeypatch.setenv("MAX_MESSAGE_LENGTH", "100")
    monkeypatch.setenv("MAX_CONVERSATION_TURNS", "3")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("CALENDAR_ADAPTER", "mock")
    monkeypatch.setenv("CRM_ADAPTER", "mock")


@pytest.fixture
def client(_env):
    from api.main import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_admin_requires_key(client):
    resp = client.get("/admin/traces")
    assert resp.status_code == 401


def test_admin_rejects_wrong_key(client):
    resp = client.get("/admin/traces", headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 401


def test_chat_rejects_empty_message(client):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422


def test_chat_rejects_oversized_message(client):
    resp = client.post("/chat", json={"message": "x" * 200})
    lines = resp.text.strip().split("\n")
    events = [l for l in lines if l.startswith("event: error")]
    assert len(events) > 0


def test_widget_js_served(client):
    resp = client.get("/widget/widget.js")
    assert resp.status_code == 200
    assert "LeadAgent" in resp.text or "la-launcher" in resp.text


def test_cors_headers(client):
    resp = client.options(
        "/chat",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" in resp.headers


class TestRateLimiting:
    def test_rate_limit_enforced(self, client):
        for i in range(5):
            resp = client.post("/chat", json={"message": "hi"})
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.status_code == 429


class TestConversationTurnLimit:
    def test_turn_limit_enforced(self, client):
        import json as _json
        from api.routes import chat as chat_module
        chat_module._sessions.clear()

        _reset_rate_limiter()

        resp1 = client.post("/chat", json={"message": "msg1"})
        assert resp1.status_code == 200

        cid = None
        for line in resp1.text.strip().split("\n"):
            if line.startswith("data: ") and "conversation_id" in line:
                data = _json.loads(line[6:])
                if "conversation_id" in data:
                    cid = data["conversation_id"]
                    break

        assert cid is not None
        assert cid in chat_module._sessions
        chat_module._sessions[cid].turn_count = 3

        resp2 = client.post("/chat", json={"message": "msg2", "conversation_id": cid})
        lines = resp2.text.strip().split("\n")
        has_error = any("Conversation limit" in l for l in lines)
        assert has_error or resp2.status_code == 400


def _reset_rate_limiter():
    from api.main import app
    stack = app.middleware_stack
    while stack is not None:
        if hasattr(stack, "reset"):
            stack.reset()
            return
        stack = getattr(stack, "app", None)
