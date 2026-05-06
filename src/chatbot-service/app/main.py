"""
AI-powered financial advice chatbot service using Azure AI Foundry Agents
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx

try:
    from azure.ai.agents import AgentsClient
    from azure.ai.agents.models import FunctionTool, ToolSet, FunctionDefinition
    from azure.identity import DefaultAzureCredential
    from opentelemetry.instrumentation.azure import AzureInstrumentor
    AZURE_AGENTS_AVAILABLE = True
except ImportError:
    AZURE_AGENTS_AVAILABLE = False
    AgentsClient = None
    FunctionTool = None
    ToolSet = None
    FunctionDefinition = None
    DefaultAzureCredential = None
    AzureInstrumentor = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, Field

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
            resource=Resource.create({"service.name": "chatbot-service"})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        if AzureInstrumentor:
            AzureInstrumentor().instrument()

init_telemetry()

# Azure AI Agents client and agent
agents_client = None
agent_id = None
user_threads = {}  # In-memory thread storage per user


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
    global agents_client, agent_id
    
    # Support both AZURE_AI_AGENTS_ENDPOINT and AZURE_OPENAI_ENDPOINT for flexibility
    endpoint = os.getenv("AZURE_AI_AGENTS_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
    if endpoint and AZURE_AGENTS_AVAILABLE and DefaultAzureCredential:
        # Initialize Agents client
        agents_client = AgentsClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential()
        )
        
        logger.info("=" * 50)
        logger.info("Validating Azure AI Foundry connectivity...")
        
        # Validate Entra ID token acquisition for Azure AI Agents
        try:
            credential = DefaultAzureCredential()
            token = await credential.get_token("https://ai.azure.com/.default")
            logger.info(f"✅ Azure AI Foundry token acquired (expires {token.expires_on})")
        except Exception as ex:
            logger.error(f"❌ Azure AI Foundry token acquisition FAILED: {ex}")
            logger.error("Ensure AZURE_AI_AGENTS_ENDPOINT is set and Managed Identity/Service Principal has Azure AI Account role")
            raise
        
        # Test connectivity with a simple ping
        try:
            test_run = agents_client.create_agent(
                model=os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4"),
                name="connectivity-test-agent",
                instructions="Test agent"
            )
            agents_client.delete_agent(test_run.id)
            logger.info("✅ Azure AI Foundry connectivity verified - Agent creation/deletion works")
        except Exception as ping_ex:
            logger.warning(f"⚠️ Azure AI Foundry ping test failed: {ping_ex}")
        
        # Create agent with tools for financial advisor
        agent = agents_client.create_agent(
            model=os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4"),
            name="financial-advisor-agent",
            instructions="""You are a helpful financial advisor agent. 
            Provide concise, actionable financial advice. 
            Never provide specific investment recommendations.
            Use the available tools to get budget insights, spending patterns, and analyze transactions.
            Always cite data from tools when providing advice.""",
            toolset=ToolSet(
                FunctionTool(get_budget_insights),
                FunctionTool(get_spending_pattern),
                FunctionTool(analyze_transaction)
            )
        )
        agent_id = agent.id
        logger.info(f"✅ Created Azure AI Agent: {agent_id}")
    
    yield
    
    if agent_id and agents_client:
        try:
            agents_client.delete_agent(agent_id)
            logger.info(f"Cleaned up agent {agent_id}")
        except Exception as e:
            logger.warning(f"Error cleaning up agent: {e}")


app = FastAPI(title="Chatbot Service", version="1.0.0", lifespan=lifespan)

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
    """
    Get financial advice from the AI agent
    """
    if not agents_client or not agent_id:
        raise HTTPException(
            status_code=503, 
            detail="Azure AI Foundry not configured. Set AZURE_AI_AGENTS_ENDPOINT environment variable."
        )
    
    tracer = trace.get_tracer(__name__)
    
    try:
        with tracer.start_as_current_span("ai-agent.chat") as span:
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("user.id", request.user_id)
            span.set_attribute("user.message", request.message[:100])
            
            # Get or create thread for user
            thread_id = user_threads.get(request.user_id)
            if not thread_id:
                thread = agents_client.create_thread()
                thread_id = thread.id
                user_threads[request.user_id] = thread_id
                logger.info(f"Created new thread {thread_id} for user {request.user_id}")
            
            # Add user message to thread
            user_message = f"Context: {request.context}\n\nQuestion: {request.message}"
            agents_client.create_message(
                thread_id=thread_id,
                role="user",
                content=user_message
            )
            
            # Run agent on thread
            run = agents_client.create_run(
                thread_id=thread_id,
                agent_id=agent_id
            )
            
            span.set_attribute("run.id", run.id)
            
            # Wait for run completion with async sleep to avoid blocking event loop
            while run.status in ["queued", "in_progress", "requires_action"]:
                await asyncio.sleep(0.5)
                run = agents_client.get_run(thread_id, run.id)
            
            span.set_attribute("run.status", run.status)
            
            if run.status == "failed":
                raise HTTPException(status_code=500, detail=f"Agent run failed: {run.last_error}")
            
            # Get messages from thread
            messages = agents_client.list_messages(thread_id=thread_id)
            answer = ""
            for msg in messages.data:
                if msg.role == "assistant":
                    answer = msg.content[0].text.value if msg.content else ""
                    break
            
            span.set_attribute("response.length", len(answer))
            
            if not answer:
                answer = "I couldn't generate a response at this time."
        
        suggestions = [
            "How can I save more each month?",
            "What's my spending pattern?",
            "Should I consider a budget?",
        ]
        
        return ChatResponse(response=answer, suggestions=suggestions)
    
    except Exception as e:
        logger.error(f"Error in agent chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/new", response_model=ChatResponse)
async def chat_new_session(request: ChatRequest):
    """
    Start a new chat session (clears conversation history)
    """
    user_threads.pop(request.user_id, None)
    return await chat(request)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "agent_id": agent_id,
        "agents_available": AZURE_AGENTS_AVAILABLE
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)