from __future__ import annotations

import json

import pytest

from receiptgate.security_middleware import (
    RequestSizeLimitConfig,
    RequestSizeLimitMiddleware,
    SecurityHeadersConfig,
    SecurityHeadersMiddleware,
    load_request_size_limit_config_from_env,
    load_security_headers_config_from_env,
)


def test_load_security_headers_config_from_env(monkeypatch):
    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "false")
    monkeypatch.setenv("SECURITY_HEADERS_REFERRER_POLICY", "strict-origin")
    config = load_security_headers_config_from_env()

    assert config.enabled is False
    assert config.referrer_policy == "strict-origin"


def test_load_request_size_limit_config_from_env(monkeypatch):
    monkeypatch.setenv("REQUEST_SIZE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "123")
    config = load_request_size_limit_config_from_env()

    assert config.enabled is True
    assert config.max_body_bytes == 123


@pytest.mark.asyncio
async def test_security_headers_middleware_injects_headers():
    config = SecurityHeadersConfig(
        enabled=True,
        enable_hsts=True,
        hsts_max_age=60,
        hsts_include_subdomains=True,
        hsts_preload=False,
        referrer_policy="no-referrer",
        frame_options="DENY",
        permissions_policy="geolocation=()",
        content_security_policy=None,
    )

    messages = []

    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": b"{}"})

    middleware = SecurityHeadersMiddleware(app, config)
    scope = {"type": "http", "method": "GET"}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive, send)

    headers = dict(messages[0]["headers"])
    assert b"x-content-type-options" in {k.lower() for k in headers.keys()}
    assert b"strict-transport-security" in {k.lower() for k in headers.keys()}


@pytest.mark.asyncio
async def test_request_size_limit_rejects_large_body():
    config = RequestSizeLimitConfig(enabled=True, max_body_bytes=4)

    async def app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestSizeLimitMiddleware(app, config)

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"12345"}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": "POST", "headers": []}

    await middleware(scope, receive, send)

    assert messages[0]["status"] == 413
    payload = json.loads(messages[1]["body"].decode())
    assert payload["error"] == "request_too_large"
