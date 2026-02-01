"""Middleware configuration for ReceiptGate."""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from receiptgate.config import settings
from receiptgate.rate_limiter import (
    RateLimitMiddleware,
    build_rate_limiter_from_env,
    load_rate_limit_config_from_env,
)
from receiptgate.security_middleware import (
    RequestSizeLimitConfig,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    load_security_headers_config_from_env,
)


def configure_middleware(app):
    """Configure security, rate limiting, and CORS middleware for ReceiptGate."""
    rate_limit_config = load_rate_limit_config_from_env()
    rate_limiter = build_rate_limiter_from_env(rate_limit_config)

    request_size_config = RequestSizeLimitConfig(
        enabled=True,
        max_body_bytes=settings.receipt_body_max_bytes,
    )
    security_headers_config = load_security_headers_config_from_env()

    app.add_middleware(
        RequestSizeLimitMiddleware,
        config=request_size_config,
    )

    app.add_middleware(
        RateLimitMiddleware,
        limiter=rate_limiter,
        config=rate_limit_config,
    )

    app.add_middleware(
        SecurityHeadersMiddleware,
        config=security_headers_config,
    )

    if settings.trusted_hosts:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_hosts,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allowed_methods,
        allow_headers=settings.cors_allowed_headers,
    )

    return rate_limiter
