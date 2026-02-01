"""
Authentication for ReceiptGate REST API.

Simple API key authentication for protected endpoints.
"""

from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

from receiptgate.config import settings

logger = logging.getLogger(__name__)

API_KEY_PREFIX = "rg_"


def verify_api_key(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> bool:
    """Verify API key for protected endpoints."""
    if settings.allow_insecure_dev:
        return True

    api_key = None
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]
    elif x_api_key:
        api_key = x_api_key

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization. Use Authorization: Bearer <key> or X-API-Key header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    configured = settings.api_key_value
    if not configured:
        logger.error(
            "SECURITY VIOLATION: api_key not configured. "
            "Set RECEIPTGATE_API_KEY or enable RECEIPTGATE_ALLOW_INSECURE_DEV=true (dev only)."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfigured: authentication not properly initialized",
        )

    if not secrets.compare_digest(api_key, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


def generate_api_key() -> str:
    """Generate a new API key with rg_ prefix."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
