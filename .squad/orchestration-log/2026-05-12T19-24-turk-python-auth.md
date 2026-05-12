# Turk — 2026-05-12T19:24 UTC

## Task
Add shared JWT auth to all Python/FastAPI services (Issue #26)

## Mode
Background Agent

## Status
✅ COMPLETED

## Deliverables

### Code Changes
- `budget-service`: JWT auth added; path param `userId` ignored, identity from JWT `sub`/`userId` claim
- `chatbot-service`: JWT auth added; body `user_id` ignored, JWT identity used, history endpoint validates ownership
- `ai-service`: JWT auth added; admin endpoints require `role == "admin"` in JWT claims; system prompt text stripped from endpoints
- `shared/auth.py`: Canonical auth module created and copied to each service's `app/auth.py`

### Configuration
- All services read `Jwt__Key`, `Jwt__Issuer`, `Jwt__Audience` from environment (identical to .NET services)
- Same docker-compose defaults and K8s secret (banking-secrets/jwt-key) feed all services

### Decision Document
- `.squad/decisions/inbox/turk-python-auth.md` — JWT auth implementation with coordination notes

## Summary

Implemented JWT authentication across all three Python/FastAPI services:

1. **Shared auth module** — `src/shared/auth.py` created as canonical source, copied to each service (duplication unavoidable due to Dockerfile context constraints)
2. **JWT config standardization** — All Python and .NET services use identical env vars and configuration
3. **User identity from JWT only** — Never trust client input; all identity comes from validated JWT claims
4. **System prompt protection** — API no longer leaks prompt text that could be used for adversarial attacks

All endpoints previously public now protected with JWT validation. Health/ready endpoints remain public.
