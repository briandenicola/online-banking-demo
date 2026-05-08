"""
AI-powered Anomaly Detection Service using Azure AI Foundry.

Uses agent-framework-foundry for risk scoring:
- FoundryChatClient for Azure AI Foundry model access
- Extensible analyzer framework for pluggable risk assessment strategies
- Redis Streams for event consumption, Redis for scored transaction storage

Architecture:
- Analyzers: Pluggable risk assessment engines (Foundry AI, future: evals, red-team)
- Categorizers: Pluggable transaction categorization (Foundry AI, user-defined hints)
- Pipeline: Event → Analyze → Score → Categorize → Store → Flag (if high-risk)
- Storage: Redis sorted sets for scored/flagged transactions
"""
import asyncio
import abc
import base64
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis
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

from fastapi import FastAPI, HTTPException, Query, Request
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
logger = structlog.get_logger("anomaly-service")

# Constants
STREAM_NAME = "banking-events"
CONSUMER_GROUP = "anomaly-consumer-group"
CONSUMER_NAME = "anomaly-1"
FLAGGED_TRANSACTIONS_KEY = "flagged-transactions"
FLAGGED_TRANSACTION_PREFIX = "flagged-tx:"
SCORED_TRANSACTIONS_KEY = "scored-transactions"
SCORED_TRANSACTION_PREFIX = "scored-tx:"
SCORED_TX_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
FLAGGING_THRESHOLD = 0.7

# Module-level state
_redis_client: Optional[redis.Redis] = None
_analyzer_pipeline: Optional["AnalyzerPipeline"] = None
_ai_calls_today: int = 0
_ai_calls_date: str = ""


