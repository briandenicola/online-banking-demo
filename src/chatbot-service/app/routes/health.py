import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import AGENT_FRAMEWORK_AVAILABLE, DefaultAzureCredential
from app.services import agent_service
from app.services.chat_service import get_health_status

router = APIRouter()


@router.get("/health")
async def health():
    return get_health_status()


@router.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "chatbot-service", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/readyz")
async def ready():
    checks = {"azure_credential": False, "agent_ready": agent_service.agent_ready}

    if AGENT_FRAMEWORK_AVAILABLE and DefaultAzureCredential:
        try:
            credential = DefaultAzureCredential()
            token = await asyncio.to_thread(credential.get_token, "https://cognitiveservices.azure.com/.default")
            checks["azure_credential"] = token is not None
        except Exception:
            checks["azure_credential"] = False
    else:
        checks["azure_credential"] = None

    all_ready = checks.get("azure_credential") is not False and checks["agent_ready"]
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}
