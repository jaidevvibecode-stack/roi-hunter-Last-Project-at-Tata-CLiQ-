"""
backend/core/security.py
-------------------------
Security middleware: headers, per-IP rate limit, query-param length cap,
generic error handler (no stack traces leak to clients).
"""
from __future__ import annotations

import ipaddress
import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

log = logging.getLogger("security")
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityMiddleware(BaseHTTPMiddleware):
    MAX_TRACKED_CLIENTS = 10_000

    def __init__(self, app: ASGIApp, rate_limit_per_minute: int, max_param_len: int, trust_forwarded_for: bool = False) -> None:
        super().__init__(app)
        self.trust_forwarded_for = trust_forwarded_for
        self.limit = rate_limit_per_minute
        self.max_param_len = max_param_len
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def client_ip(self, request: Request) -> str:
        if self.trust_forwarded_for:
            first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            try:
                return str(ipaddress.ip_address(first))
            except ValueError:
                pass  # missing / malformed -> fall back to the socket address
        return request.client.host if request.client else "unknown"

    def _rate_limited(self, ip: str) -> bool:
        now = time.monotonic()
        if len(self._hits) > self.MAX_TRACKED_CLIENTS:  # bound memory: drop clients idle for > 60s
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                del self._hits[k]
        q = self._hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.limit:
            return True
        q.append(now)
        return False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ip = self.client_ip(request)
        if request.url.path != "/health" and self._rate_limited(ip):
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        for _k, v in request.query_params.multi_items():
            if len(v) > self.max_param_len:
                return JSONResponse({"detail": "Query parameter too long"}, status_code=414)

        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Cache-Control"] = "no-store"
        h["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if not request.url.path.startswith(_DOC_PATHS):
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        log.exception("unhandled error on %s", request.url.path)  # details only in server logs
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