# Initialize telemetry
def init_telemetry():
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider = TracerProvider(
            resource=Resource.create({"service.name": "anomaly-service"})
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


# ============================================================
# Models
# ============================================================

class RiskAssessment(BaseModel):
    """Result of analyzing a single transaction for risk."""
    riskScore: float = Field(ge=0.0, le=1.0, description="Risk score 0.0 (safe) to 1.0 (critical)")
    explanation: str = Field(description="Human-readable explanation of the risk assessment")
    flags: list[str] = Field(default_factory=list, description="Risk flag categories detected")


class CategoryResult(BaseModel):
    """Result of AI-powered transaction categorization."""
    category: str = Field(description="Assigned category (e.g., Groceries, Entertainment)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the categorization")
    reasoning: str = Field(default="", description="Brief explanation of why this category was chosen")


class ScoredTransaction(BaseModel):
    """A transaction with its AI risk assessment and categorization."""
    id: str
    transactionId: str
    accountId: str
    amount: float
    type: str
    description: str
    category: str = ""
    categoryConfidence: float = 0.0
    categoryReasoning: str = ""
    riskScore: float
    explanation: str
    flags: list[str] = []
    scoredAt: str
    status: str = "scored"
    notes: Optional[str] = None


class FlaggedTransaction(BaseModel):
    """A high-risk transaction requiring admin review."""
    id: str
    transactionId: str
    accountId: str
    amount: float
    type: str
    riskScore: float
    reason: str
    flags: list[str] = []
    flaggedAt: str
    status: str = "pending"
    notes: Optional[str] = None


class AdminStats(BaseModel):
    totalFlagged: int
    pendingReview: int
    reviewed: int
    cleared: int
    avgRiskScore: float
    totalScored: int
    highRiskCount: int
    aiCallsToday: int


class ReviewRequest(BaseModel):
    status: str = Field(..., pattern=r"^(reviewed|cleared)$")
    notes: str


# ============================================================
# Extensible Analyzer Framework
# ============================================================

class BaseAnalyzer(abc.ABC):
    """Base class for transaction risk analyzers.

    Extend this to add new analysis capabilities:
    - EvalAnalyzer: Run Azure AI Evaluation SDK checks
    - RedTeamAnalyzer: Adversarial pattern detection
    - RuleBasedAnalyzer: Deterministic business rules
    - VelocityAnalyzer: Transaction frequency analysis

    Each analyzer returns a RiskAssessment. The pipeline aggregates results.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for this analyzer."""
        ...

    @abc.abstractmethod
    async def analyze(self, transaction: dict) -> RiskAssessment:
        """Analyze a transaction and return a risk assessment."""
        ...

    @property
    def enabled(self) -> bool:
        """Override to conditionally disable an analyzer."""
        return True


class FoundryRiskAnalyzer(BaseAnalyzer):
    """Primary risk analyzer using Azure AI Foundry (GPT-5.4-mini).

    Sends transaction context to the model with a financial security expert prompt.
    Returns structured JSON with risk score, explanation, and flags.
    """

    SYSTEM_PROMPT = """You are a financial security expert at a major bank. Your job is to assess transaction risk.

Analyze each transaction and provide a risk assessment. Consider:
- Transaction amount relative to typical banking activity
- Transaction type and whether it matches expected patterns
- Description for suspicious keywords or patterns
- Category context

Risk scoring guidelines:
- 0.0-0.3: Normal, low-risk transaction (routine purchases, small transfers)
- 0.3-0.5: Slightly elevated risk (larger than typical, unusual category)
- 0.5-0.7: Moderate risk (significantly unusual amount or pattern)
- 0.7-0.9: High risk (suspicious pattern, very large amount, unusual destination)
- 0.9-1.0: Critical risk (clear fraud indicators, impossible patterns)

Examples:
- $25 grocery purchase → {"riskScore": 0.05, "explanation": "Routine small purchase", "flags": []}
- $500 transfer to known account → {"riskScore": 0.15, "explanation": "Normal transfer amount", "flags": []}
- $5,000 transfer to new account → {"riskScore": 0.55, "explanation": "Large transfer — elevated due to amount", "flags": ["large_transfer"]}
- $15,000 wire at unusual hours → {"riskScore": 0.85, "explanation": "Very large amount with unusual timing", "flags": ["large_amount", "unusual_time"]}

Respond with ONLY a JSON object (no markdown, no text outside JSON):
{"riskScore": <float 0.0-1.0>, "explanation": "<1-2 sentence explanation>", "flags": ["<flag1>", ...]}"""

    def __init__(self):
        self._client: Optional[FoundryChatClient] = None
        self._model: str = ""
        self._ready = False

    @property
    def name(self) -> str:
        return "foundry-risk"

    @property
    def enabled(self) -> bool:
        return self._ready

    def initialize(self, client: FoundryChatClient, model: str):
        """Initialize with a FoundryChatClient instance."""
        self._client = client
        self._model = model
        self._ready = True

    async def analyze(self, transaction: dict) -> RiskAssessment:
        global _ai_calls_today, _ai_calls_date

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if _ai_calls_date != today:
            _ai_calls_today = 0
            _ai_calls_date = today

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("foundry.risk-assessment") as span:
            span.set_attribute("analyzer.name", self.name)
            span.set_attribute("transaction.amount", transaction.get("amount", 0))
            span.set_attribute("transaction.type", transaction.get("type", ""))

            try:
                user_message = (
                    f"Assess this transaction:\n"
                    f"- Amount: ${transaction.get('amount', 0):,.2f}\n"
                    f"- Type: {transaction.get('type', 'Unknown')}\n"
                    f"- Description: {transaction.get('description', 'N/A')}\n"
                    f"- Category: {transaction.get('category', 'N/A')}\n"
                    f"- Account: {transaction.get('accountId', 'N/A')}"
                )

                risk_agent = Agent(
                    client=self._client,
                    name="RiskAssessor",
                    instructions=self.SYSTEM_PROMPT,
                    tools=[],
                )
                session = risk_agent.create_session()
                response = await risk_agent.run(user_message, session=session)

                _ai_calls_today += 1
                span.set_attribute("ai.calls_today", _ai_calls_today)

                result = self._parse_response(str(response))
                span.set_attribute("risk.score", result.riskScore)
                return result

            except Exception as e:
                logger.error(f"Foundry risk assessment failed: {e}")
                span.record_exception(e)
                return RiskAssessment(
                    riskScore=0.5,
                    explanation="AI scoring unavailable — assigned default moderate risk",
                    flags=["ai_unavailable"]
                )

    def _parse_response(self, response: str) -> RiskAssessment:
        """Parse the AI response into a RiskAssessment."""
        try:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)
            return RiskAssessment(
                riskScore=max(0.0, min(1.0, float(data.get("riskScore", 0.5)))),
                explanation=data.get("explanation", "No explanation provided"),
                flags=data.get("flags", [])
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse AI response: {e}, raw: {response[:200]}")
            return RiskAssessment(
                riskScore=0.5,
                explanation="Failed to parse AI risk assessment",
                flags=["parse_error"]
            )


# ============================================================
# Extensible Categorizer Framework
# ============================================================

class BaseCategorizer(abc.ABC):
    """Base class for transaction categorizers.

    Separate from risk analyzers — categorization is about labeling
    transactions (Groceries, Entertainment, etc.), not assessing risk.

    User-defined category hints can be passed to influence categorization.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique identifier for this categorizer."""
        ...

    @abc.abstractmethod
    async def categorize(self, transaction: dict, hints: list[str] | None = None) -> CategoryResult:
        """Categorize a transaction, optionally using user-defined category hints."""
        ...

    @property
    def enabled(self) -> bool:
        """Override to conditionally disable a categorizer."""
        return True


class FoundryCategorizer(BaseCategorizer):
    """AI-powered transaction categorizer using Azure AI Foundry.

    Uses a dedicated prompt focused solely on categorization.
    Accepts optional user-defined category hints to personalize results.
    """

    SYSTEM_PROMPT = """You are a financial transaction categorizer. Your ONLY job is to assign a category to a transaction.

Choose the single best category from common banking categories:
- Groceries
- Dining & Restaurants
- Entertainment
- Transportation
- Utilities
- Healthcare
- Shopping
- Travel
- Income
- Transfer
- Subscription
- Education
- Housing
- Insurance
- Savings
- Cash Withdrawal
- Fees & Charges
- Other

If the user has provided custom categories, prefer those when they are a good fit.

Respond with ONLY a JSON object (no markdown, no text outside JSON):
{"category": "<category name>", "confidence": <float 0.0-1.0>, "reasoning": "<brief reason>"}"""

    def __init__(self):
        self._client: Optional[FoundryChatClient] = None
        self._model: str = ""
        self._ready = False

    @property
    def name(self) -> str:
        return "foundry-categorizer"

    @property
    def enabled(self) -> bool:
        return self._ready

    def initialize(self, client: FoundryChatClient, model: str):
        """Initialize with a FoundryChatClient instance."""
        self._client = client
        self._model = model
        self._ready = True

    async def categorize(self, transaction: dict, hints: list[str] | None = None) -> CategoryResult:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("foundry.categorization") as span:
            span.set_attribute("categorizer.name", self.name)

            try:
                user_message = (
                    f"Categorize this transaction:\n"
                    f"- Description: {transaction.get('description', 'N/A')}\n"
                    f"- Amount: ${transaction.get('amount', 0):,.2f}\n"
                    f"- Type: {transaction.get('type', 'Unknown')}"
                )

                if hints:
                    user_message += f"\n\nUser-defined categories (prefer these when applicable): {', '.join(hints)}"

                cat_agent = Agent(
                    client=self._client,
                    name="TransactionCategorizer",
                    instructions=self.SYSTEM_PROMPT,
                    tools=[],
                )
                session = cat_agent.create_session()
                response = await cat_agent.run(user_message, session=session)

                result = self._parse_response(str(response))
                span.set_attribute("category.result", result.category)
                span.set_attribute("category.confidence", result.confidence)
                return result

            except Exception as e:
                logger.error(f"Foundry categorization failed: {e}")
                span.record_exception(e)
                return CategoryResult(
                    category="Uncategorized",
                    confidence=0.0,
                    reasoning=f"AI categorization failed: {str(e)[:100]}"
                )

    @staticmethod
    def _parse_response(response: str) -> CategoryResult:
        try:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)
            return CategoryResult(
                category=data.get("category", "Uncategorized"),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                reasoning=data.get("reasoning", "")
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse categorization response: {e}, raw: {response[:200]}")
            return CategoryResult(
                category="Uncategorized",
                confidence=0.0,
                reasoning="Failed to parse AI categorization"
            )


class AnalyzerPipeline:
    """Orchestrates multiple analyzers and aggregates results.

    Future analyzers (evals, red-team, rule-based) can be registered here.
    The pipeline runs enabled analyzers and returns the highest-risk result.
    Categorizers run separately from risk analyzers (separation of concerns).
    """

    def __init__(self):
        self._analyzers: list[BaseAnalyzer] = []
        self._categorizers: list[BaseCategorizer] = []

    def register(self, analyzer: BaseAnalyzer):
        """Register an analyzer in the pipeline."""
        self._analyzers.append(analyzer)
        logger.info(f"Registered analyzer: {analyzer.name} (enabled={analyzer.enabled})")

    def register_categorizer(self, categorizer: BaseCategorizer):
        """Register a categorizer in the pipeline."""
        self._categorizers.append(categorizer)
        logger.info(f"Registered categorizer: {categorizer.name} (enabled={categorizer.enabled})")

    @property
    def analyzers(self) -> list[BaseAnalyzer]:
        return self._analyzers

    @property
    def categorizers(self) -> list[BaseCategorizer]:
        return self._categorizers

    async def assess(self, transaction: dict) -> RiskAssessment:
        """Run all enabled analyzers and return the highest-risk assessment."""
        results: list[RiskAssessment] = []

        for analyzer in self._analyzers:
            if not analyzer.enabled:
                continue
            try:
                result = await analyzer.analyze(transaction)
                results.append(result)
            except Exception as e:
                logger.error(f"Analyzer {analyzer.name} failed: {e}")

        if not results:
            return RiskAssessment(
                riskScore=0.0,
                explanation="No analyzers available",
                flags=["no_analyzers"]
            )

        # Return highest risk score (conservative approach)
        return max(results, key=lambda r: r.riskScore)

    async def categorize(self, transaction: dict, hints: list[str] | None = None) -> CategoryResult:
        """Run the first enabled categorizer to assign a category."""
        for categorizer in self._categorizers:
            if not categorizer.enabled:
                continue
            try:
                return await categorizer.categorize(transaction, hints=hints)
            except Exception as e:
                logger.error(f"Categorizer {categorizer.name} failed: {e}")

        return CategoryResult(
            category=transaction.get("category", "Uncategorized"),
            confidence=0.0,
            reasoning="No categorizers available"
        )


# ============================================================
# Redis Helpers
# ============================================================

REDIS_SCOPE = "acca5fbb-b7e4-4009-81f1-37e38fd66d78/.default"
_token_refresh_task: Optional[asyncio.Task] = None


def _parse_redis_connection_string(conn_str: str) -> dict:
    """Parse a .NET-style Redis connection string into components."""
    result = {"host": "redis", "port": 6379, "ssl": False, "password": None}
    parts = [p.strip() for p in conn_str.split(",")]
    for i, part in enumerate(parts):
        if i == 0:
            if ":" in part and "=" not in part:
                host, port_str = part.rsplit(":", 1)
                result["host"] = host
                try:
                    result["port"] = int(port_str)
                except ValueError:
                    result["host"] = part
            else:
                result["host"] = part
            continue
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "ssl" and value.lower() == "true":
            result["ssl"] = True
        elif key == "password":
            result["password"] = value
    return result


def _extract_oid_from_token(token: str) -> str:
    """Extract the Object ID (oid claim) from a JWT access token."""
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    try:
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims.get("oid", "")
    except Exception as e:
        logger.error(f"Failed to decode token payload: {e}")
        return ""


async def _refresh_redis_token(client, credential):
    """Periodically refresh the Entra ID token on the Redis connection."""
    while True:
        await asyncio.sleep(45 * 60)
        try:
            token = credential.get_token(REDIS_SCOPE)
            oid = _extract_oid_from_token(token.token)
            await client.execute_command("AUTH", oid, token.token)
            logger.info("✅ Redis token refreshed")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"⚠️ Failed to refresh Redis token: {e}")


