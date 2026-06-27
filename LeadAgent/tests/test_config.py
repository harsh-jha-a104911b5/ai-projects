"""Tests for typed settings and config validation."""

from __future__ import annotations

import pytest


def test_settings_loads_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from config import Settings
    s = Settings()
    assert s.env == "dev"
    assert s.agent_model == "deepseek-chat"
    assert s.embedding_dimensions == 768
    assert s.rate_limit_rpm == 30
    assert s.widget_color == "#2563eb"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("COMPANY_NAME", "TestCo")
    monkeypatch.setenv("WIDGET_COLOR", "#ff0000")
    monkeypatch.setenv("RATE_LIMIT_RPM", "100")
    from config import Settings
    s = Settings()
    assert s.company_name == "TestCo"
    assert s.widget_color == "#ff0000"
    assert s.rate_limit_rpm == 100


def test_validate_required_missing(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    from config import Settings
    s = Settings(_env_file=None)
    missing = []
    if not s.deepseek_api_key:
        missing.append("DEEPSEEK_API_KEY")
    if not s.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not s.admin_api_key:
        missing.append("ADMIN_API_KEY")
    assert "DEEPSEEK_API_KEY" in missing
    assert "GEMINI_API_KEY" in missing
    assert "ADMIN_API_KEY" in missing


def test_validate_required_present(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key-123")
    from config import validate_required, get_settings
    get_settings.cache_clear()
    missing = validate_required("api")
    assert missing == []
    get_settings.cache_clear()


def test_embed_snippet_endpoint(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("ENV", "dev")
    from config import get_settings
    get_settings.cache_clear()
    from api.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/embed-snippet")
    assert resp.status_code == 200
    data = resp.json()
    assert "snippet" in data
    assert "widget.js" in data["snippet"]
    assert "data-api" in data["snippet"]
    get_settings.cache_clear()
