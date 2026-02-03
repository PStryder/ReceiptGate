from __future__ import annotations

import asyncio
import os

import pytest

from receiptgate.rate_limiter import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimitResult,
    RateLimitRule,
    RateLimitMiddleware,
    build_rate_limiter_from_env,
    load_rate_limit_config_from_env,
)


@pytest.mark.asyncio
async def test_in_memory_rate_limiter_allows_until_limit():
    limiter = InMemoryRateLimiter(max_entries=10)
    rule = RateLimitRule(limit=2, window_seconds=60)

    first = await limiter.allow("key", rule)
    second = await limiter.allow("key", rule)
    third = await limiter.allow("key", rule)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.remaining == 0


def test_load_rate_limit_config_from_env(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_PER_IP", "5")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_WINDOW_SECONDS", "10")
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_COUNT", "1")
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_IPS", "1.1.1.1,2.2.2.2")

    config = load_rate_limit_config_from_env()
    assert config.enabled is False
    assert config.global_ip.limit == 5
    assert config.global_ip.window_seconds == 10
    assert config.trusted_proxy_count == 1
    assert "1.1.1.1" in config.trusted_proxy_ips


def test_build_rate_limiter_from_env_with_missing_redis(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setattr("receiptgate.rate_limiter.redis_async", None)

    config = load_rate_limit_config_from_env()
    limiter = build_rate_limiter_from_env(config)
    assert isinstance(limiter, InMemoryRateLimiter)


def test_rate_limit_middleware_helpers():
    config = RateLimitConfig(
        enabled=True,
        global_ip=RateLimitRule(limit=1, window_seconds=60),
        api_key=RateLimitRule(limit=1, window_seconds=60),
        auth_ip=RateLimitRule(limit=1, window_seconds=60),
        max_cache_entries=10,
        trusted_proxy_count=1,
        trusted_proxy_ips=(),
        redis_fail_open=True,
    )
    limiter = InMemoryRateLimiter()
    middleware = RateLimitMiddleware(app=lambda *_: None, limiter=limiter, config=config)

    headers = [
        (b"authorization", b"Bearer rg_12345678901"),
        (b"x-forwarded-for", b"2.2.2.2, 3.3.3.3"),
    ]
    normalized = middleware._normalize_headers(headers)
    assert normalized["authorization"].startswith("Bearer")
    assert middleware._extract_api_key_prefix(normalized) == "rg_12345678"

    forwarded_ip = middleware._select_forwarded_ip("2.2.2.2, 3.3.3.3")
    assert forwarded_ip == "2.2.2.2"

    client_ip = middleware._get_client_ip(
        {"client": ("1.1.1.1", 1234)},
        normalized,
    )
    assert client_ip == "2.2.2.2"

    assert middleware._is_auth_path("/auth/login") is True
    assert middleware._is_auth_path("/mcp") is False


@pytest.mark.asyncio
async def test_rate_limit_middleware_send_429():
    config = RateLimitConfig(
        enabled=True,
        global_ip=RateLimitRule(limit=1, window_seconds=60),
        api_key=RateLimitRule(limit=1, window_seconds=60),
        auth_ip=RateLimitRule(limit=1, window_seconds=60),
        max_cache_entries=10,
        trusted_proxy_count=0,
        trusted_proxy_ips=(),
        redis_fail_open=True,
    )
    limiter = InMemoryRateLimiter()
    middleware = RateLimitMiddleware(app=lambda *_: None, limiter=limiter, config=config)

    messages = []

    async def send(message):
        messages.append(message)

    result = RateLimitResult(allowed=False, remaining=0, reset_epoch=123, limit=1)
    await middleware._send_429(send, result, "global_ip")

    assert messages[0]["status"] == 429
    header_names = {name for name, _ in messages[0]["headers"]}
    assert b"x-ratelimit-limit" in header_names