async def _create_redis_client():
    """Create a Redis client supporting both Azure Managed Redis (Entra ID)
    and local docker-compose connections."""
    conn_str = os.getenv("REDIS__CONNECTIONSTRING", "redis:6379")
    parsed = _parse_redis_connection_string(conn_str)

    kwargs = {
        "host": parsed["host"],
        "port": parsed["port"],
        "decode_responses": True,
    }

    if parsed["ssl"]:
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = None

    azure_client_id = os.getenv("AZURE_CLIENT_ID")
    if azure_client_id and AGENT_FRAMEWORK_AVAILABLE:
        credential = DefaultAzureCredential()
        token = credential.get_token(REDIS_SCOPE)
        oid = _extract_oid_from_token(token.token)
        kwargs["username"] = oid
        kwargs["password"] = token.token
        logger.info(f"Using Entra ID token for Redis authentication (OID: {oid})")

        client = redis.Redis(**kwargs)

        global _token_refresh_task
        _token_refresh_task = asyncio.create_task(_refresh_redis_token(client, credential))
        return client

    if parsed["password"]:
        kwargs["password"] = parsed["password"]

    logger.info("Using connection string for Redis authentication (local dev)")
    return redis.Redis(**kwargs)


# ============================================================
# Scoring & Storage
# ============================================================

