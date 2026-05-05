"""
Anomaly Detection Agent for suspicious transaction detection
"""
import asyncio
import json
import logging
import os
from typing import Optional

import numpy as np

try:
    from azure.eventhub import EventHubConsumerClient
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.identity import DefaultAzureCredential
    from opentelemetry.instrumentation.azure import AzureInstrumentor
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    EventHubConsumerClient = None
    ChatCompletionsClient = None
    DefaultAzureCredential = None
    AzureInstrumentor = None

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel
from sklearn.ensemble import IsolationForest

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
            resource=Resource.create({"service.name": "anomaly-service"})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        # Instrument Azure SDK for tracing OpenAI calls
        if AzureInstrumentor:
            AzureInstrumentor().instrument()

init_telemetry()

app = FastAPI(title="Anomaly Detection Agent", version="1.0.0")
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

# ML Model
model = IsolationForest(contamination=0.1, random_state=42)
transaction_history = []

# AI Client for explanations
ai_client = None


def init_ai_client():
    """Initialize Azure OpenAI client for anomaly explanations using RBAC"""
    global ai_client
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if endpoint and ChatCompletionsClient and DefaultAzureCredential:
        ai_client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential()
        )


async def explain_anomaly(transaction: dict, ml_reason: str) -> str:
    """Generate human-readable explanation for anomaly using GPT"""
    if not ai_client:
        return ml_reason
    
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("openai.generate-explanation") as span:
        span.set_attribute("openai.model", os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4"))
        span.set_attribute("openai.max_tokens", 150)
        span.set_attribute("openai.temperature", 0.3)
        span.set_attribute("transaction.amount", transaction.get('amount', 0))
        span.set_attribute("transaction.type", transaction.get('type', 'Unknown'))
        span.set_attribute("transaction.description", transaction.get('description', 'N/A')[:100])
        
        try:
            prompt = f"""
You are a financial security expert. Explain why this transaction might be suspicious:

Transaction Details:
- Amount: ${transaction.get('amount', 0):,.2f}
- Type: {transaction.get('type', 'Unknown')}
- Description: {transaction.get('description', 'N/A')}
- Category: {transaction.get('category', 'N/A')}

ML Detection Reason: {ml_reason}

Provide a clear, concise explanation suitable for a bank customer alert (2-3 sentences max).
"""
            response = ai_client.complete(
                messages=[UserMessage(content=prompt)],
                model=os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4"),
                temperature=0.3,
                max_tokens=150
            )
            span.set_attribute("openai.response_length", len(response.choices[0].message.content))
            return response.choices[0].message.content.strip()
        except Exception as e:
            span.record_exception(e)
            logger.error(f"Error generating AI explanation: {e}")
            return ml_reason


class TransactionEvent(BaseModel):
    id: str
    transactionId: str
    accountId: str
    amount: float
    type: str
    description: str
    category: str


class AnomalyResult(BaseModel):
    transactionId: str
    isAnomalous: bool
    confidenceScore: float
    reason: Optional[str] = None
    aiExplanation: Optional[str] = None


def extract_features(transaction: dict) -> np.ndarray:
    """Extract ML features from transaction"""
    amount = transaction.get("amount", 0)
    trans_type = transaction.get("type", "")
    
    # Simple feature engineering
    features = [
        amount,
        len(trans_type),
        1 if trans_type == "Transfer" else 0,
        amount / 1000 if amount > 0 else 0,  # normalized amount
    ]
    return np.array(features).reshape(1, -1)


async def detect_anomaly(transaction: dict) -> AnomalyResult:
    """Detect if a transaction is anomalous"""
    global model, transaction_history
    
    try:
        features = extract_features(transaction)
        
        # If we have enough history, use the model
        if len(transaction_history) > 10:
            prediction = model.predict(features)[0]
            score = model.decision_function(features)[0]
            
            is_anomalous = prediction == -1
            confidence = abs(score)
            
            # Additional heuristic checks
            reasons = []
            if transaction.get("amount", 0) > 10000:
                reasons.append("High value transaction")
            if transaction.get("type") == "Transfer" and transaction.get("amount", 0) > 5000:
                reasons.append("Large transfer")
            
            ml_reason = "; ".join(reasons) if reasons else None
            
            # Get AI explanation for anomalies
            ai_explanation = None
            if is_anomalous or len(reasons) > 0:
                ai_explanation = await explain_anomaly(transaction, ml_reason or "Unusual transaction pattern")
            
            return AnomalyResult(
                transactionId=transaction.get("transactionId", ""),
                isAnomalous=is_anomalous or len(reasons) > 0,
                confidenceScore=min(confidence, 1.0),
                reason=ml_reason,
                aiExplanation=ai_explanation
            )
        
        return AnomalyResult(
            transactionId=transaction.get("transactionId", ""),
            isAnomalous=False,
            confidenceScore=0.0,
            reason="Insufficient training data"
        )
    
    except Exception as e:
        logger.error(f"Error detecting anomaly: {e}")
        return AnomalyResult(
            transactionId=transaction.get("transactionId", ""),
            isAnomalous=False,
            confidenceScore=0.0,
            reason=f"Error: {str(e)}"
        )


async def process_events(partition_context, event):
    """Process incoming events from Event Hub"""
    try:
        event_data = event.body_as_str()
        transaction = json.loads(event_data)
        
        logger.info(f"Processing transaction: {transaction.get('transactionId')}")
        
        result = await detect_anomaly(transaction)
        
        if result.isAnomalous:
            logger.warning(f"Anomaly detected: {result.transactionId}")
            # In production, publish to alert topic or notification service
        
        # Update model with new transaction
        global transaction_history
        transaction_history.append(extract_features(transaction).flatten())
        
        # Retrain model periodically
        if len(transaction_history) >= 20:
            X = np.array(transaction_history[-100:])  # Use last 100 transactions
            model.fit(X)
        
        await partition_context.update_checkpoint(event)
    
    except Exception as e:
        logger.error(f"Error processing event: {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize event processor and AI client with validation"""
    init_ai_client()
    
    # Validate Entra ID token acquisition for Azure OpenAI (Foundry)
    if DefaultAzureCredential and os.getenv("AZURE_OPENAI_ENDPOINT"):
        logger.info("=" * 50)
        logger.info("Validating Azure OpenAI (Foundry) connectivity...")
        try:
            credential = DefaultAzureCredential()
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Azure OpenAI token acquired (expires {token.expires_on})")
            
            # Test AI connectivity with a simple ping
            if ai_client:
                try:
                    test_response = ai_client.complete(
                        messages=[UserMessage(content="Ping")],
                        model=os.getenv("AZURE_OPENAI_MODEL", "gpt-5.4"),
                        max_tokens=5
                    )
                    logger.info(f"✅ Azure OpenAI connectivity verified - Response received")
                except Exception as ping_ex:
                    logger.warning(f"⚠️ OpenAI ping failed: {ping_ex}")
        except Exception as ex:
            logger.error(f"❌ Azure OpenAI token acquisition FAILED: {ex}")
            logger.error("Ensure AZURE_OPENAI_ENDPOINT is set and Managed Identity/Service Principal has Cognitive Services OpenAI User role")
    
    # Validate EventHub connectivity
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
            
            # Start receiving messages
            asyncio.create_task(client.receive(
                on_event=process_events,
                max_wait_time=5
            ))
            logger.info("Anomaly detection agent started")
        except Exception as eh_ex:
            logger.error(f"❌ EventHub connection FAILED: {eh_ex}")
            logger.error("Ensure EVENTHUB_CONNECTION_STRING is set and Managed Identity has Azure Event Hubs Data Receiver role")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/detect", response_model=AnomalyResult)
async def detect(request: TransactionEvent):
    """Detect anomaly in a single transaction"""
    return await detect_anomaly(request.model_dump())


if __name__ == "__main__":
    import asyncio
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)