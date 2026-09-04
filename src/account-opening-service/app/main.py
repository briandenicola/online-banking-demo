from __future__ import annotations

import contextlib

import os
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.config import CorrelationIdMiddleware, configure_logging, init_telemetry
from app.routes import router as account_opening_router
from app.routes.health import router as health_router
from app.auth import assert_token_configuration
from app.services.lifecycle import lifespan
from app.state_machine import ApplicationStateMachine

configure_logging()
logger = structlog.get_logger("account-opening-service")
init_telemetry()

# Token posture is checked before anything else can serve a request (issue #334). Fail closed:
# a service that boots holding a retired symmetric secret, or holding signing material it has
# no business having, looks healthy while misrepresenting its own security posture.
@contextlib.asynccontextmanager
async def _guarded_lifespan(_app: FastAPI):
    assert_token_configuration("account-opening-service")
    async with lifespan(_app):
        yield


app = FastAPI(title="Account Opening Service", version="1.0.0", lifespan=_guarded_lifespan)

app.state.repository = None
app.state.redis = None
app.state.blob_service_client = None
app.state.state_machine = ApplicationStateMachine()

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
app.include_router(health_router)


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