async def score_and_store_transaction(transaction: dict) -> ScoredTransaction:
    """Categorize and score a transaction, then store results."""

    # Step 1: Categorize first (separate concern from risk)
    existing_category = transaction.get("category", "")
    if not existing_category or existing_category == "Uncategorized":
        cat_result = await _analyzer_pipeline.categorize(transaction)
        category = cat_result.category
        logger.info(
            f"🏷️ Categorized transaction: {category} "
            f"(confidence: {cat_result.confidence:.2f}, reason: {cat_result.reasoning})"
        )
    else:
        category = existing_category
        cat_result = CategoryResult(category=category, confidence=1.0, reasoning="User-provided category")
        logger.info(f"🏷️ Using user-provided category: {category}")

    # Inject category into transaction context for risk scoring
    transaction_with_category = {**transaction, "category": category}

    # Step 2: Score for risk (uses category context)
    assessment = await _analyzer_pipeline.assess(transaction_with_category)
    logger.info(
        f"📊 Scored transaction: risk={assessment.riskScore:.2f}, "
        f"flags={assessment.flags}, explanation={assessment.explanation[:80]}"
    )

    scored_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    scored_tx = ScoredTransaction(
        id=scored_id,
        transactionId=transaction.get("transactionId", transaction.get("id", "")),
        accountId=transaction.get("accountId", ""),
        amount=transaction.get("amount", 0),
        type=transaction.get("type", ""),
        description=transaction.get("description", ""),
        category=category,
        categoryConfidence=cat_result.confidence,
        categoryReasoning=cat_result.reasoning,
        riskScore=assessment.riskScore,
        explanation=assessment.explanation,
        flags=assessment.flags,
        scoredAt=now.isoformat(),
    )

    if _redis_client:
        try:
            # Store scored transaction with TTL
            await _redis_client.set(
                f"{SCORED_TRANSACTION_PREFIX}{scored_id}",
                scored_tx.model_dump_json(),
                ex=SCORED_TX_TTL_SECONDS,
            )
            await _redis_client.zadd(SCORED_TRANSACTIONS_KEY, {scored_id: now.timestamp()})

            # Flag if high-risk
            if assessment.riskScore >= FLAGGING_THRESHOLD:
                flagged_tx = FlaggedTransaction(
                    id=scored_id,
                    transactionId=scored_tx.transactionId,
                    accountId=scored_tx.accountId,
                    amount=scored_tx.amount,
                    type=scored_tx.type,
                    riskScore=assessment.riskScore,
                    reason=assessment.explanation,
                    flags=assessment.flags,
                    flaggedAt=now.isoformat(),
                )
                await _redis_client.set(
                    f"{FLAGGED_TRANSACTION_PREFIX}{scored_id}",
                    flagged_tx.model_dump_json(),
                )
                await _redis_client.zadd(FLAGGED_TRANSACTIONS_KEY, {scored_id: now.timestamp()})
                logger.warning(
                    f"🚨 High-risk transaction flagged: {scored_tx.transactionId} "
                    f"(score: {assessment.riskScore:.2f}, flags: {assessment.flags})"
                )

        except Exception as e:
            logger.error(f"Error storing scored transaction: {e}")

    return scored_tx


