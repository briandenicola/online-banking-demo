from datetime import datetime

from fastapi import APIRouter, Depends

from app.dependencies import get_redis_client

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@router.get("/readyz")
async def readyz(redis_client=Depends(get_redis_client)):
    if not redis_client:
        return {"status": "unavailable", "reason": "redis"}, 503
    try:
        await redis_client.ping()
    except Exception as exc:
        return {"status": "unavailable", "reason": "redis", "error": str(exc)}, 503
    return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}
