"""
Budget Analysis Agent for spending analysis and insights
"""
import asyncio
import json
import logging
import os
import uuid
import structlog
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

try:
    from azure.eventhub import EventHubConsumerClient, EventHubProducerClient
    from azure.ai.inference import EmbeddingsClient
    from azure.identity import DefaultAzureCredential
    from opentelemetry.instrumentation.azure import AzureInstrumentor
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    EventHubConsumerClient = None
    EventHubProducerClient = None
    EmbeddingsClient = None
    DefaultAzureCredential = None
    AzureInstrumentor = None

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = structlog.get_logger("budget-service")

# Initialize telemetry
def init_telemetry():
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider = TracerProvider(
            resource=Resource.create({"service.name": "budget-service"})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        if AzureInstrumentor:
            AzureInstrumentor().instrument()

init_telemetry()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Extract or generate X-Correlation-ID for each request."""
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

app = FastAPI(title="Budget Analysis Agent", version="1.0.0")

app.add_middleware(CorrelationIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

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


def init_embeddings_client():
    """Initialize embeddings client for categorization using RBAC"""
    global embeddings_client
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if endpoint and EmbeddingsClient and DefaultAzureCredential:
        embeddings_client = EmbeddingsClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential()
        )


def cosine_similarity(a, b):
    """Calculate cosine similarity between two vectors"""
    import numpy as np
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


async def categorize_transaction(description: str) -> str:
    """Use embeddings to categorize transaction description"""
    if not embeddings_client:
        return "Uncategorized"
    
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("openai.embedding-categorization") as span:
        span.set_attribute("openai.model", os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"))
        span.set_attribute("transaction.description", description[:100])
        
        try:
            # Get embedding for transaction description
            desc_response = embeddings_client.embed(
                model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"),
                input=[description.lower()]
            )
            desc_embedding = desc_response.data[0].embedding
            
            # Compare with category keywords
            best_category = "Uncategorized"
            best_score = 0
            
            for category, keywords in CATEGORIES.items():
                for keyword in keywords:
                    keyword_response = embeddings_client.embed(
                        model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"),
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


class TransactionEvent(BaseModel):
    transactionId: str
    accountId: str
    amount: float
    type: str
    description: str
    category: str
    timestamp: Optional[datetime] = None
    aiCategory: Optional[str] = None


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
    
    except Exception as e:
        logger.error(f"Error processing event: {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize event processor and AI client with validation"""
    init_embeddings_client()
    
    # Validate Entra ID token acquisition for Azure OpenAI (Foundry) Embeddings
    if DefaultAzureCredential and os.getenv("AZURE_OPENAI_ENDPOINT"):
        logger.info("=" * 50)
        logger.info("Validating Azure OpenAI (Foundry) Embeddings connectivity...")
        try:
            credential = DefaultAzureCredential()
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Azure OpenAI token acquired (expires {token.expires_on})")
            
            # Test embeddings connectivity with a simple ping
            if embeddings_client:
                try:
                    test_response = embeddings_client.embed(
                        model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"),
                        input=["ping"]
                    )
                    logger.info(f"✅ Azure OpenAI Embeddings connectivity verified - {len(test_response.data[0].embedding)} dimensions")
                except Exception as ping_ex:
                    logger.warning(f"⚠️ OpenAI Embeddings ping failed: {ping_ex}")
        except Exception as ex:
            logger.error(f"❌ Azure OpenAI token acquisition FAILED: {ex}")
            logger.error("Ensure AZURE_OPENAI_ENDPOINT is set and Managed Identity/Service Principal has Cognitive Services OpenAI User role")
    
    eventhub_conn = os.getenv("EVENTHUB_CONNECTION_STRING")
    eventhub_name = os.getenv("EVENTHUB_NAME", "banking-events")
    
    if eventhub_conn and AZURE_AVAILABLE:
        try:
            client = EventHubConsumerClient.from_connection_string(
                conn_str=eventhub_conn,
                consumer_group="$Default",
                eventhub_name=eventhub_name
            )
            logger.info(f"✅ EventHub client created for '{eventhub_name}' - connectivity verified")
            
            asyncio.create_task(client.receive(
                on_event=process_events,
                max_wait_time=5
            ))
            logger.info("Budget analysis agent started")
        except Exception as eh_ex:
            logger.error(f"❌ EventHub connection FAILED: {eh_ex}")
            logger.error("Ensure EVENTHUB_CONNECTION_STRING is set and Managed Identity has Azure Event Hubs Data Receiver role")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "budget-service", "timestamp": datetime.utcnow().isoformat()}


@app.get("/readyz")
async def ready():
    return {"status": "ready"}


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


@app.post("/categorize")
async def categorize(description: str):
    """Categorize a transaction description"""
    category = await categorize_transaction(description)
    return {"description": description, "category": category}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)