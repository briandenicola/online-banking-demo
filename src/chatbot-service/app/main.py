"""
AI-powered financial advice chatbot service using Azure AI Foundry Agents.

Uses the azure-ai-projects SDK with the OpenAI Responses API to reference
a pre-created agent in Azure AI Foundry (not created at runtime).
"""
import logging
from datetime import datetime, timezone
import os
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import structlog

try:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
    AZURE_PROJECTS_AVAILABLE = True
except ImportError:
    AZURE_PROJECTS_AVAILABLE = False
    AIProjectClient = None
    DefaultAzureCredential = None

try:
    from opentelemetry.instrumentation.azure import AzureInstrumentor
except ImportError:
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

# System instructions for the financial advisor agent
FINANCIAL_ADVISOR_INSTRUCTIONS = (
    "You are a helpful financial advisor agent. "
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


# OpenAI client (obtained from AIProjectClient)
openai_client = None
agent_name = None
agent_version = None

# In-memory conversation history per user (list of message dicts)
user_conversations: dict[str, list[dict]] = defaultdict(list)


def get_budget_insights(user_id: str, period: str = "30d") -> dict:
    """Get budget insights for a user - financial advisor tool"""
    try:
        budget_service_url = os.getenv("BUDGET_SERVICE_URL", "http://budget-service:8003")
        response = httpx.get(f"{budget_service_url}/insights/{user_id}?period={period}", timeout=10.0)
        if response.ok:
            return response.json()
    except Exception as e:
        logger.warning(f"Failed to get budget insights: {e}")
    raise ValueError("Unable to retrieve budget insights")


def get_spending_pattern(user_id: str) -> dict:
    """Get spending patterns for a user - financial advisor tool"""
    try:
        budget_service_url = os.getenv("BUDGET_SERVICE_URL", "http://budget-service:8003")
        response = httpx.get(f"{budget_service_url}/insights/{user_id}?period=7d", timeout=10.0)
        if response.ok:
            return response.json()
    except Exception as e:
        logger.warning(f"Failed to get spending patterns: {e}")
    raise ValueError("Unable to retrieve spending patterns")


def analyze_transaction(description: str, amount: float) -> dict:
    """Analyze a transaction for budgeting - financial advisor tool"""
    try:
        budget_service_url = os.getenv("BUDGET_SERVICE_URL", "http://budget-service:8003")
        response = httpx.post(f"{budget_service_url}/categorize", params={"description": description}, timeout=10.0)
        if response.ok:
            data = response.json()
            return {
                "description": description,
                "amount": amount,
                "suggested_category": data.get("category", "Uncategorized"),
                "note": "Transaction analyzed successfully"
            }
    except Exception as e:
        logger.warning(f"Failed to analyze transaction: {e}")
    raise ValueError("Unable to analyze transaction")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global openai_client, agent_name, agent_version

    logger.info("=" * 60)
    logger.info("🤖 Chatbot Service — Startup")
    logger.info("=" * 60)

    endpoint = os.getenv("AZURE_AI_AGENTS_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
    agent_name = os.getenv("AZURE_AGENT_NAME", "financial-advisor-agent")
    agent_version = os.getenv("AZURE_AGENT_VERSION", "1")

    logger.info(f"  AZURE_AI_AGENTS_ENDPOINT: {endpoint or '❌ NOT SET'}")
    logger.info(f"  AZURE_AGENT_NAME: {agent_name}")
    logger.info(f"  AZURE_AGENT_VERSION: {agent_version}")
    logger.info(f"  AZURE_TENANT_ID: {'✅ set' if os.getenv('AZURE_TENANT_ID') else '❌ not set'}")
    logger.info(f"  AZURE_CLIENT_ID: {'✅ set' if os.getenv('AZURE_CLIENT_ID') else '❌ not set'}")
    logger.info(f"  AZURE_CLIENT_SECRET: {'✅ set' if os.getenv('AZURE_CLIENT_SECRET') else '❌ not set'}")
    logger.info(f"  AZURE_PROJECTS_AVAILABLE (SDK): {AZURE_PROJECTS_AVAILABLE}")

    if not endpoint:
        logger.warning("⚠️  No Azure endpoint configured — chatbot will return 503 on requests")
    elif not AZURE_PROJECTS_AVAILABLE:
        logger.warning("⚠️  azure-ai-projects SDK not installed — chatbot will return 503 on requests")
    else:
        logger.info("🔐 Acquiring Azure credential...")
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Token acquired successfully (expires: {token.expires_on})")
        except Exception as ex:
            logger.error(f"❌ Credential acquisition FAILED: {ex}")
            logger.error("   Check AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET are correct")
            logger.info("=" * 60)
            yield
            return

        logger.info(f"🔌 Connecting to Azure AI Foundry at: {endpoint}")
        try:
            project_client = AIProjectClient(
                endpoint=endpoint,
                credential=credential,
            )
            openai_client = project_client.get_openai_client()
            logger.info("✅ AIProjectClient + OpenAI client created")
            logger.info(f"🔗 Referencing agent: {agent_name} (v{agent_version})")
            logger.info("🟢 Chatbot service READY — accepting requests")
        except Exception as ex:
            logger.error(f"❌ Failed to create AIProjectClient: {ex}")
            logger.info("=" * 60)
            yield
            return

    logger.info("=" * 60)

    yield

    # No cleanup needed — agent is pre-created in Foundry, not managed at runtime
    logger.info("🛑 Chatbot service shutting down")


app = FastAPI(title="Chatbot Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(CorrelationIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize instrumentation
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
    if not openai_client:
        raise HTTPException(
            status_code=503,
            detail="Azure AI Foundry not configured. Set AZURE_AI_AGENTS_ENDPOINT environment variable."
        )

    tracer = trace.get_tracer(__name__)

    try:
        with tracer.start_as_current_span("ai-agent.chat") as span:
            span.set_attribute("agent.name", agent_name)
            span.set_attribute("agent.version", agent_version)
            span.set_attribute("user.id", request.user_id)
            span.set_attribute("user.message", request.message[:100])

            # Build input messages: system instructions + conversation history + new user message
            messages: list[dict] = [
                {"role": "system", "content": FINANCIAL_ADVISOR_INSTRUCTIONS},
            ]

            # Append prior conversation history for this user
            messages.extend(user_conversations[request.user_id])

            # Add the new user message (with optional context)
            user_content = request.message
            if request.context:
                user_content = f"Context: {request.context}\n\nQuestion: {request.message}"

            messages.append({"role": "user", "content": user_content})

            # Call the Responses API referencing the pre-created Foundry agent
            response = openai_client.responses.create(
                input=messages,
                extra_body={
                    "agent_reference": {
                        "name": agent_name,
                        "version": agent_version,
                        "type": "agent_reference",
                    }
                },
            )

            answer = response.output_text or "I couldn't generate a response at this time."
            span.set_attribute("response.length", len(answer))

            # Store conversation turn in history
            user_conversations[request.user_id].append({"role": "user", "content": user_content})
            user_conversations[request.user_id].append({"role": "assistant", "content": answer})

            # Cap history to last 20 messages to prevent unbounded growth
            if len(user_conversations[request.user_id]) > 20:
                user_conversations[request.user_id] = user_conversations[request.user_id][-20:]

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
    """Start a new chat session (clears conversation history)."""
    user_conversations.pop(request.user_id, None)
    return await chat(request)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "agent_name": agent_name,
        "agent_version": agent_version,
        "sdk_available": AZURE_PROJECTS_AVAILABLE,
    }


@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "chatbot-service", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/readyz")
async def ready():
    checks = {"azure_credential": False, "openai_client_ready": openai_client is not None}

    if AZURE_PROJECTS_AVAILABLE and DefaultAzureCredential:
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            checks["azure_credential"] = token is not None
        except Exception:
            checks["azure_credential"] = False
    else:
        checks["azure_credential"] = None  # Not configured

    all_ready = checks.get("azure_credential") is not False and checks["openai_client_ready"]
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)