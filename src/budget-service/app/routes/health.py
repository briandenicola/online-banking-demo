import asyncio
from datetime import datetime

from fastapi import APIRouter

from app.config import AZURE_AVAILABLE, DefaultAzureCredential

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/healthz")
async def healthz():
    return {"status": "healthy", "service": "budget-service", "timestamp": datetime.utcnow().isoformat()}


@router.get("/readyz")
async def ready():
    checks = {"azure_credential": False}

    if AZURE_AVAILABLE and DefaultAzureCredential:
        try:
            credential = DefaultAzureCredential()
            token = await asyncio.to_thread(credential.get_token, "https://cognitiveservices.azure.com/.default")
            checks["azure_credential"] = token is not None
        except Exception:
            checks["azure_credential"] = False
    else:
        checks["azure_credential"] = None  # Not configured

    status = "ready" if checks.get("azure_credential") is not False else "degraded"
    return {"status": status, "checks": checks}
