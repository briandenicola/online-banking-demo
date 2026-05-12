from __future__ import annotations

from datetime import datetime, date, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, AliasChoices


class ApplicationStatus(str, Enum):
    submitted = "submitted"
    document_extraction = "document_extraction"
    identity_verification = "identity_verification"
    compliance_check = "compliance_check"
    approved = "approved"
    rejected = "rejected"
    pending_review = "pending_review"


class Address(BaseModel):
    street: str = Field(..., min_length=1, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    zip: str = Field(..., min_length=3, max_length=20)
    country: str = Field(..., min_length=1, max_length=100)


class Employment(BaseModel):
    employer: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=200)
    annualIncome: float = Field(..., gt=0)


AccountType = Literal["checking", "savings", "both"]
DocumentType = Literal["photo_id", "proof_of_address"]


class ApplicationCreate(BaseModel):
    firstName: str = Field(..., min_length=1, max_length=100)
    lastName: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30, pattern=r"^\+?[\d\s\-().]{7,30}$")
    dateOfBirth: date
    address: Address | str
    employment: Employment | str | None = None
    annualIncome: float | None = Field(default=None, gt=0)
    accountType: AccountType
    ssn: str = Field(pattern=r"^\d{4}$")


class AgentResult(BaseModel):
    agentName: str | None = None
    status: str
    confidence: float = Field(ge=0.0, le=1.0)
    findings: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("findings", "details"),
    )
    reasoning: str | None = None
    timestamp: datetime | None = None

    model_config = {
        "populate_by_name": True,
    }


class AuditEntry(BaseModel):
    timestamp: datetime
    agent: str
    action: str
    details: dict[str, Any] | None = None
    previousState: str
    newState: str


class DocumentMetadata(BaseModel):
    type: DocumentType
    filename: str | None = None
    uploadedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    blobUrl: str


class ApplicationResponse(BaseModel):
    id: str
    status: ApplicationStatus
    createdAt: datetime
    updatedAt: datetime
    formData: dict[str, Any]
    documents: list[DocumentMetadata] = Field(default_factory=list)
    agentResults: list[AgentResult] = Field(default_factory=list)
    auditTrail: list[AuditEntry] = Field(default_factory=list)
