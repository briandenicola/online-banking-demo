import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_redis_client

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@router.get("/readyz")
async def readyz(request: Request, redis_client=Depends(get_redis_client)):
    if not redis_client:
        return {"status": "unavailable", "reason": "redis"}, 503
    try:
        await redis_client.ping()
    except Exception as exc:
        return {"status": "unavailable", "reason": "redis", "error": str(exc)}, 503

    cosmos_endpoint = os.getenv("COSMOS_DB_ENDPOINT")
    cosmos_configured = bool(cosmos_endpoint and cosmos_endpoint != "REPLACE_WITH_COSMOS_ENDPOINT")
    repository_mode = getattr(request.app.state, "repository_mode", "unknown")
    if cosmos_configured and repository_mode != "cosmos":
        return {
            "status": "unavailable",
            "reason": "repository_mode",
            "repositoryMode": repository_mode,
        }, 503

    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
        "repositoryMode": repository_mode,
    }
