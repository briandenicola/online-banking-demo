# Decision: Auth Vulnerability Fixes — Service-to-Service Impact

**Date:** 2026-05-13
**Author:** Basher
**Priority:** P0
**Status:** Implemented (with known follow-up needed)
**Related Issues:** #25, #27

## What Changed

1. **X-User-Id header forgery removed** — account-service no longer accepts identity from HTTP headers. JWT claim only.
2. **Ownership checks added** — all user-facing endpoints now verify the authenticated user owns the resource before returning it. Ownership failures return 404 (not 403) to prevent resource enumeration.
3. **Fail-closed balance validation** — transaction-service now rejects transactions when balance cannot be validated (network errors, timeouts, service down). Previously it silently allowed them through.
4. **Transfer ownership** — Transfer model now carries UserId. Transfer service verifies FromAccountId belongs to the authenticated user before processing.

## Known Breaking Change: Service-to-Service Calls

Adding ownership checks to `GET /api/accounts/{id}` and `POST /api/accounts/{id}/balance` affects service-to-service flows where the forwarded user JWT doesn't own the target resource.

**Example:** During a transfer, transaction-service creates a credit transaction for the *destination* account and calls `POST /api/accounts/{toAccountId}/balance`. The forwarded JWT belongs to the *sender*, not the destination account owner. This call will now fail with 404.

### Proposed Solution (needs Brian's input)

Introduce a **service identity** mechanism:
- Option A: Service-to-service calls use a dedicated service JWT with a `role: service` claim. Balance update and account lookup endpoints allow access when this role is present.
- Option B: Use mTLS-based identity (Istio peer authentication) to identify trusted internal callers and skip ownership checks for internal mesh traffic.
- Option C: Move balance updates into the transaction-service itself (it already has Cosmos access) so it doesn't need to call account-service at all.

**Recommendation:** Option A is simplest to implement short-term. Option C is architecturally cleanest but requires more refactoring.

## Fail-Closed Rationale

In a banking system, "fail open" on balance checks means a user could overdraw their account when account-service is temporarily down. This is unacceptable. The new behavior rejects the transaction with a clear error message. Retry logic is a separate concern (flagged as future work).
