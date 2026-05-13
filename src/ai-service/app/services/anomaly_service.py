"""
AI-powered Anomaly Detection Service using Azure AI Foundry.
"""
import abc
import asyncio
import base64
import json
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import redis.asyncio as redis
import structlog
from fastapi import FastAPI, Request
from opentelemetry import trace

from app.config import AGENT_FRAMEWORK_AVAILABLE, Agent, DefaultAzureCredential, FoundryAgent, FoundryChatClient
from app.models import CategoryResult, RiskAssessment, ScoredTransaction

logger = structlog.get_logger("ai-service")

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

@dataclass
class AnomalyState:
    redis_client: Optional[redis.Redis] = None
    analyzer_pipeline: Optional["AnalyzerPipeline"] = None
    foundry_credential: Any = None
    foundry_endpoint: Optional[str] = None
    foundry_model: Optional[str] = None
    token_refresh_task: Optional[asyncio.Task] = None


def get_anomaly_state(request: Request) -> AnomalyState:
    return request.app.state.anomaly_state


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
        self._agent: Optional["FoundryAgent"] = None
        self._ready = False
        self._ai_calls_today = 0
        self._ai_calls_date = ""
        self._ai_calls_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "foundry-risk"

    @property
    def enabled(self) -> bool:
        return self._ready

    def initialize(self, agent: "FoundryAgent"):
        """Initialize with a persistent FoundryAgent instance."""
        self._agent = agent
        self._ready = True

    async def analyze(self, transaction: dict) -> RiskAssessment:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self._ai_calls_lock:
            if self._ai_calls_date != today:
                self._ai_calls_today = 0
                self._ai_calls_date = today

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("foundry.risk-assessment") as span:
            span.set_attribute("analyzer.name", self.name)
            span.set_attribute("transaction.amount", transaction.get("amount", 0))
            span.set_attribute("transaction.type", transaction.get("type", ""))

            try:
                # Pseudonymize account ID — send only last 4 chars to LLM
                raw_account_id = transaction.get("accountId", "")
                masked_account = f"****{raw_account_id[-4:]}" if len(raw_account_id) >= 4 else "****"

                user_message = (
                    f"Assess this transaction:\n"
                    f"- Amount: ${transaction.get('amount', 0):,.2f}\n"
                    f"- Type: {transaction.get('type', 'Unknown')}\n"
                    f"- Description: {transaction.get('description', 'N/A')}\n"
                    f"- Category: {transaction.get('category', 'N/A')}\n"
                    f"- Account: {masked_account}"
                )

                session = self._agent.create_session()
                response = await self._agent.run(user_message, session=session)

                async with self._ai_calls_lock:
                    self._ai_calls_today += 1
                    calls_today = self._ai_calls_today
                span.set_attribute("ai.calls_today", calls_today)

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

    @property
    def ai_calls_today(self) -> int:
        return self._ai_calls_today

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
        self._agent: Optional["FoundryAgent"] = None
        self._ready = False

    @property
    def name(self) -> str:
        return "foundry-categorizer"

    @property
    def enabled(self) -> bool:
        return self._ready

    def initialize(self, agent: "FoundryAgent"):
        """Initialize with a persistent FoundryAgent instance."""
        self._agent = agent
        self._ready = True

    async def categorize(self, transaction: dict, hints: list[str] | None = None) -> CategoryResult:
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("foundry.transaction-categorization") as span:
            span.set_attribute("categorizer.name", self.name)
            span.set_attribute("transaction.amount", transaction.get("amount", 0))

            try:
                hint_text = ""
                if hints:
                    hint_text = "\nUser custom categories: " + ", ".join(hints)

                user_message = (
                    f"Categorize this transaction:\n"
                    f"- Amount: ${transaction.get('amount', 0):,.2f}\n"
                    f"- Type: {transaction.get('type', 'Unknown')}\n"
                    f"- Description: {transaction.get('description', 'N/A')}\n"
                    f"- Current Category: {transaction.get('category', 'Uncategorized')}"
                    f"{hint_text}"
                )

                session = self._agent.create_session()
                response = await self._agent.run(user_message, session=session)

                result = self._parse_response(str(response))
                span.set_attribute("category.result", result.category)
                span.set_attribute("category.confidence", result.confidence)
                return result

            except Exception as e:
                logger.error(f"Foundry categorization failed: {e}")
                span.record_exception(e)
                return CategoryResult(
                    category=transaction.get("category", "Uncategorized"),
                    confidence=0.0,
                    reasoning="Categorization unavailable"
                )

    def _parse_response(self, response: str) -> CategoryResult:
        """Parse the AI response into a CategoryResult."""
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
                reasoning=data.get("reasoning", "No reasoning provided"),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse categorization response: {e}, raw: {response[:200]}")
            return CategoryResult(
                category="Uncategorized",
                confidence=0.0,
                reasoning="Failed to parse categorization response"
            )


