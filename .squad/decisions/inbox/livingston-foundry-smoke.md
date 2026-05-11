# Decision: Foundry Agent Smoke Tests Use Direct Port Access

**Author:** Livingston (Tester/QA)
**Date:** 2026-05-11

## Context
The ai-service exposes `/readyz` at its root, but nginx only proxies `/api/admin/*` and `/api/anomaly/*` paths to the ai-service. The `/readyz` endpoint is not reachable through the reverse proxy.

## Decision
Smoke tests hit the ai-service directly on port 8002 (configurable via `AI_SERVICE_URL` env var) for the readyz health check. The `/api/admin/transactions` categorization test goes through the proxy as normal since `/api/admin/*` is routed.

## Rationale
- Exposing `/readyz` through the proxy would require nginx config changes and isn't needed for production traffic
- Direct port access is appropriate for infrastructure health checks in smoke tests
- `AI_SERVICE_URL` env var allows override for deployed environments where port 8002 isn't directly accessible

## Impact
- Team should be aware that `AI_SERVICE_URL` must be set in CI/deployed environments if ai-service port 8002 is not directly reachable
- Consider adding an nginx route for `/api/ai/readyz` if proxy-only access is preferred
