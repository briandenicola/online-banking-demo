from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from .redis_client import create_redis_client
from .repository import InMemoryApplicationRepository
from .cosmos_repository import CosmosDBApplicationRepository
from .routes import router as account_opening_router


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
logger = structlog.get_logger("account-opening-service")


class CorrelationIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        correlation_id = headers.get(b"x-correlation-id")
        correlation_value = correlation_id.decode() if correlation_id else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_value)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-correlation-id", correlation_value.encode()))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def init_telemetry() -> None:
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp_endpoint:
        return
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider = TracerProvider(resource=Resource.create({"service.name": "account-opening-service"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


init_telemetry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cosmos_endpoint = os.getenv("CosmosDb__Endpoint")
    is_production = bool(os.getenv("AZURE_CLIENT_ID"))
    if cosmos_endpoint and cosmos_endpoint != "REPLACE_WITH_COSMOS_ENDPOINT":
        try:
            from azure.cosmos import CosmosClient
            from azure.cosmos.exceptions import CosmosHttpResponseError

            credential = DefaultAzureCredential()
            cosmos_client = await asyncio.to_thread(CosmosClient, cosmos_endpoint, credential=credential)
            db = cosmos_client.get_database_client("BankingDemo")
            container = db.get_container_client("account-applications")
            app.state.repository = CosmosDBApplicationRepository(container)
            logger.info("Using Cosmos DB repository", endpoint=cosmos_endpoint)
        except CosmosHttpResponseError as exc:
            if is_production:
                logger.error("Cosmos DB initialization failed in production — aborting startup", error=str(exc))
                raise
            logger.warning("Cosmos DB request failed, falling back to in-memory", error=str(exc))
            app.state.repository = InMemoryApplicationRepository()
        except (ConnectionError, OSError) as exc:
            if is_production:
                logger.error("Cosmos DB network error in production — aborting startup", error=str(exc))
                raise
            logger.warning("Cosmos DB unreachable, falling back to in-memory", error=str(exc))
            app.state.repository = InMemoryApplicationRepository()
        except Exception as exc:
            if is_production:
                logger.error("Unexpected Cosmos DB init failure in production — aborting startup", error=str(exc))
                raise
            logger.warning("Unexpected Cosmos DB init error, falling back to in-memory", error=str(exc))
            app.state.repository = InMemoryApplicationRepository()
    else:
        logger.warning("CosmosDb__Endpoint not set — using in-memory repository")
        app.state.repository = InMemoryApplicationRepository()

    app.state.redis = await create_redis_client()

    storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if storage_account_name:
        credential = DefaultAzureCredential()
        account_url = f"https://{storage_account_name}.blob.core.windows.net"
        app.state.blob_service_client = BlobServiceClient(account_url, credential=credential)
    else:
        logger.warning("AZURE_STORAGE_ACCOUNT_NAME not set — blob uploads disabled")
        app.state.blob_service_client = None

    yield
    redis_client = app.state.redis
    if redis_client:
        close_result = redis_client.close()
        if asyncio.iscoroutine(close_result):
            await close_result


app = FastAPI(title="Account Opening Service", version="1.0.0", lifespan=lifespan)
app.state.repository = None
app.state.redis = None
app.state.blob_service_client = None

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()

app.include_router(account_opening_router)


@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@app.get("/readyz")
async def readyz():
    redis_client = app.state.redis
    if not redis_client:
        return {"status": "unavailable", "reason": "redis"}, 503
    try:
        await redis_client.ping()
    except Exception as exc:
        return {"status": "unavailable", "reason": "redis", "error": str(exc)}, 503
    return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id", uuid.uuid4().hex)
    logger.error("Unhandled exception", error=str(exc), path=request.url.path, exc_info=True)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": f"Internal server error. Correlation ID: {correlation_id}",
            "status_code": 500,
        },
    )
