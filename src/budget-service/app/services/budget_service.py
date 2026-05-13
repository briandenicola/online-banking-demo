import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

import structlog
from opentelemetry import trace

from app.config import DefaultAzureCredential, EmbeddingsClient
from app.models import BudgetInsight

logger = structlog.get_logger("budget-service")

# In-memory storage for transactions (in production, use Cosmos DB)
user_transactions = defaultdict(list)

# AI Client for categorization
embeddings_client = None

# Category definitions for embedding-based classification
CATEGORIES = {
    "Food & Dining": ["restaurant", "dining", "food", "cafe", "coffee", "lunch", "dinner", "takeout"],
    "Shopping": ["store", "shop", "retail", "mall", "purchase", "amazon", "walmart", "target"],
    "Transportation": ["gas", "fuel", "uber", "lyft", "taxi", "transport", "parking", "car"],
    "Entertainment": ["movie", "netflix", "spotify", "game", "entertainment", "streaming"],
    "Bills & Utilities": ["electric", "water", "gas bill", "internet", "phone", "utility"],
    "Healthcare": ["doctor", "medical", "pharmacy", "health", "hospital", "clinic"],
    "Travel": ["hotel", "flight", "airline", "travel", "vacation", "booking"],
    "Income": ["salary", "payroll", "deposit", "income", "transfer from"],
}


def init_embeddings_client() -> None:
    """Initialize embeddings client for categorization using RBAC."""
    global embeddings_client
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if endpoint and EmbeddingsClient and DefaultAzureCredential:
        embeddings_client = EmbeddingsClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential()
        )


def cosine_similarity(a, b):
    """Calculate cosine similarity between two vectors."""
    import numpy as np
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


async def categorize_transaction(description: str) -> str:
    """Use embeddings to categorize transaction description."""
    if not embeddings_client:
        return "Uncategorized"

    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("openai.embedding-categorization") as span:
        span.set_attribute("openai.model", os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"))
        span.set_attribute("transaction.description", description[:100])

        try:
            # Get embedding for transaction description
            desc_response = embeddings_client.embed(
                model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),
                input=[description.lower()]
            )
            desc_embedding = desc_response.data[0].embedding

            # Compare with category keywords
            best_category = "Uncategorized"
            best_score = 0

            for category, keywords in CATEGORIES.items():
                for keyword in keywords:
                    keyword_response = embeddings_client.embed(
                        model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),
                        input=[keyword]
                    )
                    keyword_embedding = keyword_response.data[0].embedding

                    score = cosine_similarity(desc_embedding, keyword_embedding)
                    if score > best_score:
                        best_score = score
                        best_category = category

            span.set_attribute("category.result", best_category)
            span.set_attribute("category.confidence", best_score)

            if best_score > 0.7:
                return best_category
            return "Uncategorized"
        except Exception as e:
            span.record_exception(e)
            logger.error(f"Error categorizing transaction: {e}")
            return "Uncategorized"


def analyze_spending(transactions: list[dict], period: str = "30d") -> BudgetInsight:
    """Analyze spending patterns."""
    if not transactions:
        return BudgetInsight(
            userId="",
            period=period,
            totalSpent=0,
            categoryBreakdown={},
            topCategories=[],
            insights=["No transactions found for analysis"]
        )

    # Filter by period
    cutoff = datetime.utcnow() - timedelta(days=30 if period == "30d" else 7)
    recent_transactions = [
        t for t in transactions
        if datetime.fromisoformat(t.get("timestamp", datetime.utcnow().isoformat())) >= cutoff
    ]

    # Calculate totals
    total_spent = sum(abs(t.get("amount", 0)) for t in recent_transactions if t.get("amount", 0) < 0)

    # Category breakdown
    category_breakdown = defaultdict(float)
    for t in recent_transactions:
        category = t.get("category", "Uncategorized")
        category_breakdown[category] += abs(t.get("amount", 0))

    # Top categories
    top_categories = sorted(category_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]

    # Generate insights
    insights = []
    if total_spent > 5000:
        insights.append(f"High spending this period: ${total_spent:.2f}")
    if "Dining" in category_breakdown and category_breakdown["Dining"] > 500:
        insights.append("Consider reducing dining expenses")
    if "Shopping" in category_breakdown and category_breakdown["Shopping"] > 1000:
        insights.append("High shopping spending detected")

    if not insights:
        insights.append("Spending is within normal range")

    return BudgetInsight(
        userId="",  # Will be set by caller
        period=period,
        totalSpent=total_spent,
        categoryBreakdown=dict(category_breakdown),
        topCategories=top_categories,
        insights=insights
    )


async def process_events(partition_context, event) -> None:
    """Process incoming transaction events."""
    try:
        event_data = event.body_as_str()
        transaction = json.loads(event_data)

        accountId = transaction.get("accountId", "")
        if accountId:
            # Use AI categorization if NeedsCategorization flag is set OR category is missing/generic
            needs_categorization = transaction.get("needsCategorization", False)
            current_category = transaction.get("category", "Uncategorized")

            if needs_categorization or not current_category or current_category == "Uncategorized":
                transaction["aiCategory"] = await categorize_transaction(
                    transaction.get("description", "")
                )

            user_transactions[accountId].append(transaction)
            logger.info(f"Stored transaction for account {accountId}")

        await partition_context.update_checkpoint(event)

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error processing event (malformed data): {e}")
    except Exception as e:
        logger.error(f"Unexpected error processing event: {e}", exc_info=True)
