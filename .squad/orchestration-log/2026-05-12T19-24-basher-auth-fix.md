# Basher — 2026-05-12T19:24 UTC

## Task
Fix .NET auth bypass + IDOR + fail-closed (Issues #25, #27)

## Mode
Background Agent

## Status
✅ COMPLETED

## Deliverables

### Code Changes
- `.NET Services`: X-User-Id header forgery removed, ownership checks added to all user-facing endpoints
- `account-service`: GetAccount and PostAccountBalance endpoints now verify ownership (404 on cross-user access)
- `transaction-service`: Fail-closed balance validation — rejects transactions when balance cannot be validated
- `transfer-service`: Transfer model now carries UserId, verifies FromAccountId ownership before processing

### Decision Document
- `.squad/decisions/inbox/basher-auth-fix.md` — Complete auth vulnerability fixes with rationale

## Summary

Implemented critical security fixes for authentication and authorization issues:

1. **X-User-Id header forgery eliminated** — Account service no longer accepts identity from HTTP headers; JWT claim only
2. **Ownership checks** — All user-facing endpoints verify authenticated user owns resource before returning (404 prevents enumeration)
3. **Fail-closed balance validation** — Transaction service rejects transactions when balance cannot be validated (network errors, timeouts)
4. **Transfer ownership verification** — Transfer service verifies sender owns source account

### Known Issue

Service-to-service calls now fail when forwarded JWT doesn't own target resource. Proposed solutions documented (Option A: service JWT with role claim, Option B: mTLS, Option C: move balance updates to transaction-service).
