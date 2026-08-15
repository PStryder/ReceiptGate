"""
Authentication for ReceiptGate REST API.

Simple API key authentication for protected endpoints.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Header, HTTPException, status
from legivellum.authority import Principal

from receiptgate.config import settings

logger = logging.getLogger(__name__)

API_KEY_PREFIX = "rg_"


def verify_api_key(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
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


def _presented_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return x_api_key


def resolve_principal(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> Principal:
    """Derive the acting principal from the credential, never from the body.

    Governance-critical identity -- who performed a transition, which service
    emitted it, which tenant it belongs to -- must be bound to authentication.
    Previously every one of those was a request-body field: any holder of the
    shared key could submit
    `{phase: "complete", recipient_ai: "agent:finance", source_system: "delegate"}`
    and the ledger recorded a discharge attributed to a component that never
    acted. Receipts are append-only, so there is no way to correct it.

    `RECEIPTGATE_PRINCIPALS` maps credentials to principals, so a deployment can
    issue per-component keys and get per-component identity. It is a JSON object:

        {"<api-key>": {"id": "svc:cognigate", "role": "service",
                       "visibility": "tenant-a"}}

    With a single shared key configured the whole stack still resolves to one
    principal -- which is not per-component identity, but it is honest about
    that rather than believing whatever the body claims.
    """
    presented = _presented_key(authorization, x_api_key)

    mapping = settings.principal_map()
    if presented and presented in mapping:
        entry = mapping[presented]
        return Principal(
            id=entry["id"],
            role=entry.get("role", "service"),
            visibility=entry.get("visibility", settings.default_tenant_id),
        )

    if settings.allow_insecure_dev:
        # Development only. Named so it is obvious in the ledger that these
        # transitions were performed by an unauthenticated caller.
        return Principal(
            id="svc:insecure-dev",
            role="service",
            visibility=settings.default_tenant_id,
        )

    # A valid shared key with no principal mapping: authenticated, but with no
    # identity beyond "holds the key".
    verify_api_key(authorization=authorization, x_api_key=x_api_key)
    return Principal(
        id=settings.service_principal_id,
        role="service",
        visibility=settings.default_tenant_id,
    )
