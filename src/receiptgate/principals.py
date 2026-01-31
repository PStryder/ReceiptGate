"""Canonical principal identifiers for ReceiptGate."""

SYSTEM_PRINCIPAL_ID = "sys:legivellum"
SERVICE_PRINCIPAL_ID = "svc:receiptgate"
INTERNAL_PRINCIPAL_PREFIXES = ("sys:", "svc:")


def is_internal_principal(principal_id: str) -> bool:
    return principal_id.startswith(INTERNAL_PRINCIPAL_PREFIXES)
