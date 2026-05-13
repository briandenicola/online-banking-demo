from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TransactionEvent(BaseModel):
    transactionId: str = Field(..., min_length=1, max_length=128)
    accountId: str = Field(..., min_length=1, max_length=128)
    amount: float
    type: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., max_length=500)
    category: str = Field(..., max_length=100)
    timestamp: Optional[datetime] = None
    aiCategory: Optional[str] = Field(default=None, max_length=100)


class BudgetInsight(BaseModel):
    userId: str
    period: str
    totalSpent: float
    categoryBreakdown: dict[str, float]
    topCategories: list[tuple[str, float]]
    insights: list[str]
