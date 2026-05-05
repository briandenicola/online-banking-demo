"""
AI-powered financial advice chatbot service
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.identity import DefaultAzureCredential
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    ChatCompletionsClient = None
    SystemMessage = None
    UserMessage = None
    DefaultAzureCredential = None

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
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
            resource=Resource.create({"service.name": "chatbot-service"})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

init_telemetry()

app = FastAPI(title="Chatbot Service", version="1.0.0")

# Initialize instrumentation
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

# Azure OpenAI client
ai_client = None
http_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ai_client, http_client
    http_client = httpx.AsyncClient()
    
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if endpoint and AZURE_AVAILABLE and DefaultAzureCredential:
        ai_client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential()
        )
        
        # Validate Entra ID token acquisition
        logger.info("Validating Entra ID token acquisition...")
        try:
            credential = DefaultAzureCredential()
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Entra ID token acquired successfully (expires {token.expires_on})")
        except Exception as ex:
            logger.error(f"❌ Entra ID token acquisition FAILED: {ex}")
    
    yield
    
    await http_client.aclose()


app.router.lifespan = lifespan


class ChatRequest(BaseModel):
    message: str
    user_id: str
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    response: str
    suggestions: list[str] = []


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Get financial advice from the AI chatbot
    """
    if not ai_client:
        raise HTTPException(status_code=500, detail="AI service not configured")
    
    # Enrich context with user data if available
    context_messages = []
    
    if request.context:
        context_messages.append(SystemMessage(
            content=f"You are a helpful financial advisor. "
                    f"Current user context: {request.context}. "
                    f"Provide concise, actionable financial advice. "
                    f"Never provide specific investment recommendations."
        ))
    else:
        context_messages.append(SystemMessage(
            content="You are a helpful financial advisor. "
                    "Provide concise, actionable financial advice. "
                    "Never provide specific investment recommendations."
        ))
    
    context_messages.append(UserMessage(content=request.message))
    
    try:
        response = ai_client.complete(
            messages=context_messages,
            model=os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4"),
            temperature=0.7,
            max_tokens=500
        )
        
        answer = response.choices[0].message.content
        
        # Generate suggestions based on the response
        suggestions = [
            "How can I save more each month?",
            "What's my spending pattern?",
            "Should I consider a budget?",
        ]
        
        return ChatResponse(response=answer, suggestions=suggestions)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)