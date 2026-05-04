"""
Budget Analysis Agent for spending analysis and insights
"""
import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

try:
    from azure.eventhub import EventHubConsumerClient, EventHubProducerClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    EventHubConsumerClient = None
    EventHubProducerClient = None

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize telemetry
def init_telemetry():
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        exporter = OTLPSpanExporter(
            endpoint="https://dc.services.visualstudio.com/v2/track",
            headers={"Authorization": f"InstrumentationKey={os.getenv('APPINSIGHTS_INSTRUMENTATIONKEY')}"}
        )
        provider = TracerProvider(
            resource=Resource.create({"service.name": "budget-service"})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

init_telemetry()

app = FastAPI(title="Budget Analysis Agent", version="1.0.0")
FastAPIInstrumentor.instrument_app(app)

# In-memory storage for transactions (in production, use Cosmos DB)
user_transactions = defaultdict(list)


class TransactionEvent(BaseModel):
    transactionId: str
    accountId: str
    amount: float
    type: str
    description: str
    category: str
    timestamp: Optional[datetime] = None


class BudgetInsight(BaseModel):
    userId: str
    period: str
    totalSpent: float
    categoryBreakdown: dict[str, float]
    topCategories: list[tuple[str, float]]
    insights: list[str]


def analyze_spending(transactions: list[dict], period: str = "30d") -> BudgetInsight:
    """Analyze spending patterns"""
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


async def process_events(partition_context, event):
    """Process incoming transaction events"""
    try:
        event_data = event.body_as_str()
        transaction = json.loads(event_data)
        
        accountId = transaction.get("accountId", "")
        if accountId:
            user_transactions[accountId].append(transaction)
            logger.info(f"Stored transaction for account {accountId}")
        
        await partition_context.update_checkpoint(event)
    
    except Exception as e:
        logger.error(f"Error processing event: {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize event processor"""
    eventhub_conn = os.getenv("EVENTHUB_CONNECTION_STRING")
    eventhub_name = os.getenv("EVENTHUB_NAME", "banking-events")
    
    if eventhub_conn and AZURE_AVAILABLE:
        client = EventHubConsumerClient.from_connection_string(
            conn_str=eventhub_conn,
            consumer_group="$Default",
            eventhub_name=eventhub_name
        )
        
        asyncio.create_task(client.receive(
            on_event=process_events,
            max_wait_time=5
        ))
        logger.info("Budget analysis agent started")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/insights/{userId}", response_model=BudgetInsight)
async def get_insights(userId: str, period: str = "30d"):
    """Get spending insights for a user"""
    # Get all transactions for user's accounts
    transactions = []
    for accountId, txns in user_transactions.items():
        if accountId.startswith(userId[:8]):  # Simple matching
            transactions.extend(txns)
    
    insight = analyze_spending(transactions, period)
    insight.userId = userId
    return insight


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)