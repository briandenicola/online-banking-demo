"""
AI-powered Anomaly Detection Service using Azure AI Foundry.
"""
import contextlib
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.auth import assert_token_configuration
from app.config import CorrelationIdMiddleware, configure_logging, init_telemetry
from app.routes import router as api_router
from app.services.anomaly_service import lifespan

configure_logging()
logger = structlog.get_logger("ai-service")
init_telemetry()

# Token posture is checked before anything else can serve a request (issue #334). Fail closed:
# a service that boots holding a retired symmetric secret, or holding signing material it has
# no business having, looks healthy while misrepresenting its own security posture.
@contextlib.asynccontextmanager
async def _guarded_lifespan(_app: FastAPI):
    assert_token_configuration("ai-service")
    async with lifespan(_app):
        yield


app = FastAPI(title="Anomaly Detection Service", version="2.0.0", lifespan=_guarded_lifespan)


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

app.include_router(api_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from fastapi.responses import JSONResponse
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
