from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import legacy_config_names_in_use
from app.events.envelope import utc_now_iso
from app.tools.manifest import READ_METHODS

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@router.get("/readyz")
async def readyz(request: Request):
    state = request.app.state
    registry = getattr(state, "registry", None)

    if registry is None:
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "reason": "manifest_not_loaded"}
        )

    write_tools = registry.write_tools()
    if write_tools:
        # Unreachable via the loader, asserted again here. The claim "zero write tools" is
        # visible to an operator on a live process, not only to a test on a build agent.
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "reason": "write_tools_registered",
                "writeTools": [tool.tool_id for tool in write_tools],
            },
        )

    settings = state.settings
    store_mode = getattr(state, "store_mode", "unknown")
    if settings.cosmos_configured and store_mode != "cosmos":
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": "store_mode", "storeMode": store_mode},
        )

    return {
        "status": "ready",
        "timestamp": utc_now_iso(),
        "manifestId": registry.manifest.manifest_id,
        "readTools": len(registry.tools),
        "writeTools": 0,
        "methods": sorted(registry.methods_in_use()),
        "readMethodAllowlist": sorted(READ_METHODS),
        "storeMode": store_mode,
        "credentialMode": settings.credential_mode,
        "plannerMode": getattr(state, "planner_mode", "unknown"),
        "authorityConfigured": bool(settings.authority_service_url),
        # Deployed config still using a superseded env var name. Empty is the healthy state.
        # Reported rather than logged once at startup, so a stale ConfigMap is visible to
        # whoever is looking at the pod rather than to whoever read the boot logs.
        "legacyConfigNames": legacy_config_names_in_use(),
    }