def get_ai_calls_today(analyzer_pipeline: Optional["AnalyzerPipeline"]) -> int:
    if not analyzer_pipeline:
        return 0
    for analyzer in analyzer_pipeline.analyzers:
        if isinstance(analyzer, FoundryRiskAnalyzer):
            return analyzer.ai_calls_today
    return 0


class AnalyzerPipeline:
    """Pipeline for combining multiple analyzers."""

    def __init__(self):
        self._analyzers: list[BaseAnalyzer] = []
        self._categorizers: list[BaseCategorizer] = []

    def register(self, analyzer: BaseAnalyzer):
        self._analyzers.append(analyzer)

    def register_categorizer(self, categorizer: BaseCategorizer):
        self._categorizers.append(categorizer)

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
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to decode token payload: {e}")
        return ""


async def _refresh_redis_token(client, credential):
    """Periodically refresh the Entra ID token on the Redis connection."""
    while True:
        await asyncio.sleep(45 * 60)
        try:
            token = await asyncio.to_thread(credential.get_token, REDIS_SCOPE)
            oid = _extract_oid_from_token(token.token)
            await client.execute_command("AUTH", oid, token.token)
            logger.info("✅ Redis token refreshed")
        except asyncio.CancelledError:
            raise
        except redis.RedisError as e:
            logger.warning(f"⚠️ Failed to refresh Redis auth command: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to refresh Redis token: {e}")


async def _create_redis_client() -> tuple[redis.Redis, Optional[asyncio.Task]]:
    """Create a Redis client supporting both Azure Managed Redis (Entra ID cluster)
    and local docker-compose connections (standard single-node)."""
    conn_str = os.getenv("REDIS_CONNECTION_STRING", "redis:6379")
    parsed = _parse_redis_connection_string(conn_str)

    azure_client_id = os.getenv("AZURE_CLIENT_ID")

    if azure_client_id and AGENT_FRAMEWORK_AVAILABLE:
        # Azure Managed Redis uses OSS Cluster mode — must use RedisCluster
        credential = DefaultAzureCredential()
        token = await asyncio.to_thread(credential.get_token, REDIS_SCOPE)
        oid = _extract_oid_from_token(token.token)
        logger.info(f"Using Entra ID token for Redis authentication (OID: {oid})")

        client = redis.RedisCluster(
            host=parsed["host"],
            port=parsed["port"],
            username=oid,
            password=token.token,
            ssl=parsed["ssl"],
            ssl_cert_reqs="required",
            decode_responses=True,
        )

        token_refresh_task = asyncio.create_task(_refresh_redis_token(client, credential))
        return client, token_refresh_task

    # Local dev: standard single-node Redis
    kwargs = {
        "host": parsed["host"],
        "port": parsed["port"],
        "decode_responses": True,
    }
    if parsed["ssl"]:
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = "required"
    if parsed["password"]:
        kwargs["password"] = parsed["password"]

    logger.info("Using connection string for Redis authentication (local dev)")
    return redis.Redis(**kwargs), None


# ============================================================
# Scoring & Storage
# ============================================================

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8080")


