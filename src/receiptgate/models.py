"""Pydantic models for ReceiptGate."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., max_length=200)
    queue: Optional[str] = Field(default=None, max_length=200)
    lease_seconds: Optional[int] = Field(default=None, ge=1, le=86400)


class PlanRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(..., max_length=200)
    plan_hash: Optional[str] = Field(default=None, max_length=200)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: Optional[str] = Field(default=None, max_length=200)
    uri: Optional[str] = Field(default=None, max_length=2048)
    digest: Optional[str] = Field(default=None, max_length=200)
    kind: Optional[
        Literal["report", "dataset", "binary", "text", "json", "image", "other"]
    ] = None
    mime: Optional[str] = Field(default=None, max_length=200)
    bytes: Optional[int] = Field(default=None, ge=0)
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def ensure_identifier(self) -> "ArtifactRef":
        if not self.artifact_id and not self.uri:
            raise ValueError("artifact_ref requires artifact_id or uri")
        return self


class CompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "no_output", "partial", "failed"]
    reason: Optional[str] = Field(default=None, max_length=5000)
    metrics: Optional[dict[str, Any]] = None


class EscalationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_receipt_id: str = Field(..., max_length=200)
    parent_obligation_id: str = Field(..., max_length=200)
    child_obligation_id: str = Field(..., max_length=200)
    from_: str = Field(..., max_length=200, alias="from")
    to: str = Field(..., max_length=200)
    reason: str = Field(..., max_length=5000)
    copied_task_id: Optional[str] = Field(default=None, max_length=200)
    context: Optional[dict[str, Any]] = None


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., max_length=5000)
    superseded_by_obligation_id: Optional[str] = Field(default=None, max_length=200)
    superseded_by_receipt_id: Optional[str] = Field(default=None, max_length=200)


class ReceiptBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: Optional[str] = Field(default=None, max_length=2000)
    inputs: Optional[dict[str, Any]] = None
    constraints: Optional[dict[str, Any]] = None
    result: Optional[CompletionResult] = None
    escalation: Optional[EscalationBody] = None
    cancel: Optional[CancelBody] = None


class ReceiptEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(..., max_length=200, pattern=r"^[a-zA-Z0-9._:\-]+$")
    phase: Literal["accepted", "complete", "escalate", "cancel"]
    obligation_id: str = Field(..., max_length=200)
    caused_by_receipt_id: Optional[str] = Field(default=None, max_length=200)
    created_by: str = Field(..., max_length=200)
    recipient: str = Field(..., max_length=200)
    principal: Optional[str] = Field(default=None, max_length=200)
    task_ref: Optional[TaskRef] = None
    plan_ref: Optional[PlanRef] = None
    artifact_refs: Optional[list[ArtifactRef]] = Field(default=None, max_length=100)
    body: ReceiptBody
    created_at: Optional[datetime] = None


class ReceiptAccepted(ReceiptEnvelope):
    phase: Literal["accepted"]


class ReceiptComplete(ReceiptEnvelope):
    phase: Literal["complete"]

    @model_validator(mode="after")
    def validate_complete_payload(self) -> "ReceiptComplete":
        has_artifacts = bool(self.artifact_refs)
        has_result = self.body is not None and self.body.result is not None
        if not has_artifacts and not has_result:
            raise ValueError("complete requires artifact_refs or body.result")
        return self


class ReceiptEscalate(ReceiptEnvelope):
    phase: Literal["escalate"]

    @model_validator(mode="after")
    def validate_escalation(self) -> "ReceiptEscalate":
        if not self.body or not self.body.escalation:
            raise ValueError("escalate requires body.escalation")
        return self


class ReceiptCancel(ReceiptEnvelope):
    phase: Literal["cancel"]

    @model_validator(mode="after")
    def validate_cancel(self) -> "ReceiptCancel":
        if not self.body or not self.body.cancel:
            raise ValueError("cancel requires body.cancel")
        return self


ReceiptCreateRequest = Annotated[
    Union[ReceiptAccepted, ReceiptComplete, ReceiptEscalate, ReceiptCancel],
    Field(discriminator="phase"),
]


class ReceiptPutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=True)
    receipt_id: str
    canonical_hash: str
    created_at: Optional[datetime] = None
    idempotent_replay: bool = Field(default=False)


class ErrorObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: Optional[dict[str, Any]] = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=False)
    error: ErrorObject


class ReceiptRecord(ReceiptEnvelope):
    canonical_hash: str


class ReceiptSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: Optional[str] = None
    obligation_id: Optional[str] = None
    phase: Optional[Literal["accepted", "complete", "escalate", "cancel"]] = None
    recipient: Optional[str] = None
    created_by: Optional[str] = None
    principal: Optional[str] = None
    caused_by_receipt_id: Optional[str] = None
    task_id: Optional[str] = None
    plan_id: Optional[str] = None
    created_at_from: Optional[datetime] = None
    created_at_to: Optional[datetime] = None
    query: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=500)
    offset: Optional[int] = Field(default=0, ge=0)


class ReceiptSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=True)
    count: int
    limit: int
    offset: int
    receipts: list[ReceiptRecord]


class ReceiptChainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=True)
    receipt_id: str
    chain: list[ReceiptRecord]
    truncated: bool = Field(default=False)


class ReceiptInboxItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligation_id: str
    opened_by_receipt_id: str
    opened_by_phase: Literal["accepted", "escalate"]
    receipt: ReceiptRecord
    parent_obligation_id: Optional[str] = None


class ReceiptInboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=True)
    recipient: str
    items: list[ReceiptInboxItem]


class ReceiptStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(default=True)
    total_receipts: int
    by_phase: dict[str, int]
    top_recipients: list[dict[str, Any]]