# ============================================================
# Redis Stream Consumer
# ============================================================

async def consume_redis_stream(redis_client: redis.Redis):
    """Consume events from Redis Streams and score each transaction."""
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

                            scored = await score_and_store_transaction(data)
                            logger.info(
                                f"Scored transaction {scored.transactionId}: "
                                f"risk={scored.riskScore:.2f}"
                            )

                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)

                    except Exception as e:
                        logger.error(f"Error processing message {message_id}: {e}")
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)

        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}. Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except Exception as e:
            logger.error(f"Unexpected error in consumer loop: {e}. Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ============================================================
# Application Lifespan
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize analyzer pipeline and start consumer."""
    global _redis_client, _analyzer_pipeline

    logger.info("=" * 60)
    logger.info("🔍 Anomaly Detection Service — Startup (v2.0 Foundry)")
    logger.info("=" * 60)

    # Initialize analyzer pipeline
    _analyzer_pipeline = AnalyzerPipeline()

    # Initialize Foundry analyzer
    endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    model_name = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini")

    logger.info(f"  Endpoint: {endpoint or '❌ NOT SET'}")
    logger.info(f"  Model: {model_name}")
    logger.info(f"  AGENT_FRAMEWORK_AVAILABLE: {AGENT_FRAMEWORK_AVAILABLE}")

    foundry_analyzer = FoundryRiskAnalyzer()
    foundry_categorizer = FoundryCategorizer()

    if endpoint and AGENT_FRAMEWORK_AVAILABLE:
        try:
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Azure credential acquired (expires: {token.expires_on})")

            client = FoundryChatClient(
                project_endpoint=endpoint,
                model=model_name,
                credential=credential,
            )
            foundry_analyzer.initialize(client, model_name)
            foundry_categorizer.initialize(client, model_name)
            logger.info("✅ Foundry risk analyzer initialized")
            logger.info("✅ Foundry categorizer initialized")
        except Exception as e:
            logger.error(f"❌ Foundry initialization failed: {e}")
    else:
        logger.warning("⚠️ Foundry not available — using fallback scoring")

    _analyzer_pipeline.register(foundry_analyzer)
    _analyzer_pipeline.register_categorizer(foundry_categorizer)

    # Future analyzers/categorizers can be registered here:
    # _analyzer_pipeline.register(EvalAnalyzer())
    # _analyzer_pipeline.register(VelocityAnalyzer())
    # _analyzer_pipeline.register_categorizer(UserHintCategorizer())

    # Initialize Redis
    redis_client = await _create_redis_client()
    _redis_client = redis_client

    try:
        await redis_client.ping()
        logger.info("✅ Redis connectivity verified")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")

    # Start the consumer as a background task
    consumer_task = asyncio.create_task(consume_redis_stream(redis_client))
    logger.info("🟢 Anomaly detection service ready — consuming from Redis Stream")
    logger.info("=" * 60)

    yield

    # Shutdown
    consumer_task.cancel()
    if _token_refresh_task:
        _token_refresh_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    _redis_client = None


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(title="Anomaly Detection Service", version="2.0.0", lifespan=lifespan)

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


# ============================================================
# Health Endpoints
# ============================================================

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/healthz")
async def healthz():
    return {
        "status": "healthy",
        "service": "anomaly-service",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/readyz")
async def ready():
    checks = {"redis": False, "analyzer_pipeline": False}

    if _redis_client:
        try:
            await _redis_client.ping()
            checks["redis"] = True
        except Exception:
            pass

    if _analyzer_pipeline and any(a.enabled for a in _analyzer_pipeline.analyzers):
        checks["analyzer_pipeline"] = True

    all_ready = all(checks.values())
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}


# ============================================================
# Detection Endpoint (synchronous scoring)
# ============================================================

@app.post("/detect", response_model=RiskAssessment)
async def detect(request: Request):
    """Score a single transaction synchronously (for on-demand assessment)."""
    body = await request.json()
    if not _analyzer_pipeline:
        raise HTTPException(status_code=503, detail="Analyzer pipeline not initialized")
    return await _analyzer_pipeline.assess(body)


# ============================================================
# Admin API Endpoints
# ============================================================

@app.get("/api/admin/stats", response_model=AdminStats)
async def get_admin_stats():
    """Return aggregated admin statistics."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    total_scored = await _redis_client.zcard(SCORED_TRANSACTIONS_KEY)
    total_flagged = await _redis_client.zcard(FLAGGED_TRANSACTIONS_KEY)

    pending = 0
    reviewed = 0
    cleared = 0
    risk_scores = []

    flagged_ids = await _redis_client.zrevrange(FLAGGED_TRANSACTIONS_KEY, 0, -1)
    for tx_id in flagged_ids:
        raw = await _redis_client.get(f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            tx = json.loads(raw)
            status = tx.get("status", "pending")
            if status == "pending":
                pending += 1
            elif status == "reviewed":
                reviewed += 1
            elif status == "cleared":
                cleared += 1
            risk_scores.append(tx.get("riskScore", 0))

    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0

    return AdminStats(
        totalFlagged=total_flagged,
        pendingReview=pending,
        reviewed=reviewed,
        cleared=cleared,
        avgRiskScore=avg_risk,
        totalScored=total_scored,
        highRiskCount=total_flagged,
        aiCallsToday=_ai_calls_today,
    )


@app.get("/api/admin/transactions", response_model=list[ScoredTransaction])
async def list_scored_transactions(
    limit: int = Query(default=100, ge=1, le=500),
    sort: str = Query(default="scoredAt", pattern=r"^(scoredAt|riskScore|amount)$"),
    order: str = Query(default="desc", pattern=r"^(asc|desc)$"),
):
    """Return all scored transactions with risk scores."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    # Get IDs from sorted set (most recent first)
    tx_ids = await _redis_client.zrevrange(SCORED_TRANSACTIONS_KEY, 0, limit * 2)

    results = []
    for tx_id in tx_ids:
        raw = await _redis_client.get(f"{SCORED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            results.append(ScoredTransaction(**json.loads(raw)))
        if len(results) >= limit:
            break

    # Sort by requested field
    reverse = order == "desc"
    if sort == "riskScore":
        results.sort(key=lambda t: t.riskScore, reverse=reverse)
    elif sort == "amount":
        results.sort(key=lambda t: abs(t.amount), reverse=reverse)
    else:
        results.sort(key=lambda t: t.scoredAt, reverse=reverse)

    return results


@app.get("/api/admin/flagged-transactions", response_model=list[FlaggedTransaction])
async def list_flagged_transactions():
    """Return all flagged (high-risk) transactions, ordered by most recent."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    tx_ids = await _redis_client.zrevrange(FLAGGED_TRANSACTIONS_KEY, 0, -1)
    results = []
    for tx_id in tx_ids:
        raw = await _redis_client.get(f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            results.append(FlaggedTransaction(**json.loads(raw)))
    return results


@app.get("/api/admin/flagged-transactions/{tx_id}", response_model=FlaggedTransaction)
async def get_flagged_transaction(tx_id: str):
    """Get details of a single flagged transaction."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    raw = await _redis_client.get(f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Flagged transaction not found")
    return FlaggedTransaction(**json.loads(raw))


@app.get("/api/admin/scored-transactions/{tx_id}", response_model=ScoredTransaction)
async def get_scored_transaction(tx_id: str):
    """Get details of a single scored transaction."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    raw = await _redis_client.get(f"{SCORED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Scored transaction not found")
    return ScoredTransaction(**json.loads(raw))


@app.post("/api/admin/scored-transactions/{tx_id}/rescore", response_model=ScoredTransaction)
async def rescore_transaction(tx_id: str):
    """Re-run AI risk analysis on an existing scored transaction."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    if not _analyzer_pipeline:
        raise HTTPException(status_code=503, detail="Analyzer pipeline not initialized")

    raw = await _redis_client.get(f"{SCORED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Scored transaction not found")

    existing = json.loads(raw)
    transaction = {
        "transactionId": existing.get("transactionId", ""),
        "accountId": existing.get("accountId", ""),
        "amount": existing.get("amount", 0),
        "type": existing.get("type", ""),
        "description": existing.get("description", ""),
        "category": existing.get("category", ""),
    }

    # Re-categorize first, then re-score
    cat_result = await _analyzer_pipeline.categorize(transaction)
    transaction["category"] = cat_result.category

    assessment = await _analyzer_pipeline.assess(transaction)
    now = datetime.now(timezone.utc)

    existing["category"] = cat_result.category
    existing["categoryConfidence"] = cat_result.confidence
    existing["categoryReasoning"] = cat_result.reasoning
    existing["riskScore"] = assessment.riskScore
    existing["explanation"] = assessment.explanation
    existing["flags"] = assessment.flags
    existing["scoredAt"] = now.isoformat()
    existing["status"] = "rescored"

    await _redis_client.set(
        f"{SCORED_TRANSACTION_PREFIX}{tx_id}",
        json.dumps(existing),
        ex=SCORED_TX_TTL_SECONDS,
    )

    # Update flagged status if threshold crossed
    if assessment.riskScore >= FLAGGING_THRESHOLD:
        flagged_tx = FlaggedTransaction(
            id=tx_id,
            transactionId=existing["transactionId"],
            accountId=existing["accountId"],
            amount=existing["amount"],
            type=existing["type"],
            riskScore=assessment.riskScore,
            reason=assessment.explanation,
            flags=assessment.flags,
            flaggedAt=now.isoformat(),
        )
        await _redis_client.set(
            f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}",
            flagged_tx.model_dump_json(),
        )
        await _redis_client.zadd(FLAGGED_TRANSACTIONS_KEY, {tx_id: now.timestamp()})
    else:
        # Remove from flagged if score dropped below threshold
        await _redis_client.delete(f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}")
        await _redis_client.zrem(FLAGGED_TRANSACTIONS_KEY, tx_id)

    return ScoredTransaction(**existing)


@app.put("/api/admin/flagged-transactions/{tx_id}/review", response_model=FlaggedTransaction)
async def review_flagged_transaction(tx_id: str, review: ReviewRequest):
    """Mark a flagged transaction as reviewed or cleared."""
    if not _redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    raw = await _redis_client.get(f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Flagged transaction not found")

    flagged_tx = json.loads(raw)
    flagged_tx["status"] = review.status
    flagged_tx["notes"] = review.notes

    await _redis_client.set(
        f"{FLAGGED_TRANSACTION_PREFIX}{tx_id}",
        json.dumps(flagged_tx),
    )

    return FlaggedTransaction(**flagged_tx)
