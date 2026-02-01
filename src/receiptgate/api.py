"""ReceiptGate API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from receiptgate.auth import verify_api_key
from receiptgate.config import settings
from receiptgate.db import get_db_session
from receiptgate.models import (
    ReceiptChainResponse,
    ReceiptCreateRequest,
    ReceiptInboxResponse,
    ReceiptPutResponse,
    ReceiptRecord,
    ReceiptSearchRequest,
    ReceiptSearchResponse,
    ReceiptStatsResponse,
)
from receiptgate.receipts import (
    chain_for_receipt,
    get_receipt,
    inbox_for_recipient,
    put_receipt,
    search_receipts,
    stats,
)


router = APIRouter()


@router.post(
    "/receipts",
    response_model=ReceiptPutResponse,
    responses={200: {"model": ReceiptPutResponse}},
)
def receipts_put(
    receipt: ReceiptCreateRequest,
    db=Depends(get_db_session),
    _auth: bool = Depends(verify_api_key),
):
    response, status_code = put_receipt(db, receipt)
    if status_code == 200:
        return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
    return response


@router.get("/receipts/{receipt_id}", response_model=ReceiptRecord)
def receipts_get(
    receipt_id: str,
    db=Depends(get_db_session),
    _auth: bool = Depends(verify_api_key),
):
    record = get_receipt(db, receipt_id)
    if not record:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return record


@router.post("/receipts/search", response_model=ReceiptSearchResponse)
def receipts_search(
    request: ReceiptSearchRequest,
    db=Depends(get_db_session),
    _auth: bool = Depends(verify_api_key),
):
    return search_receipts(db, request)


@router.get("/receipts/{receipt_id}/chain", response_model=ReceiptChainResponse)
def receipts_chain(
    receipt_id: str,
    db=Depends(get_db_session),
    _auth: bool = Depends(verify_api_key),
):
    response = chain_for_receipt(db, receipt_id)
    if not response.chain:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return response


@router.get("/inbox/{recipient}", response_model=ReceiptInboxResponse)
def receipts_inbox(
    recipient: str,
    limit: int = Query(default=settings.search_default_limit, ge=1, le=settings.search_max_limit),
    db=Depends(get_db_session),
    _auth: bool = Depends(verify_api_key),
):
    return inbox_for_recipient(db, recipient, limit=limit)


@router.get("/receipts/stats", response_model=ReceiptStatsResponse)
def receipts_stats(
    db=Depends(get_db_session),
    _auth: bool = Depends(verify_api_key),
):
    return stats(db)


@router.get("/health")
def health():
    return {"ok": True, "service": settings.service_name}
