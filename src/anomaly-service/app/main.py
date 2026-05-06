"""
Anomaly Detection Agent for suspicious transaction detection
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import redis.asyncio as redis

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.identity import DefaultAzureCredential
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    ChatCompletionsClient = None
    DefaultAzureCredential = None

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

# Constants
STREAM_NAME = "banking-events"
CONSUMER_GROUP = "anomaly-consumer-group"
CONSUMER_NAME = "anomaly-1"

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

init_telemetry()

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
    
    features = [
        amount,
        len(trans_type),
        1 if trans_type == "Transfer" else 0,
        amount / 1000 if amount > 0 else 0,
    ]
    return np.array(features).reshape(1, -1)


async def detect_anomaly(transaction: dict) -> AnomalyResult:
    """Detect if a transaction is anomalous"""
    global model, transaction_history
    
    try:
        features = extract_features(transaction)
        
        if len(transaction_history) > 10:
            prediction = model.predict(features)[0]
            score = model.decision_function(features)[0]
            
            is_anomalous = prediction == -1
            confidence = abs(score)
            
            reasons = []
            if transaction.get("amount", 0) > 10000:
                reasons.append("High value transaction")
            if transaction.get("type") == "Transfer" and transaction.get("amount", 0) > 5000:
                reasons.append("Large transfer")
            
            ml_reason = "; ".join(reasons) if reasons else None
            
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


async def consume_redis_stream(redis_client: redis.Redis):
    """Consume events from Redis Streams using consumer groups"""
    # Create consumer group if it doesn't exist
    try:
        await redis_client.xgroup_create(
            STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True
        )
        logger.info(f"Created consumer group '{CONSUMER_GROUP}' on stream '{STREAM_NAME}'")
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group '{CONSUMER_GROUP}' already exists")
        else:
            raise

    logger.info(f"Starting Redis Stream consumer: {CONSUMER_NAME}")
    backoff = 1

    while True:
        try:
            messages = await redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=10,
                block=5000,
            )

            if not messages:
                backoff = 1
                continue

            backoff = 1

            for stream_name, stream_messages in messages:
                for message_id, fields in stream_messages:
                    try:
                        payload_raw = fields.get("payload") or fields.get(b"payload")
                        if payload_raw:
                            if isinstance(payload_raw, bytes):
                                payload_raw = payload_raw.decode("utf-8")
                            event_data = json.loads(payload_raw)

                            event_type = event_data.get("eventType", "")
                            data = event_data.get("data", {})

                            logger.info(f"Processing event: {event_type}")

                            # Run anomaly detection on the event data
                            result = await detect_anomaly(data)

                            if result.isAnomalous:
                                logger.warning(
                                    f"Anomaly detected in {event_type}: {result.reason}"
                                )

                            # Update ML model training data
                            transaction_history.append(extract_features(data).flatten())
                            if len(transaction_history) >= 20:
                                X = np.array(transaction_history[-100:])
                                model.fit(X)

                        # Acknowledge the message
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)

                    except Exception as e:
                        logger.error(f"Error processing message {message_id}: {e}")
                        # Still ack to avoid infinite reprocessing of bad messages
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)

        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}. Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except Exception as e:
            logger.error(f"Unexpected error in consumer loop: {e}. Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start Redis consumer on startup"""
    init_ai_client()

    redis_url = os.getenv("REDIS__CONNECTIONSTRING", "redis:6379")
    if not redis_url.startswith("redis://"):
        redis_url = f"redis://{redis_url}"

    redis_client = redis.from_url(redis_url, decode_responses=True)

    # Verify Redis connectivity
    try:
        await redis_client.ping()
        logger.info("✅ Redis connectivity verified")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")

    # Start the consumer as a background task
    consumer_task = asyncio.create_task(consume_redis_stream(redis_client))
    logger.info("Anomaly detection agent started — consuming from Redis Stream")

    yield

    # Shutdown
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()


app = FastAPI(title="Anomaly Detection Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/detect", response_model=AnomalyResult)
async def detect(request: TransactionEvent):
    """Detect anomaly in a single transaction"""
    return await detect_anomaly(request.model_dump())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)