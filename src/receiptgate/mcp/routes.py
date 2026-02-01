"""HTTP MCP (JSON-RPC) interface for ReceiptGate."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from receiptgate import __version__
from receiptgate.auth import verify_api_key
from receiptgate.config import receiptgate_clock, settings
from receiptgate.db import get_db_session
from receiptgate.ledger_v1 import (
    get_receipt,
    get_receipt_chain,
    list_inbox,
    list_task_receipts,
    search_receipts,
    store_receipt,
)
from receiptgate.validation_v1 import apply_server_fields, validate_receipt_payload


class MCPRequest(BaseModel):
    """JSON-RPC request envelope for MCP."""

    jsonrpc: str = Field(default="2.0")
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: Any = None


MCP_TOOLS = [
    {
        "name": "receiptgate.health",
        "description": "Health check / service info",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "receiptgate.submit_receipt",
        "description": "Store a new receipt",
        "inputSchema": {
            "type": "object",
            "properties": {
                "receipt": {"type": "object", "description": "Receipt payload"},
            },
            "required": ["receipt"],
        },
    },
    {
        "name": "receiptgate.list_inbox",
        "description": "Retrieve active obligations for an agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient_ai": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["recipient_ai"],
        },
    },
    {
        "name": "receiptgate.bootstrap",
        "description": "Initialize session and return inbox/config",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["agent_name", "session_id"],
        },
    },
    {
        "name": "receiptgate.list_task_receipts",
        "description": "Retrieve all receipts for a task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "sort": {"type": "string", "enum": ["asc", "desc"]},
                "include_payload": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "receiptgate.search_receipts",
        "description": "Search receipt headers by task and filters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_task_id": {"type": "string"},
                "phase": {"type": "string"},
                "recipient_ai": {"type": "string"},
                "since": {"type": "string", "description": "ISO timestamp"},
                "limit": {"type": "integer"},
            },
            "required": ["root_task_id"],
        },
    },
    {
        "name": "receiptgate.get_receipt_chain",
        "description": "Retrieve escalation/causation chain",
        "inputSchema": {
            "type": "object",
            "properties": {
                "receipt_id": {"type": "string"},
            },
            "required": ["receipt_id"],
        },
    },
    {
        "name": "receiptgate.get_receipt",
        "description": "Retrieve full receipt payload by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "receipt_id": {"type": "string"},
            },
            "required": ["receipt_id"],
        },
    },
]


def _jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: Any, message: str, details: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(verify_api_key)])


@router.post("")
async def mcp_entry(request: MCPRequest, http_request: Request):
    """Handle MCP JSON-RPC requests."""
    if request.method == "tools/list":
        return _jsonrpc_result(request.id, {"tools": MCP_TOOLS})

    if request.method != "tools/call":
        return _jsonrpc_error(request.id, -32601, f"Method not found: {request.method}")

    params = request.params or {}
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}
    if not tool_name:
        return _jsonrpc_error(request.id, -32602, "Missing tool name")

    db = next(get_db_session())
    tenant_id = settings.default_tenant_id

    try:
        if tool_name == "receiptgate.health":
            return _jsonrpc_result(
                request.id,
                {
                    "status": "healthy",
                    "service": "ReceiptGate",
                    "version": __version__,
                    "instance_id": settings.service_name,
                },
            )

        if tool_name == "receiptgate.submit_receipt":
            receipt = arguments.get("receipt") or {}
            errors = validate_receipt_payload(receipt)
            if errors:
                return _jsonrpc_error(request.id, "validation_failed", "Receipt validation failed", errors)

            stored_at = receiptgate_clock()
            payload = apply_server_fields(receipt, tenant_id=tenant_id, stored_at=stored_at)
            result = store_receipt(db, payload, tenant_id)
            return _jsonrpc_result(request.id, result)

        if tool_name == "receiptgate.list_inbox":
            recipient_ai = arguments.get("recipient_ai")
            if not recipient_ai:
                return _jsonrpc_error(request.id, "validation_failed", "recipient_ai is required")
            limit = int(arguments.get("limit") or settings.search_default_limit)
            return _jsonrpc_result(request.id, list_inbox(db, tenant_id, recipient_ai, limit))

        if tool_name == "receiptgate.bootstrap":
            agent_name = arguments.get("agent_name")
            session_id = arguments.get("session_id")
            if not agent_name or not session_id:
                return _jsonrpc_error(request.id, "validation_failed", "agent_name and session_id are required")
            inbox = list_inbox(db, tenant_id, agent_name, settings.search_default_limit)
            return _jsonrpc_result(
                request.id,
                {
                    "tenant_id": tenant_id,
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "config": {
                        "receipt_schema_version": "1.0",
                        "receiptgate_url": settings.public_url,
                        "capabilities": ["receipts", "audit"],
                    },
                    "inbox": inbox,
                    "recent_context": {
                        "last_10_receipts": [],
                        "recent_patterns": [],
                    },
                },
            )

        if tool_name == "receiptgate.list_task_receipts":
            task_id = arguments.get("task_id")
            if not task_id:
                return _jsonrpc_error(request.id, "validation_failed", "task_id is required")
            sort = arguments.get("sort", "asc")
            include_payload = bool(arguments.get("include_payload", False))
            limit = arguments.get("limit")
            return _jsonrpc_result(
                request.id,
                list_task_receipts(db, tenant_id, task_id, sort, include_payload, limit),
            )

        if tool_name == "receiptgate.search_receipts":
            root_task_id = arguments.get("root_task_id")
            if not root_task_id:
                return _jsonrpc_error(request.id, "validation_failed", "root_task_id is required")
            phase = arguments.get("phase")
            recipient_ai = arguments.get("recipient_ai")
            since = arguments.get("since")
            limit = int(arguments.get("limit") or settings.search_default_limit)
            return _jsonrpc_result(
                request.id,
                search_receipts(
                    db,
                    tenant_id,
                    root_task_id,
                    phase=phase,
                    recipient_ai=recipient_ai,
                    since=since,
                    limit=limit,
                ),
            )

        if tool_name == "receiptgate.get_receipt_chain":
            receipt_id = arguments.get("receipt_id")
            if not receipt_id:
                return _jsonrpc_error(request.id, "validation_failed", "receipt_id is required")
            return _jsonrpc_result(
                request.id,
                get_receipt_chain(db, tenant_id, receipt_id, settings.receipt_chain_max_depth),
            )

        if tool_name == "receiptgate.get_receipt":
            receipt_id = arguments.get("receipt_id")
            if not receipt_id:
                return _jsonrpc_error(request.id, "validation_failed", "receipt_id is required")
            payload = get_receipt(db, tenant_id, receipt_id)
            if payload is None:
                return _jsonrpc_error(request.id, "not_found", "Receipt not found")
            return _jsonrpc_result(request.id, payload)

        return _jsonrpc_error(request.id, "unknown_tool", f"Unknown tool: {tool_name}")
    finally:
        db.close()
