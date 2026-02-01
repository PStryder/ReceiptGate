"""ReceiptGate error types and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ReceiptGateError(Exception):
    status_code: int
    code: str
    message: str
    details: Optional[dict[str, Any]] = None


def validation_error(message: str, details: Optional[dict[str, Any]] = None) -> ReceiptGateError:
    return ReceiptGateError(status_code=422, code="VALIDATION_ERROR", message=message, details=details)


def conflict_error(code: str, message: str, details: Optional[dict[str, Any]] = None) -> ReceiptGateError:
    return ReceiptGateError(status_code=409, code=code, message=message, details=details)


def body_too_large(max_bytes: int, size_bytes: int) -> ReceiptGateError:
    return ReceiptGateError(
        status_code=413,
        code="BODY_TOO_LARGE",
        message="Receipt body exceeds maximum size",
        details={"max_bytes": max_bytes, "size_bytes": size_bytes},
    )
