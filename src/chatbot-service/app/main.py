"""
AI-powered financial advice chatbot using Microsoft Agent Framework.

Uses agent-framework-foundry:
- FoundryChatClient for Azure AI Foundry model access
- Agent with @tool-decorated functions for financial data
- AgentSession for multi-turn conversation history
"""
import logging
from datetime import datetime, timezone
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Optional

import httpx
import structlog

try:
    from agent_framework import Agent, tool
    from agent_framework.foundry import FoundryChatClient
    from azure.identity import DefaultAzureCredential
    AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:
    AGENT_FRAMEWORK_AVAILABLE = False
    Agent = None
    FoundryChatClient = None
    DefaultAzureCredential = None

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, Field
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
logger = structlog.get_logger("chatbot-service")

FINANCIAL_ADVISOR_INSTRUCTIONS = (
    "You are a helpful financial advisor agent for an online banking application. "
    "Provide concise, actionable financial advice. "
    "Never provide specific investment recommendations. "
    "Use the available tools to get budget insights, spending patterns, and analyze transactions. "
    "Always cite data from tools when providing advice."
)


# Initialize telemetry
def init_telemetry():
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider = TracerProvider(
            resource=Resource.create({"service.name": "chatbot-service"})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

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


# --- Agent Framework tool functions ---
BUDGET_SERVICE_URL = os.getenv("BUDGET_SERVICE_URL", "http://budget-service:8003")


@tool(approval_mode="never_require")
def get_budget_insights(
    user_id: Annotated[str, Field(description="The user ID to get budget insights for")],
    period: Annotated[str, Field(description="Time period (e.g. '7d', '30d')")] = "30d",
) -> str:
    """Get budget insights including spending breakdown and savings rate for a user."""
    try:
        response = httpx.get(f"{BUDGET_SERVICE_URL}/insights/{user_id}?period={period}", timeout=10.0)
        if response.ok:
            return json.dumps(response.json())
    except Exception as e:
        logger.warning(f"Failed to get budget insights: {e}")
    return json.dumps({"error": "Unable to retrieve budget insights"})


@tool(approval_mode="never_require")
def get_spending_pattern(
    user_id: Annotated[str, Field(description="The user ID to analyze spending for")],
) -> str:
    """Get recent spending patterns and trends for a user over the last 7 days."""
    try:
        response = httpx.get(f"{BUDGET_SERVICE_URL}/insights/{user_id}?period=7d", timeout=10.0)
        if response.ok:
            return json.dumps(response.json())
    except Exception as e:
        logger.warning(f"Failed to get spending patterns: {e}")
    return json.dumps({"error": "Unable to retrieve spending patterns"})


@tool(approval_mode="never_require")
def analyze_transaction(
    description: Annotated[str, Field(description="Transaction description text")],
    amount: Annotated[float, Field(description="Transaction amount in dollars")],
) -> str:
    """Analyze and categorize a transaction for budgeting purposes."""
    try:
        response = httpx.post(f"{BUDGET_SERVICE_URL}/categorize", params={"description": description}, timeout=10.0)
        if response.ok:
            data = response.json()
            return json.dumps({
                "description": description,
                "amount": amount,
                "suggested_category": data.get("category", "Uncategorized"),
                "note": "Transaction analyzed successfully",
            })
    except Exception as e:
        logger.warning(f"Failed to analyze transaction: {e}")
    return json.dumps({"error": "Unable to analyze transaction"})


# Globals
financial_agent: Optional["Agent"] = None
agent_ready: bool = False
model_name: str = ""

# In-memory sessions per user (maps user_id -> AgentSession)
user_sessions: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global financial_agent, agent_ready, model_name

    logger.info("=" * 60)
    logger.info("🤖 Chatbot Service — Startup (Microsoft Agent Framework)")
    logger.info("=" * 60)

    # Support both FOUNDRY_PROJECT_ENDPOINT and legacy AZURE_OPENAI_ENDPOINT
    endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("AZURE_AI_AGENTS_ENDPOINT")
        or os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    model_name = os.getenv("FOUNDRY_MODEL") or os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4-mini")

    logger.info(f"  Endpoint: {endpoint or '❌ NOT SET'}")
    logger.info(f"  Model: {model_name}")
    logger.info(f"  AZURE_TENANT_ID: {'✅ set' if os.getenv('AZURE_TENANT_ID') else '❌ not set'}")
    logger.info(f"  AZURE_CLIENT_ID: {'✅ set' if os.getenv('AZURE_CLIENT_ID') else '❌ not set'}")
    logger.info(f"  AGENT_FRAMEWORK_AVAILABLE: {AGENT_FRAMEWORK_AVAILABLE}")

    if not endpoint:
        logger.warning("⚠️  No Azure endpoint configured — chatbot will return 503 on requests")
    elif not AGENT_FRAMEWORK_AVAILABLE:
        logger.warning("⚠️  agent-framework SDK not installed — chatbot will return 503 on requests")
    else:
        logger.info("🔐 Acquiring Azure credential...")
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Token acquired (expires: {token.expires_on})")
        except Exception as ex:
            logger.error(f"❌ Credential acquisition FAILED: {ex}")
            logger.info("=" * 60)
            yield
            return

        logger.info(f"🔌 Creating FoundryChatClient → {endpoint}")
        try:
            client = FoundryChatClient(
                project_endpoint=endpoint,
                model=model_name,
                credential=credential,
            )

            financial_agent = Agent(
                client=client,
                name="FinancialAdvisor",
                instructions=FINANCIAL_ADVISOR_INSTRUCTIONS,
                tools=[get_budget_insights, get_spending_pattern, analyze_transaction],
            )
            agent_ready = True
            logger.info("🟢 Agent ready — accepting requests")
        except Exception as ex:
            logger.error(f"❌ Failed to create agent: {ex}")
            logger.info("=" * 60)
            yield
            return

    logger.info("=" * 60)
    yield
    logger.info("🛑 Chatbot service shutting down")


app = FastAPI(title="Chatbot Service", version="2.0.0", lifespan=lifespan)

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


class ChatRequest(BaseModel):
    message: str
    user_id: str
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    response: str
    suggestions: list[str] = Field(default_factory=list)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Get financial advice from the AI agent."""
    if not agent_ready or not financial_agent:
        raise HTTPException(
            status_code=503,
            detail="Azure AI Foundry not configured. Set FOUNDRY_PROJECT_ENDPOINT or AZURE_OPENAI_ENDPOINT.",
        )

    tracer = trace.get_tracer(__name__)

    try:
        with tracer.start_as_current_span("ai-agent.chat") as span:
            span.set_attribute("agent.name", "FinancialAdvisor")
            span.set_attribute("agent.model", model_name)
            span.set_attribute("user.id", request.user_id)
            span.set_attribute("user.message", request.message[:100])

            user_content = request.message
            if request.context:
                user_content = f"Context: {request.context}\n\nQuestion: {request.message}"

            # Get or create a session for multi-turn conversation
            if request.user_id not in user_sessions:
                user_sessions[request.user_id] = financial_agent.create_session()

            session = user_sessions[request.user_id]

            result = await financial_agent.run(user_content, session=session)
            answer = str(result) if result else "I couldn't generate a response at this time."

            span.set_attribute("response.length", len(answer))

        suggestions = [
            "How can I save more each month?",
            "What's my spending pattern?",
            "Should I consider a budget?",
        ]

        return ChatResponse(response=answer, suggestions=suggestions)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in agent chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/new", response_model=ChatResponse)
async def chat_new_session(request: ChatRequest):
    """Start a new chat session (clears conversation history for this user)."""
    user_sessions.pop(request.user_id, None)
    return await chat(request)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "agent_ready": agent_ready,
        "model": model_name,
        "sdk_available": AGENT_FRAMEWORK_AVAILABLE,
    }


@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "chatbot-service", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/readyz")
async def ready():
    checks = {"azure_credential": False, "agent_ready": agent_ready}

    if AGENT_FRAMEWORK_AVAILABLE and DefaultAzureCredential:
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            checks["azure_credential"] = token is not None
        except Exception:
            checks["azure_credential"] = False
    else:
        checks["azure_credential"] = None

    all_ready = checks.get("azure_credential") is not False and checks["agent_ready"]
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)