async def _fetch_user_category_hints(user_id: str | None) -> list[str]:
    """Fetch user-defined category preferences from user-service."""
    if not user_id:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{USER_SERVICE_URL}/api/users/{user_id}/categories")
            if resp.status_code == 200:
                data = resp.json()
                hints = data.get("categories", [])
                if hints:
                    logger.info(f"📋 Loaded {len(hints)} category hints for user {user_id}")
                return hints
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Failed to fetch category hints for user {user_id}: {e}")
    return []


async def score_and_store_transaction(
    transaction: dict,
    analyzer_pipeline: "AnalyzerPipeline",
    redis_client: Optional[redis.Redis],
) -> ScoredTransaction:
    """Categorize and score a transaction, then store results."""
    if not analyzer_pipeline:
        raise ValueError("Analyzer pipeline not initialized")

    # Step 1: Categorize first (separate concern from risk)
    existing_category = transaction.get("category", "")
    if not existing_category or existing_category == "Uncategorized":
        user_hints = await _fetch_user_category_hints(transaction.get("userId"))
        cat_result = await analyzer_pipeline.categorize(transaction, hints=user_hints or None)
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
    assessment = await analyzer_pipeline.assess(transaction_with_category)
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
        userId=transaction.get("userId", ""),
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
        status="scored",
    )

    # Store in Redis
    if redis_client:
        scored_key = f"{SCORED_TRANSACTION_PREFIX}{scored_id}"
        await redis_client.set(scored_key, scored_tx.json(), ex=SCORED_TX_TTL_SECONDS)

        # Add to sorted set (by score)
        await redis_client.zadd(SCORED_TRANSACTIONS_KEY, {scored_id: assessment.riskScore})

        # If high risk, flag it
        if assessment.riskScore >= FLAGGING_THRESHOLD:
            flagged_tx = {
                "id": scored_id,
                "transactionId": scored_tx.transactionId,
                "accountId": scored_tx.accountId,
                "amount": scored_tx.amount,
                "type": scored_tx.type,
                "riskScore": scored_tx.riskScore,
                "reason": scored_tx.explanation,
                "flags": scored_tx.flags,
                "flaggedAt": now.isoformat(),
                "status": "pending",
            }
            flagged_key = f"{FLAGGED_TRANSACTION_PREFIX}{scored_id}"
            await redis_client.set(flagged_key, json.dumps(flagged_tx))
            await redis_client.zadd(FLAGGED_TRANSACTIONS_KEY, {scored_id: assessment.riskScore})
            logger.info(f"🚩 Transaction flagged for review: {scored_id}")

    return scored_tx


