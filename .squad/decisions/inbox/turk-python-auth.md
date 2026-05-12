# Decision: JWT Authentication for Python/FastAPI Services

**Author:** Turk (Backend Dev)
**Date:** 2026-05-12
**Status:** Implemented
**Issue:** #26

## Context

All three Python/FastAPI services (budget-service, chatbot-service, ai-service) had zero authentication — every endpoint was publicly accessible. This was flagged as CRITICAL in the security audit (Issue #18).

## Decision

### 1. Shared auth module with per-service copies
Created `src/shared/auth.py` as canonical source, copied into each service's `app/auth.py`. This is necessary because each Python service's Dockerfile builds from its own directory context (`./src/<service>`), making a shared import path impossible without restructuring build contexts.

**Trade-off:** Duplication vs. Docker build simplicity. Accepted because the auth module is small (~100 LOC) and stable. A future improvement could restructure Docker contexts to `./src` and share the module properly.

### 2. JWT config via Jwt__Key env var (matching .NET)
Python services read `Jwt__Key`, `Jwt__Issuer`, `Jwt__Audience` — identical to .NET services. This means:
- Same docker-compose defaults work across all services
- Same K8s secret (banking-secrets/jwt-key) feeds all services
- No separate secret management for Python vs .NET

### 3. User identity from JWT only — never trust client input
- budget-service: path param `userId` is ignored; identity comes from JWT `sub`/`userId` claim
- chatbot-service: `user_id` in ChatRequest body is ignored; JWT identity used. History endpoint validates ownership.
- ai-service: admin endpoints require `role == "admin"` in JWT claims

### 4. System prompt text stripped from /api/admin/prompts
The ai-service prompts endpoint previously returned full system prompt text. Now returns only name, type, and enabled status. This prevents prompt leakage that could be used to craft adversarial inputs.

## Coordination Notes

- **Linus (Frontend):** The UI must send `Authorization: Bearer <token>` headers on all API calls to Python services. Health/ready endpoints are excluded.
- **Basher (Backend):** .NET services already validate JWT with the same key. No changes needed on .NET side.
- **Livingston (QA):** Smoke tests hitting Python service endpoints will need valid JWT tokens. Unauthenticated calls to protected endpoints should return 401.
