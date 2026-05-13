from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    """Result of analyzing a single transaction for risk."""
    riskScore: float = Field(ge=0.0, le=1.0, description="Risk score 0.0 (safe) to 1.0 (critical)")
    explanation: str = Field(description="Human-readable explanation of the risk assessment")
    flags: list[str] = Field(default_factory=list, description="Risk flag categories detected")


class CategoryResult(BaseModel):
    """Result of AI-powered transaction categorization."""
    category: str = Field(description="Assigned category (e.g., Groceries, Entertainment)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the categorization")
    reasoning: str = Field(default="", description="Brief explanation of why this category was chosen")


class ScoredTransaction(BaseModel):
    """A transaction with its AI risk assessment and categorization."""
    id: str
    transactionId: str
    accountId: str
    userId: str = ""
    amount: float
    type: str
    description: str
    category: str = ""
    categoryConfidence: float = 0.0
    categoryReasoning: str = ""
    riskScore: float
    explanation: str
    flags: list[str] = []
    scoredAt: str
    status: str = "scored"
    notes: Optional[str] = None


class FlaggedTransaction(BaseModel):
    """A high-risk transaction requiring admin review."""
    id: str
    transactionId: str
    accountId: str
    amount: float
    type: str
    riskScore: float
    reason: str
    flags: list[str] = []
    flaggedAt: str
    status: str = "pending"
    notes: Optional[str] = None


class AdminStats(BaseModel):
    totalFlagged: int
    pendingReview: int
    reviewed: int
    cleared: int
    avgRiskScore: float
    totalScored: int
    highRiskCount: int
    aiCallsToday: int


class ReviewRequest(BaseModel):
    status: str = Field(..., pattern=r"^(reviewed|cleared)$")
    notes: str = Field(..., min_length=1, max_length=2000)


class DetectRequest(BaseModel):
    """Strict schema for synchronous transaction detection."""
    transactionId: str = Field(..., min_length=1, max_length=128, description="Transaction identifier")
    accountId: str = Field(..., min_length=1, max_length=128, description="Account identifier")
    amount: float = Field(..., description="Transaction amount")
    type: str = Field(..., min_length=1, max_length=50, description="Transaction type (e.g. Debit, Credit, Transfer)")
    description: str = Field(default="", max_length=500, description="Transaction description")
    category: str = Field(default="", max_length=100, description="Transaction category")


class EvalRequest(BaseModel):
    """Request to run a Foundry evaluation."""
    eval_name: str = Field(..., min_length=1, max_length=200, description="Display name for the evaluation run")
    system_prompt: str = Field(..., min_length=1, max_length=10000, description="System prompt to evaluate")
    transactions: list[dict] = Field(..., min_length=1, max_length=100, description="List of transaction dicts to test against")
    evaluators: list[str] = Field(
        default=["coherence", "fluency", "relevance"],
        min_length=1,
        max_length=20,
        description="Foundry evaluator names (short form preferred, e.g. 'coherence' not 'builtin.coherence')"
    )
