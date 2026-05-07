"""
AI-powered financial advice chatbot service using Azure AI Foundry Agents.

Creates the agent programmatically at startup via `project_client.agents`
and tears it down on shutdown. Chat uses the agents threads/runs pattern.
"""
import logging
from datetime import datetime, timezone
import os
import uuid
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


# Globals for the programmatically-created agent
project_client: Optional[AIProjectClient] = None
agent_id: Optional[str] = None
agent_name: Optional[str] = None

# In-memory conversation threads per user (maps user_id -> thread_id)
user_threads: dict[str, str] = {}


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
    global project_client, agent_id, agent_name

    logger.info("=" * 60)
    logger.info("🤖 Chatbot Service — Startup")
    logger.info("=" * 60)

    endpoint = os.getenv("AZURE_AI_AGENTS_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
    agent_name = os.getenv("AZURE_AGENT_NAME", "financial-advisor-agent")
    model = os.getenv("AZURE_OPENAI_MODEL", "gpt-4o")

    logger.info(f"  AZURE_AI_AGENTS_ENDPOINT: {endpoint or '❌ NOT SET'}")
    logger.info(f"  AZURE_AGENT_NAME: {agent_name}")
    logger.info(f"  AZURE_OPENAI_MODEL: {model}")
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
            logger.info("✅ AIProjectClient created")
        except Exception as ex:
            logger.error(f"❌ Failed to create AIProjectClient: {ex}")
            logger.info("=" * 60)
            yield
            return

        logger.info(f"🤖 Creating agent '{agent_name}' with model '{model}'...")
        try:
            agent = project_client.agents.create_agent(
                model=model,
                name=agent_name,
                instructions=FINANCIAL_ADVISOR_INSTRUCTIONS,
            )
            agent_id = agent.id
            logger.info(f"✅ Agent created: id={agent_id}")
            logger.info("🟢 Chatbot service READY — accepting requests")
        except Exception as ex:
            logger.error(f"❌ Failed to create agent: {ex}")
            project_client = None
            logger.info("=" * 60)
            yield
            return

    logger.info("=" * 60)

    yield

    # Shutdown: delete the programmatically-created agent
    if agent_id and project_client:
        logger.info(f"🗑️  Deleting agent {agent_id}...")
        try:
            project_client.agents.delete_agent(agent_id)
            logger.info("✅ Agent deleted")
        except Exception as ex:
            logger.warning(f"⚠️  Failed to delete agent on shutdown: {ex}")

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
    if not project_client or not agent_id:
        raise HTTPException(
            status_code=503,
            detail="Azure AI Foundry not configured. Set AZURE_AI_AGENTS_ENDPOINT environment variable."
        )

    tracer = trace.get_tracer(__name__)

    try:
        with tracer.start_as_current_span("ai-agent.chat") as span:
            span.set_attribute("agent.name", agent_name or "")
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("user.id", request.user_id)
            span.set_attribute("user.message", request.message[:100])

            user_content = request.message
            if request.context:
                user_content = f"Context: {request.context}\n\nQuestion: {request.message}"

            # Reuse or create a thread for this user
            thread_id = user_threads.get(request.user_id)
            if not thread_id:
                thread = project_client.agents.threads.create()
                thread_id = thread.id
                user_threads[request.user_id] = thread_id

            # Add the user message to the thread
            project_client.agents.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_content,
            )

            # Run the agent on the thread
            run = project_client.agents.runs.create_and_process(
                thread_id=thread_id,
                agent_id=agent_id,
            )

            if run.status != "completed":
                logger.error(f"Agent run failed: status={run.status}, error={run.last_error}")
                raise HTTPException(status_code=500, detail="Agent run did not complete successfully.")

            # Retrieve the assistant's latest response
            messages = project_client.agents.messages.list(thread_id=thread_id, order="desc", limit=1)
            answer = "I couldn't generate a response at this time."
            for msg in messages.data:
                if msg.role == "assistant":
                    # Extract text from content blocks
                    for block in msg.content:
                        if hasattr(block, "text"):
                            answer = block.text.value
                            break
                    break

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
    """Start a new chat session (creates a fresh thread for this user)."""
    user_threads.pop(request.user_id, None)
    return await chat(request)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "agent_name": agent_name,
        "agent_id": agent_id,
        "sdk_available": AZURE_PROJECTS_AVAILABLE,
    }


@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "chatbot-service", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/readyz")
async def ready():
    checks = {"azure_credential": False, "agent_ready": agent_id is not None}

    if AZURE_PROJECTS_AVAILABLE and DefaultAzureCredential:
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            checks["azure_credential"] = token is not None
        except Exception:
            checks["azure_credential"] = False
    else:
        checks["azure_credential"] = None  # Not configured

    all_ready = checks.get("azure_credential") is not False and checks["agent_ready"]
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)