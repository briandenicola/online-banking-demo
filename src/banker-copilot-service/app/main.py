"""Banker Copilot harness.

This service registers ZERO write tools. Its only write-shaped affordance is `propose_action`,
which hands a proposal to `authority-service` — the sole executor of agent-originated writes.
The split between the two services IS the enforcement mechanism for epic #332.
"""

from __future__ import annotations

import os
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.config import SERVICE_NAME, CorrelationIdMiddleware, configure_logging, init_telemetry
from app.lifespan import lifespan
from app.routes import copilot_router, health_router

configure_logging()
logger = structlog.get_logger(SERVICE_NAME)
init_telemetry()

app = FastAPI(title="Banker Copilot Service", version="1.0.0", lifespan=lifespan)

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

app.include_router(copilot_router)
app.include_router(health_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id", uuid.uuid4().hex)
    logger.error("Unhandled exception", error=str(exc), path=request.url.path, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": f"Internal server error. Correlation ID: {correlation_id}",
            "status_code": 500,
        },
    )
