from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@router.get("/readyz")
async def readyz(request: Request):
    redis_client = request.app.state.redis
    if not redis_client:
        return {"status": "unavailable", "reason": "redis"}, 503
    try:
        await redis_client.ping()
    except Exception as exc:
        return {"status": "unavailable", "reason": "redis", "error": str(exc)}, 503
    return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}
