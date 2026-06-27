"""Typed application settings — single source of truth for all config.

Reads from environment variables (and .env in dev). Validates at import time.
Grouped into client-specific vs infrastructure sections so a future per-client
config store maps cleanly onto this shape.

Usage:
    from config import settings
    settings.deepseek_api_key  # validated str
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Infrastructure ───────────────────────────────────────────────────
    database_url: str = ""
    env: str = "dev"
    log_level: str = "INFO"

    # ── LLM ──────────────────────────────────────────────────────────────
    deepseek_api_key: str = ""
    agent_model: str = "deepseek-chat"
    agent_max_tool_rounds: int = 8
    eval_judge_model: str = "deepseek-chat"

    # ── Embeddings ───────────────────────────────────────────────────────
    gemini_api_key: str = ""
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 100

    # ── Retrieval ────────────────────────────────────────────────────────
    retrieval_top_k: int = 5
    retrieval_candidate_k: int = 30
    retrieval_rrf_k: int = 60
    retrieval_min_cosine_score: float = 0.0
    grounding_cosine_threshold: float = 0.0

    # ── Crawler ──────────────────────────────────────────────────────────
    chunk_tokens: int = 256
    chunk_overlap_tokens: int = 32
    crawler_crawl_delay_seconds: float = 0.5
    crawler_request_timeout_seconds: int = 10
    crawler_max_pages: int = 200

    # ── Client-specific: identity ────────────────────────────────────────
    company_name: str = "our company"
    rep_name: str = ""
    widget_title: str = "Chat with us"
    widget_color: str = "#2563eb"
    widget_position: str = "right"

    # ── Client-specific: calendar ────────────────────────────────────────
    calendar_adapter: str = "mock"
    google_service_account_key: str = ""
    google_calendar_id: str = "primary"
    google_slot_duration_minutes: int = 30

    # ── Client-specific: CRM ─────────────────────────────────────────────
    crm_adapter: str = "mock"
    google_sheets_spreadsheet_id: str = ""
    google_sheets_sheet_name: str = "Sheet1"

    # ── Client-specific: email ───────────────────────────────────────────
    email_adapter: str = "none"
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""
    sendgrid_from_name: str = "LeadAgent"

    # ── Security / API ───────────────────────────────────────────────────
    admin_api_key: str = ""
    allowed_origins: str = "*"
    force_https: bool = False
    hsts_max_age: int = 31536000
    trusted_proxy_ips: str = ""
    rate_limit_rpm: int = 30
    admin_rate_limit_rpm: int = 10
    max_message_length: int = 2000
    max_conversation_turns: int = 50
    session_ttl_seconds: int = 3600
    conversation_token_budget: int = 50000
    daily_token_ceiling: int = 500000


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_required(mode: str = "api") -> list[str]:
    """Check that required secrets are set. Returns list of missing field names."""
    s = get_settings()
    missing = []
    if mode == "api":
        if not s.deepseek_api_key:
            missing.append("DEEPSEEK_API_KEY")
        if not s.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not s.admin_api_key:
            missing.append("ADMIN_API_KEY")
    return missing


settings = get_settings()
