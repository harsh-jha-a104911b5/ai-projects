"""Security middleware: rate limiting, security headers, HTTPS enforcement."""

from __future__ import annotations

import os
import time
from collections import defaultdict

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger(__name__)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For behind a trusted proxy."""
    trusted_proxies = os.environ.get("TRUSTED_PROXY_IPS", "").split(",")
    trusted_proxies = [p.strip() for p in trusted_proxies if p.strip()]

    socket_ip = request.client.host if request.client else "unknown"

    if not trusted_proxies:
        return socket_ip

    if socket_ip in trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",")]
            for ip in reversed(ips):
                if ip not in trusted_proxies:
                    return ip
    return socket_ip


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers + optional HSTS + HTTPS redirect."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._force_https = os.environ.get("FORCE_HTTPS", "").lower() == "true"
        self._hsts_max_age = int(os.environ.get("HSTS_MAX_AGE", "31536000"))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._force_https:
            proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
            if proto == "http":
                url = str(request.url).replace("http://", "https://", 1)
                return Response(status_code=301, headers={"Location": url})

        response = await call_next(request)

        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        if self._force_https:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self._hsts_max_age}; includeSubDomains"
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-IP rate limiter with separate admin limit."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._rpm = int(os.environ.get("RATE_LIMIT_RPM", "30"))
        self._admin_rpm = int(os.environ.get("ADMIN_RATE_LIMIT_RPM", "10"))
        self._window = 60.0
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ip = _get_client_ip(request)
        is_admin = request.url.path.startswith("/admin")
        limit = self._admin_rpm if is_admin else self._rpm
        key = f"{'admin:' if is_admin else ''}{ip}"

        now = time.time()
        cutoff = now - self._window
        bucket = self._hits[key]
        self._hits[key] = [t for t in bucket if t > cutoff]

        if len(self._hits[key]) >= limit:
            return Response(
                content='{"error":"Rate limit exceeded. Try again in a minute."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        self._hits[key].append(now)
        return await call_next(request)

    def reset(self) -> None:
        self._hits.clear()
