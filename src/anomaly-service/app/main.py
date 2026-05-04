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
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    EventHubConsumerClient = None

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
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

init_telemetry()

app = FastAPI(title="Anomaly Detection Agent", version="1.0.0")
FastAPIInstrumentor.instrument_app(app)

# ML Model
model = IsolationForest(contamination=0.1, random_state=42)
transaction_history = []


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


def detect_anomaly(transaction: dict) -> AnomalyResult:
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
            
            return AnomalyResult(
                transactionId=transaction.get("transactionId", ""),
                isAnomalous=is_anomalous or len(reasons) > 0,
                confidenceScore=min(confidence, 1.0),
                reason="; ".join(reasons) if reasons else None
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
        
        result = detect_anomaly(transaction)
        
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
    """Initialize event processor"""
    eventhub_conn = os.getenv("EVENTHUB_CONNECTION_STRING")
    eventhub_name = os.getenv("EVENTHUB_NAME", "banking-events")
    
    if eventhub_conn and AZURE_AVAILABLE:
        client = EventHubConsumerClient.from_connection_string(
            conn_str=eventhub_conn,
            consumer_group="$Default",
            eventhub_name=eventhub_name
        )
        
        # Start receiving messages
        asyncio.create_task(client.receive(
            on_event=process_events,
            max_wait_time=5
        ))
        logger.info("Anomaly detection agent started")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/detect", response_model=AnomalyResult)
async def detect(request: TransactionEvent):
    """Detect anomaly in a single transaction"""
    return detect_anomaly(request.model_dump())


if __name__ == "__main__":
    import asyncio
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)