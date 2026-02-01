"""ReceiptGate configuration loaded from environment variables."""

from __future__ import annotations

import os
from typing import Literal
from datetime import datetime, timezone

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ReceiptGate configuration."""

    model_config = SettingsConfigDict(
        env_prefix="RECEIPTGATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service
    service_name: str = Field(default="receiptgate", description="Service name")
    host: str = Field(default="0.0.0.0", description="Server bind address")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Enable debug mode")
    public_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL for MCP clients",
    )
    default_tenant_id: str = Field(
        default="default",
        description="Default tenant identifier for single-tenant deployments",
    )

    # Database
    database_url: str = Field(
        default="sqlite:///./receiptgate.db",
        description="SQLAlchemy database URL",
    )
    auto_migrate_on_startup: bool = Field(
        default=True,
        description="Apply schema files on startup (dev friendly)",
    )
    enable_graph_layer: bool = Field(
        default=True,
        description="Apply graph schema (003) on startup",
    )
    enable_semantic_layer: bool = Field(
        default=False,
        description="Apply embeddings schema (004) on startup",
    )

    # Authentication
    api_key: SecretStr = Field(default=SecretStr(""), description="API key for authentication")
    allow_insecure_dev: bool = Field(
        default=False,
        description="Allow unauthenticated access (dev only)",
    )

    # Receipt validation limits
    receipt_body_max_bytes: int = Field(default=262144, description="Max body size in bytes")
    receipt_chain_max_depth: int = Field(default=2048, description="Max chain traversal depth")
    search_default_limit: int = Field(default=50, description="Default search limit")
    search_max_limit: int = Field(default=500, description="Max search limit")
    enforce_cause_exists: bool = Field(
        default=False,
        description="Require caused_by_receipt_id to exist",
    )

    # CORS configuration
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials in CORS requests")
    cors_allowed_methods: list[str] = Field(
        default=["GET", "POST", "OPTIONS"],
        description="Allowed HTTP methods",
    )
    cors_allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-API-Key"],
        description="Allowed request headers",
    )

    trusted_hosts: list[str] = Field(default_factory=list, description="Trusted hostnames")

    # Logging / privacy
    log_receipt_bodies: bool = Field(
        default=False,
        description="Log receipt bodies (discouraged for sensitive payloads)",
    )

    @property
    def api_key_value(self) -> str:
        return self.api_key.get_secret_value()

    @property
    def db_backend(self) -> Literal["postgres", "sqlite", "other"]:
        url = self.database_url.lower()
        if url.startswith("postgresql"):
            return "postgres"
        if url.startswith("sqlite"):
            return "sqlite"
        return "other"

    @field_validator("database_url", mode="before")
    @classmethod
    def prefer_global_database_url(cls, v: str) -> str:
        """Allow DATABASE_URL to override when RECEIPTGATE_DATABASE_URL is unset."""
        if os.environ.get("RECEIPTGATE_DATABASE_URL"):
            return v
        global_url = os.environ.get("DATABASE_URL")
        return global_url or v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("receipt_body_max_bytes", "receipt_chain_max_depth", "search_default_limit")
    @classmethod
    def validate_positive_ints(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Value must be positive")
        return v

    @field_validator("search_max_limit")
    @classmethod
    def validate_search_limit(cls, v: int, info) -> int:
        default_limit = info.data.get("search_default_limit", 50)
        if v < default_limit:
            raise ValueError("search_max_limit must be >= search_default_limit")
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: SecretStr, info) -> SecretStr:
        allow_insecure = info.data.get("allow_insecure_dev", False)
        key_value = v.get_secret_value() if isinstance(v, SecretStr) else str(v)
        if not key_value and not allow_insecure:
            raise ValueError("api_key is required when allow_insecure_dev=False")
        return v


settings = Settings()


def receiptgate_clock() -> str:
    """Return server clock timestamp for stored_at."""
    return datetime.now(timezone.utc).isoformat()
