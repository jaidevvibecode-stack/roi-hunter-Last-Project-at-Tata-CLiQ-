"""
backend/main.py
----------------
FastAPI entry point. Every /api/v1 route requires auth (/health is public).
Security posture is fail-closed — see backend/core/settings.py and SECURITY.md.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from backend.api.v1 import (
    attribution,
    data_quality,
    export,
    filters,
    freshness,
    overview,
    products,
    recommendations,
    segments,
    trends,
)
from backend.core.security import SecurityMiddleware, install_error_handlers
from backend.core.settings import get_settings
from backend.schemas.responses import Health


def create_app() -> FastAPI:
    s = get_settings()  # raises on unsafe configuration
    app = FastAPI(
        title="ROI Hunter — SKU-Level Ad Performance API",
        description="Read-only API for per-product Meta ad performance metrics.",
        version="1.0.0",
        docs_url="/docs" if s.is_local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.is_local else None,
    )
    app.add_middleware(SecurityMiddleware, rate_limit_per_minute=s.rate_limit_per_minute,
                       max_param_len=s.max_query_param_length, trust_forwarded_for=s.trust_forwarded_for)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET"], allow_headers=["Authorization", "Content-Type"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.allowed_host_list)
    install_error_handlers(app)

    @app.get("/health", tags=["Health"], response_model=Health)
    def health() -> dict[str, str]:
        return {"status": "ok", "data_source": s.data_source}

    for mod, tag in [
        (freshness, "Freshness"), (overview, "Overview"), (products, "Products"),
        (trends, "Trends"), (filters, "Filters"), (attribution, "Attribution"),
        (segments, "Segments"), (recommendations, "Recommendations"),
        (data_quality, "Data Quality"), (export, "Export"),
    ]:
        app.include_router(mod.router, prefix="/api/v1", tags=[tag])
    return app


app = create_app()
