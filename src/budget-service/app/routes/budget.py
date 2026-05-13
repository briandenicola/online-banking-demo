from fastapi import APIRouter, Depends

from app.auth import UserContext, verify_jwt
from typing import Optional

from app.config import EmbeddingsClient
from app.models import BudgetInsight
from app.services.budget_service import (
    BudgetState,
    analyze_spending,
    categorize_transaction,
    get_budget_state,
    get_embeddings_client,
)

router = APIRouter()


@router.get("/insights/{userId}", response_model=BudgetInsight)
async def get_insights(
    userId: str,
    period: str = "30d",
    user: UserContext = Depends(verify_jwt),
    budget_state: BudgetState = Depends(get_budget_state),
):
    """Get spending insights for the authenticated user."""
    # Derive userId from JWT — ignore path param if it doesn't match
    userId = user.user_id
    # Get all transactions for user's accounts (exact userId match only)
    transactions = []
    async with budget_state.lock:
        for accountId, txns in budget_state.user_transactions.items():
            account_txns = [t for t in txns if t.get("userId") == userId]
            transactions.extend(account_txns)

    insight = analyze_spending(transactions, period)
    insight.userId = userId
    return insight


@router.post("/categorize")
async def categorize(
    description: str,
    user: UserContext = Depends(verify_jwt),
    embeddings_client: Optional[EmbeddingsClient] = Depends(get_embeddings_client),
):
    """Categorize a transaction description."""
    category = await categorize_transaction(description, embeddings_client)
    return {"description": description, "category": category}