async def consume_redis_stream(redis_client: redis.Redis, analyzer_pipeline: "AnalyzerPipeline"):
    """Consume transactions from Redis Stream and analyze them."""
    try:
        await redis_client.xgroup_create(name=STREAM_NAME, groupname=CONSUMER_GROUP, id="0", mkstream=True)
        logger.info(f"Created consumer group {CONSUMER_GROUP} on stream {STREAM_NAME}")
    except redis.ResponseError as e:
        # BUSYGROUP — group already exists from a prior run. Expected on every
        # restart after the first; without this guard the entire consumer task
        # silently dies and no transactions are ever scored.
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group {CONSUMER_GROUP} already exists — resuming")
        else:
            logger.error(f"Failed to create consumer group: {e}")
            raise
    backoff = 1
    _failure_counts: dict[str, int] = {}
    dlq_stream = f"{STREAM_NAME}-dlq"
    max_retries = int(os.getenv("DLQ_MAX_RETRIES", "3"))

    while True:
        try:
            messages = await redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=10,
                block=1000,
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

                            scored = await score_and_store_transaction(data, analyzer_pipeline, redis_client)
                            logger.info(
                                f"Scored transaction {scored.transactionId}: "
                                f"risk={scored.riskScore:.2f}"
                            )

                        # ACK only after successful processing
                        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                        _failure_counts.pop(message_id, None)

                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        # Do NOT ACK — message stays in pending list for retry
                        fail_count = _failure_counts.get(message_id, 0) + 1
                        _failure_counts[message_id] = fail_count
                        logger.error(
                            f"Error processing message {message_id} "
                            f"(attempt {fail_count}/{max_retries}): {e}"
                        )
                        if fail_count >= max_retries:
                            # Dead-letter: move to DLQ stream, then ACK original
                            try:
                                dlq_fields = dict(fields)
                                dlq_fields["original_id"] = message_id
                                dlq_fields["error"] = str(e)[:500]
                                dlq_fields["attempts"] = str(fail_count)
                                await redis_client.xadd(dlq_stream, dlq_fields)
                                await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
                                _failure_counts.pop(message_id, None)
                                logger.warning(
                                    f"Message {message_id} moved to DLQ after "
                                    f"{fail_count} failed attempts"
                                )
                            except redis.RedisError as dlq_err:
                                logger.error(f"Failed to move {message_id} to DLQ: {dlq_err}")

        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}. Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except redis.ResponseError as e:
            # Azure Managed Redis proxy returns 11613 when BLOCK commands
            # can't be redirected during resharding — just retry immediately
            if "11613" in str(e):
                await asyncio.sleep(1)
                continue
            logger.error(f"Redis response error in consumer loop: {e}. Retrying in {backoff}s...")
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
    state = AnomalyState()
    app.state.anomaly_state = state

    logger.info("=" * 60)
    logger.info("🔍 Anomaly Detection Service — Startup (v2.0 Foundry)")
    logger.info("=" * 60)

    # Initialize analyzer pipeline
    state.analyzer_pipeline = AnalyzerPipeline()

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
            state.foundry_credential = credential
            state.foundry_endpoint = endpoint
            state.foundry_model = model_name
            token = await asyncio.to_thread(credential.get_token, "https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Azure credential acquired (expires: {token.expires_on})")

            risk_agent = FoundryAgent(
                project_endpoint=endpoint,
                credential=credential,
                agent_name="risk-assessor",
                agent_version="1",
                description="Financial transaction risk scoring agent",
                instructions=FoundryRiskAnalyzer.SYSTEM_PROMPT,
            )
            foundry_analyzer.initialize(risk_agent)
            logger.info("✅ Foundry risk agent created (persistent)")

            categorizer_agent = FoundryAgent(
                project_endpoint=endpoint,
                credential=credential,
                agent_name="transaction-categorizer",
                agent_version="1",
                description="Financial transaction categorization agent",
                instructions=FoundryCategorizer.SYSTEM_PROMPT,
            )
            foundry_categorizer.initialize(categorizer_agent)
            logger.info("✅ Foundry categorizer agent created (persistent)")
        except Exception as e:
            logger.error(f"❌ Foundry initialization failed: {e}")
    else:
        logger.warning("⚠️ Foundry not available — using fallback scoring")

    state.analyzer_pipeline.register(foundry_analyzer)
    state.analyzer_pipeline.register_categorizer(foundry_categorizer)

    # Future analyzers/categorizers can be registered here:
    # _analyzer_pipeline.register(EvalAnalyzer())
    # _analyzer_pipeline.register(VelocityAnalyzer())
    # _analyzer_pipeline.register_categorizer(UserHintCategorizer())

    # Initialize Redis
    redis_client, token_refresh_task = await _create_redis_client()
    state.redis_client = redis_client
    state.token_refresh_task = token_refresh_task

    try:
        await redis_client.ping()
        logger.info("✅ Redis connectivity verified")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")

    # Start the consumer as a background task
    consumer_task = asyncio.create_task(consume_redis_stream(redis_client, state.analyzer_pipeline))
    logger.info("🟢 Anomaly detection service ready — consuming from Redis Stream")
    logger.info("=" * 60)

    yield

    # Shutdown
    consumer_task.cancel()
    if state.token_refresh_task:
        state.token_refresh_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    state.redis_client = None
