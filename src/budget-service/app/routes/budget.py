from fastapi import APIRouter, Depends

from app.auth import UserContext, verify_jwt
from app.models import BudgetInsight
from app.services.budget_service import analyze_spending, categorize_transaction, user_transactions

router = APIRouter()


@router.get("/insights/{userId}", response_model=BudgetInsight)
async def get_insights(userId: str, period: str = "30d", user: UserContext = Depends(verify_jwt)):
    """Get spending insights for the authenticated user."""
    # Derive userId from JWT — ignore path param if it doesn't match
    userId = user.user_id
    # Get all transactions for user's accounts (exact userId match only)
    transactions = []
    for accountId, txns in user_transactions.items():
        account_txns = [t for t in txns if t.get("userId") == userId]
        transactions.extend(account_txns)

    insight = analyze_spending(transactions, period)
    insight.userId = userId
    return insight


@router.post("/categorize")
async def categorize(description: str, user: UserContext = Depends(verify_jwt)):
    """Categorize a transaction description."""
    category = await categorize_transaction(description)
    return {"description": description, "category": category}
